import ftplib
import ocrmypdf
import ocrmypdf.exceptions
import pypdf
import pypdf.errors
import tempfile
import threading
import uuid
from datetime import datetime, timedelta
from enum import Enum
from io import BytesIO
from multiprocessing import Process
from pathlib import Path
from queue import Queue, Empty
from typing import BinaryIO

from .core import *

class TaskState(Enum):
    SCHEDULED = 0
    WAITING = 1
    RUNNING = 2
    FINISHED = 3
    ABORTED = 4
    FAILED = 5
    DEPENDENCY_FAILED = 6

class Task:
    
    def __init__(self) -> None:
        self.state = TaskState.SCHEDULED
        self.uuid = str(uuid.uuid4())
        self.dependencies: list[Task] = []
        self.childrens: list[Task] = []
        self.t_created: datetime = datetime.now()
        self.t_start: datetime|None = None
        self.t_end: datetime|None = None
        self.dependencies_artificats: dict[str, BinaryIO] = {}

    def run(self, artificats: list[BinaryIO]) -> list[BinaryIO]:
        """ Called when a Task is executed """
        raise NotImplementedError(f"The given task does not implement a run() method")

    def __repr__(self) -> str:
        return f"<{str(self)}>"
    
    def __str__(self) -> str:
        return f"Generic Task {self.uuid}"
    
    def runtime(self) -> timedelta|None:
        if self.t_start is None or self.t_end is None:
            return None
        return self.t_end - self.t_start
    
    def send_artifacts_to(self, other_task: "Task") -> None:
        other_task.dependencies.append(self)
        self.childrens.append(other_task)

    def put(self, **f_handles: BinaryIO) -> None:  
        for name, f_handle in f_handles.items():
            for c in self.childrens:
                temp_file = tempfile.TemporaryFile(prefix="pyPDFserver_artifact")
                temp_file.write(f_handle.read())
                c.dependencies_artificats[name] = temp_file
        

    
class TaskException(Exception):
    """ Should be raise inside a Task's run() function when an expected error happens """

    def __init__(self, message: str, *args: object) -> None:
        super().__init__(*args)
        self.message = message

class UploadTask(Task):
    """
    Upload an file to an external FTP server
    """

    def __init__(self, 
                 file: Path, 
                 address: tuple[str, int], 
                 username: str, password: str, 
                 folder: str, 
                 tls: bool,
                 source_address: tuple[str, int]|None = None) -> None:
        super().__init__()
        self.file = file
        self.address = address
        self.username = username
        self.password = password
        self.folder = folder
        self.tls = tls
        self.source_address = source_address

        with open(self.file, "rb") as f:
            self.bytes = BytesIO(f.read())

    def run(self) -> None:
        if self.tls:
            ftp = ftplib.FTP_TLS()
        else:
            ftp = ftplib.FTP()
        try:
            ftp.connect(self.address[0], self.address[1], timeout=30, source_address=self.source_address)
            if isinstance(ftp, ftplib.FTP_TLS):
                ftp.auth()
                ftp.prot_p()
            ftp.login(user=self.username, passwd=self.password)
            ftp.cwd(self.folder)
            logger.debug(f"Connected to upload FTP server ('{ftp.getwelcome()}')")
            files = ftp.nlst()

            if self.file.name in files:
                raise TaskException(f"File already present on the server")
            
            ftp.storbinary(f"STOR {self.file.name}", self.bytes)
            logger.info(f"Uploaded file '{self.file.name}' to the server")
        except ftplib.all_errors as ex:
            raise TaskException(f"Failed to upload the file: {str(ex)}")
        finally:
            self.bytes.close()
            ftp.close()    

    def __str__(self) -> str:
        return f"Upload '{self.file.name}'"

class PDFTask(Task):

    def __init__(self, file: Path) -> None:
        super().__init__()
        self.file = file
        self.reader: pypdf.PdfReader|None = None
        self.num_pages: int|None = None

        with open(self.file, "rb") as f:
            self.bytes = BytesIO(f.read())

    def run(self) -> None:
        try:
            self.reader = pypdf.PdfReader(self.bytes)
            self.num_pages = self.reader.get_num_pages()
        except pypdf.errors.PyPdfError as ex:
            logger.warning(f"Failed to decode '{self.file.name}': {str(ex)}")
            raise TaskException(f"Failed to decode '{self.file.name}': {str(ex)}")
        
    def __str__(self) -> str:
        return f"Decode PDF '{self.file.name}'"
        

class OCRTask(Task):

    def __init__(self, file: Path, language: str, optimize: int, deskew: bool, rotate_pages: bool, Tasks: int = 1, tesseract_timeout: int = 60) -> None:
        super().__init__()
        self.input = file
        self.output = file.parent / f"{file.stem}_OCR{file.suffix}"
        self.language = language
        self.deskew = deskew
        self.optimize = optimize
        self.rotate_pages = rotate_pages
        self.Tasks = Tasks
        self.tesseract_timeout = tesseract_timeout

    def run(self) -> None:
        try:
            exit_code = ocrmypdf.ocr(self.input, self.output, 
                                        language=self.language,
                                        deskew=self.deskew,
                                        rotate_pages=self.rotate_pages,
                                        Tasks=self.Tasks,
                                        optimize=self.optimize,
                                        tesseract_timeout=self.tesseract_timeout
                                        )
        except ocrmypdf.exceptions.ExitCodeException as ex:
            raise TaskException(ex.message)
        if not exit_code == ocrmypdf.ExitCode.ok:
            raise TaskException(exit_code.name)
        
    def __repr__(self) -> str:
        return f"<OCR '{self.input.name}' (lang={self.language}, deskew={self.deskew}, optimize={self.optimize}, rotate_pages: {self.rotate_pages})>"

    def __str__(self) -> str:
        return f"OCR '{self.input.name}'>"
        
class DuplexTask(Task):

    def __init__(self) -> None:
        super().__init__()


task_finished: list[Task] = []
task_queue: Queue[Task] = Queue()
task_priority_queue: Queue[Task] = Queue()
task_waiting_list: list[Task] = []
task: Task|None = None

def loop() -> None:
    """ Implements the main thread loop """
    global task
    while True:
        task = None

        clean_up()

        # Check first if a waiting task has failed dependencies (move it to finished task list) or is ready for scheduling (put to priority queue)
        for t in task_waiting_list.copy():
            task_ready = True
            for d in t.dependencies:
                match d.state:
                    case TaskState.SCHEDULED | TaskState.WAITING | TaskState.RUNNING:
                        task_ready = False
                    case TaskState.FINISHED:
                        pass
                    case _:
                        task_ready = False
                        t.state = TaskState.DEPENDENCY_FAILED
                        break
            if t.state != TaskState.WAITING:
                task_waiting_list.remove(t)
                task_finished.append(t)
                logger.debug(f"Task '{str(t)}' was marked as DEPENDENCY_FAILED")
            elif task_ready:
                t.state = TaskState.SCHEDULED
                task_waiting_list.remove(t)
                task_priority_queue.put(t)
                logger.debug(f"Task '{str(t)}' was moved from WAITING to SCHEDULED")

        # Get next task
        try:
            task = task_priority_queue.get_nowait()
        except Empty:
            task = task_queue.get(block=True)

        if task.state != TaskState.SCHEDULED:
            task_finished.append(task)
            logger.debug(f"Unexpected TaskState {task.state} for task '{task}' in queue")
            continue

        task.state = TaskState.RUNNING

        # Check if all dependencies for the task are resolved
        dependencies_resolved = True
        for d in task.dependencies:
            match d.state:
                case TaskState.SCHEDULED | TaskState.WAITING | TaskState.RUNNING:
                    dependencies_resolved = False
                case TaskState.FINISHED:
                    pass
                case _:
                    dependencies_resolved = False
                    task.state = TaskState.DEPENDENCY_FAILED
                    break
        if task.state != TaskState.RUNNING:
            task_finished.append(task)
            logger.debug(f"Task '{str(task)}' was marked as DEPENDENCY_FAILED")
            continue
        elif not dependencies_resolved:
            task.state = TaskState.WAITING
            task_waiting_list.append(task)
            logger.debug(f"Task '{str(task)}' was marked as WAITING")
            continue

        logger.debug(f"Executing task '{str(task)}'")
        
        try:
            task.run()
        except TaskException as ex:
            task.state = TaskState.FAILED
            logger.info(f"Task {str(task)}: {ex.message}")
        except Exception as ex:
            task.state = TaskState.FAILED
            logger.warning(f"Failed to process task '{str(task)}': ", exc_info=True)
        else:
            task.state = TaskState.FINISHED
            logger.debug(f"Finished task '{str(task)}'")

        task = None

def clean_up() -> None:
    """ Clean up the task lists """
    for t in task_finished.copy():
        if (datetime.now() - t.t_created).total_seconds() > (60*60):
            task_finished.remove(t)
            logger.debug(f"Task '{str(t)}' timed out")
    for t in task_waiting_list.copy():
        if (datetime.now() - t.t_created).total_seconds() > (60*60):
            task_waiting_list.remove(t)
            logger.debug(f"Task '{str(t)}' timed out")

def run() -> None:
    """ Start the server loop """
    process.start()

def abort() -> None:
    """ Abort the current task by terminating the current process loop and restarting it """
    # Use thread to join the thread (as terminate does not wait)
    def _terminate() -> None:
        process.terminate()
        process.join()
        if task is not None:
            task.state = TaskState.ABORTED
        run()
    if not process.is_alive():
        return
    threading.Thread(target=_terminate, name="Abort pdf server loop").run()

process = Process(target=loop)
