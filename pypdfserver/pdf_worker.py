import ftplib
import ocrmypdf
import ocrmypdf.exceptions
import pypdf
import pypdf.errors
import tempfile
import threading
import uuid
import weakref
from datetime import datetime, timedelta
from enum import Enum
from io import BytesIO
from multiprocessing import Process
from pathlib import Path
from queue import Queue, Empty
from typing import Any

from .core import *

class TaskState(Enum):
    SCHEDULED = 0
    WAITING = 1
    RUNNING = 2
    FINISHED = 3
    ABORTED = 4
    FAILED = 5
    DEPENDENCY_FAILED = 6

class Artifact:

    temp_dir = Path(pyPDFserver_temp_dir.name)

    def __init__(self, task: "Task", name: str) -> None:
        self.task = task
        self.name = name
        logger.debug(f"Created artifact '{name}' for task '{str(task)}'")

    def cleanup(self) -> None:
        """ Clean up the ressources of the artifact """
        pass

    def __del__(self) -> None:
        self.cleanup()

    def __str__(self) -> str:
        return f"Artifact '{self.name}'"
    
    def __repr__(self) -> str:
        return f"<{str(self)}>"

class FileArtifact(Artifact):

    def __init__(self, task: "Task", name: str) -> None:
        super().__init__(task, name)
        self.temp_file = tempfile.NamedTemporaryFile(dir=Artifact.temp_dir / "artifacts", prefix=f"task_{task.uuid}_{name}", delete_on_close=False, delete=True)
        self.path = Path(self.temp_file.name)
        self._finalizer = weakref.finalize(self, FileArtifact._cleanup, self.path, self.name, str(self.task))
        try:
            logger.debug(f"Created temporary file '{self.path.relative_to(Artifact.temp_dir)}' for artifact '{name}' of task '{str(task)}'")
        except ValueError:
            logger.error(f"Temporary file '{self.path}' is not in the temporary directory ('{Artifact.temp_dir}')")

    def cleanup(self) -> None:
        if not self.temp_file.closed:
            self.temp_file.close()
        if self._finalizer.alive:
            self._finalizer()

    def __str__(self) -> str:
        return f"FileArtifact '{self.name}'"
    
    @staticmethod
    def _cleanup(path: Path, name: str, task_name: str) -> None:
        if not path.exists():
            return
        try:
            path.unlink(missing_ok=True)
        except Exception:
            logger.warning(f"Failed to delete temporary artifact '{name}' of task '{task_name}'")
        else:
            logger.debug(f"Removed temporary artifact '{name}' of task '{task_name}'")

class Task:
    
    def __init__(self) -> None:
        self.state = TaskState.SCHEDULED
        self.uuid = str(uuid.uuid4())
        self.dependencies: list[Task] = []
        self.t_created: datetime = datetime.now()
        self.t_start: datetime|None = None
        self.t_end: datetime|None = None
        self.artifacts: dict[str, Artifact] = {}

    def run(self):
        """ Called when a Task is executed """
        raise NotImplementedError(f"The given task does not implement a run() method")
    
    def clean_up(self) -> None:
        self.artifacts = {}
        # for a in self.artifacts.values():
        #     a.cleanup()
        #     del a

    def store_artifact(self, artifact: Artifact) -> None:
        self.artifacts[artifact.name] = artifact
    
    def runtime(self) -> timedelta|None:
        if self.t_start is None or self.t_end is None:
            return None
        return self.t_end - self.t_start
    
    def __repr__(self) -> str:
        return f"<{str(self)}>"
    
    def __str__(self) -> str:
        return f"Generic Task {self.uuid}"
    
    def __del__(self) -> None:
        self.clean_up()

    
class TaskException(Exception):
    """ Should be raise inside a Task's run() function when an expected error happens """

    def __init__(self, message: str, *args: object) -> None:
        super().__init__(*args)
        self.message = message

class UploadToFTPTask(Task):
    """
    Upload an file to an external FTP server
    """

    def __init__(self, 
                 input: Path|FileArtifact, 
                 file_name: str,
                 address: tuple[str, int], 
                 username: str, password: str, 
                 folder: str, 
                 tls: bool,
                 source_address: tuple[str, int]|None = None) -> None:
        super().__init__()
        self.input = input
        self.file_name = file_name
        self.address = address
        self.username = username
        self.password = password
        self.folder = folder
        self.tls = tls
        self.source_address = source_address


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

            if self.file_name in files:
                raise TaskException(f"File already present on the server")
            
            path = self.input.path if isinstance(self.input, FileArtifact) else self.input
            if not path.exists():
                raise TaskException(f"Missing input file '{self.input}'")
            
            with open(path, "rb") as f:
                ftp.storbinary(f"STOR {self.file_name}", f)

            logger.info(f"Uploaded file '{self.file_name}' to the server")
        except ftplib.all_errors as ex:
            raise TaskException(f"Failed to upload the file: {str(ex)}")
        finally:
            ftp.close()    

    def __str__(self) -> str:
        return f"Upload '{self.file_name}'"

class PDFTask(Task):

    def __init__(self, input: Path|FileArtifact, file_name: str) -> None:
        super().__init__()
        self.input = input
        self.file_name = file_name
        self.reader: pypdf.PdfReader|None = None
        self.num_pages: int|None = None

    def run(self) -> None:
        path = self.input.path if isinstance(self.input, FileArtifact) else self.input
        if not path.exists():
            raise TaskException(f"Missing input file '{self.input}'")
        try:
            self.reader = pypdf.PdfReader(path)
            self.num_pages = self.reader.get_num_pages()
        except pypdf.errors.PyPdfError as ex:
            raise TaskException(f"Failed to decode '{self.file_name}': {str(ex)}")
        
    def __str__(self) -> str:
        return f"Decode PDF '{self.file_name}'"
        

class OCRTask(Task):

    def __init__(self, input: Path|FileArtifact, file_name: str, language: str, optimize: int, deskew: bool, rotate_pages: bool, Tasks: int = 1, tesseract_timeout: int = 60) -> None:
        super().__init__()
        self.input = input
        self.file_name = file_name
        self.language = language
        self.deskew = deskew
        self.optimize = optimize
        self.rotate_pages = rotate_pages
        self.Tasks = Tasks
        self.tesseract_timeout = tesseract_timeout

    def run(self) -> None:
        path = self.input.path if isinstance(self.input, FileArtifact) else self.input
        if not path.exists():
            raise TaskException(f"Missing input file '{self.input}'")
        export_artifact = FileArtifact(self, "export")
        try:
            exit_code = ocrmypdf.ocr(path, export_artifact.path, 
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
        self.store_artifact(export_artifact)
        
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
current_task: Task|None = None

def loop() -> None:
    """ Implements the main thread loop """
    global current_task
    while True:
        current_task = None

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
            current_task = task_priority_queue.get_nowait()
        except Empty:
            current_task = task_queue.get(block=True)

        if current_task.state != TaskState.SCHEDULED:
            task_finished.append(current_task)
            logger.debug(f"Unexpected TaskState {current_task.state} for task '{current_task}' in queue")
            continue

        current_task.state = TaskState.RUNNING

        # Check if all dependencies for the task are resolved
        dependencies_resolved = True
        for d in current_task.dependencies:
            match d.state:
                case TaskState.SCHEDULED | TaskState.WAITING | TaskState.RUNNING:
                    dependencies_resolved = False
                case TaskState.FINISHED:
                    pass
                case _:
                    dependencies_resolved = False
                    current_task.state = TaskState.DEPENDENCY_FAILED
                    break
        if current_task.state != TaskState.RUNNING:
            task_finished.append(current_task)
            logger.debug(f"Task '{str(current_task)}' was marked as DEPENDENCY_FAILED")
            continue
        elif not dependencies_resolved:
            current_task.state = TaskState.WAITING
            task_waiting_list.append(current_task)
            logger.debug(f"Task '{str(current_task)}' was marked as WAITING")
            continue

        logger.debug(f"Executing task '{str(current_task)}'")
        
        try:
            current_task.run()
        except TaskException as ex:
            current_task.state = TaskState.FAILED
            logger.info(f"Task {str(current_task)}: {ex.message}")
        except Exception as ex:
            current_task.state = TaskState.FAILED
            logger.warning(f"Failed to process task '{str(current_task)}': ", exc_info=True)
        else:
            current_task.state = TaskState.FINISHED
            logger.debug(f"Finished task '{str(current_task)}'")

        current_task = None

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
