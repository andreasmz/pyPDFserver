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
from multiprocessing import Process
from pathlib import Path
from queue import Queue, Empty

from .core import *

class TaskState(Enum):
    SCHEDULED = 0
    WAITING = 1
    RUNNING = 2
    FINISHED = 3
    ABORTED = 4
    FAILED = 5
    DEPENDENCY_FAILED = 6
    UNKOWN_ERROR = 7

class Artifact:
    """ 
    Implements an artifact class to pass results between tasks. Any subclass should implement garbage collection in the cleanup() method called when the 
    artifact goes out of scope
    """

    temp_dir = Path(pyPDFserver_temp_dir.name)

    def __init__(self, task: "Task|None", name: str) -> None:
        self.task = task
        self.name = name
        logger.debug(f"Created artifact '{name}'" + (f" for task '{str(task)}'" if task is not None else ""))

    def cleanup(self) -> None:
        """ Clean up the resources of the artifact """
        pass

    def __del__(self) -> None:
        self.cleanup()

    def __str__(self) -> str:
        return f"Artifact '{self.name}'"
    
    def __repr__(self) -> str:
        return f"<{str(self)}>"

class FileArtifact(Artifact):
    """
    Implements a file artifact class to pass files between tasks. Access the data with the given .path attribute.
    Once the object goes out of scope, the cleanup() method is called to remove the temporary file.
    
    """

    def __init__(self, task: "Task|None", name: str) -> None:
        super().__init__(task, name)

        prefix = f"task_{name}"
        if self.task is not None:
            f"task_{self.task.uuid}_{name}"

        self._temp_file = tempfile.NamedTemporaryFile(dir=Artifact.temp_dir / "artifacts", prefix=prefix, delete_on_close=False, delete=True)
        self.path = Path(self._temp_file.name)

        self._finalizer = weakref.finalize(self, FileArtifact._cleanup, self.path, self.name, str(self.task) if self.task is not None else None)

        try:
            logger.debug(f"Created temporary file '{self.path.relative_to(Artifact.temp_dir)}' for artifact '{name}'" + (f" of task '{str(task)}'" if self.task is not None else ""))
        except ValueError:
            logger.error(f"Temporary file '{self.path}' is not in the temporary directory ('{Artifact.temp_dir}')")

    def cleanup(self) -> None:
        if not self._temp_file.closed:
            self._temp_file.close()
        if self._finalizer.alive:
            self._finalizer()

    def __str__(self) -> str:
        return f"FileArtifact '{self.name}'"
    
    @staticmethod
    def _cleanup(path: Path, name: str, task_name: str|None) -> None:
        if not path.exists():
            return
        try:
            path.unlink(missing_ok=True)
        except Exception:
            logger.warning(f"Failed to delete temporary artifact '{name}'" + (f" of task '{task_name}'" if task_name is not None else ""))
        else:
            logger.debug(f"Removed temporary artifact '{name}'" + (f" of task '{task_name}'" if task_name is not None else ""))

class Task:
    """ A task can define any workload scheduled to run asynchronously in the run() method. To pass results to other tasks, use the store_artifacts() method """
    
    def __init__(self) -> None:
        self.state = TaskState.SCHEDULED
        self.uuid = str(uuid.uuid4())
        self.dependencies: list[Task] = []
        self.t_created: datetime = datetime.now()
        self.t_start: datetime|None = None
        self.t_end: datetime|None = None
        self.artifacts: dict[str, Artifact] = {}
        self.error: TaskException|None = None

    def run(self):
        """ Called when a Task is executed """
        raise NotImplementedError(f"The given task does not implement a run() method")
    
    def clean_up(self) -> None:
        """ Clean up the artifacts and release their resources """
        for a in self.artifacts.values():
            a.cleanup()
            del a
        self.artifacts = {}

    def store_artifact(self, artifact: Artifact) -> None:
        """ Store an artifact to be used in other dependend tasks """
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
    """ Should be raise inside a Task's run() function when an expected error happens. The difference to other errors is that it is not logged with stacktrace in the logs """

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
            logger.debug(f"[UploadToFTPTask {self.uuid}] Connected to upload FTP server ('{ftp.getwelcome()}')")
            files = ftp.nlst()

            if self.file_name in files:
                raise TaskException(f"File already present on the server")
            
            path = self.input.path if isinstance(self.input, FileArtifact) else self.input
            if not path.exists():
                raise TaskException(f"Missing input file '{self.input}'")
            
            with open(path, "rb") as f:
                ftp.storbinary(f"STOR {self.file_name}", f)

            logger.info(f"Uploaded file '{self.file_name}' to the remote FTP server")
        except ftplib.all_errors as ex:
            raise TaskException(f"Failed to upload the file: {str(ex)}")
        finally:
            ftp.close()    

    def __str__(self) -> str:
        return f"Upload '{self.file_name}'"

class PDFTask(Task):
    """ Process a given PDF file """

    def __init__(self, input: Path|FileArtifact, file_name: str) -> None:
        super().__init__()
        self.input = input
        self.file_name = file_name
        self.num_pages: int|None = None

    def run(self) -> None:
        path = self.input.path if isinstance(self.input, FileArtifact) else self.input
        if not path.exists():
            raise TaskException(f"Missing input file '{self.input}'")
        
        export_artifact = FileArtifact(self, "export")

        try:
            writer = pypdf.PdfWriter(clone_from=path)

            if writer.is_encrypted:
                raise TaskException(f"Input file '{self.file_name}' is encrypted")

            self.num_pages = writer.get_num_pages()

            writer.add_metadata({"/Producer": "pyPDFserver"})
            writer.write(export_artifact.path)
        except pypdf.errors.PyPdfError as ex:
            raise TaskException(f"Failed to process '{self.file_name}': {str(ex)}")
        self.store_artifact(export_artifact)

    def __str__(self) -> str:
        return f"Decode PDF '{self.file_name}'"
        

class OCRTask(Task):

    def __init__(self, input: Path|FileArtifact, file_name: str, language: str, optimize: int, deskew: bool, rotate_pages: bool, num_jobs: int = 1, tesseract_timeout: int|None = 60) -> None:
        super().__init__()
        self.input = input
        self.file_name = file_name
        self.language = language
        self.deskew = deskew
        self.optimize = optimize
        self.rotate_pages = rotate_pages
        self.num_jobs = num_jobs
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
                                        jobs=self.num_jobs,
                                        optimize=self.optimize,
                                        tesseract_timeout=self.tesseract_timeout
                                        )
        except ocrmypdf.exceptions.ExitCodeException as ex:
            raise TaskException(ex.message)
        if not exit_code == ocrmypdf.ExitCode.ok:
            raise TaskException(exit_code.name)
        logger.debug(f"Applied OCR for '{self.file_name}' (lang={self.language}, deskew={self.deskew}, optimize={self.optimize}, rotate_pages: {self.rotate_pages})")
        
        self.store_artifact(export_artifact)
        
    def __repr__(self) -> str:
        return f"<OCR '{self.file_name}' (lang={self.language}, deskew={self.deskew}, optimize={self.optimize}, rotate_pages: {self.rotate_pages})>"

    def __str__(self) -> str:
        return f"OCR '{self.file_name}'>"
        
class DuplexTask(Task):

    def __init__(self, input1: Path|FileArtifact, input2: Path|FileArtifact, file1_name: str, file2_name: str, export_name: str) -> None:
        super().__init__()
        self.input1 = input1
        self.input2 = input2
        self.file1_name = file1_name
        self.file2_name = file2_name
        self.export_name = export_name

    def run(self):
        path1 = self.input1.path if isinstance(self.input1, FileArtifact) else self.input1
        if not path1.exists():
            raise TaskException(f"Missing input file '{self.input1}'")
        
        path2 = self.input2.path if isinstance(self.input2, FileArtifact) else self.input2
        if not path2.exists():
            raise TaskException(f"Missing input file '{self.input2}'")
        
        export_artifact = FileArtifact(self, "export")

        try:
            reader1 = pypdf.PdfReader(path1)
            reader2 = pypdf.PdfReader(path2)

            if reader1.is_encrypted:
                raise TaskException(f"Input file '{self.file1_name}' is encrypted")
            if reader2.is_encrypted:
                raise TaskException(f"Input file '{self.file2_name}' is encrypted")

            num_pages1 = reader1.get_num_pages()
            num_pages2 = reader2.get_num_pages()

            if num_pages1 != num_pages2:
                raise TaskException(f"Rejected to merge PDFs with unequal page count ({num_pages1} and {num_pages2})")
            
            pdf_merged = pypdf.PdfWriter()

            for p1, p2 in zip(reader1.pages[:], reader2.pages[::-1]):
                pdf_merged.add_page(p1)
                pdf_merged.add_page(p2)
            
            # if reader1.metadata is not None:
            #     pdf_merged.add_metadata(reader1.metadata)
            # if reader2.metadata is not None:
            #     pdf_merged.add_metadata(reader2.metadata)
            pdf_merged.add_metadata({"/Producer": "pyPDFserver"})
            pdf_merged.write(export_artifact.path)
        except pypdf.errors.PyPdfError as ex:
            raise TaskException(f"Failed to merge '{self.file1_name}' with '{self.file2_name}': {str(ex)}")
        self.store_artifact(export_artifact)



task_queue: Queue[Task] = Queue()
task_priority_queue: Queue[Task] = Queue()
task_waiting_list: list[Task] = []
task_finished_list: list[Task] = []
current_task: Task|None = None

def loop() -> None:
    """ Implements the main thread loop """
    global current_task
    while True:
        current_task = None

        # First clean up the queues and lists
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
                task_finished_list.append(t)
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
            try:
                current_task = task_queue.get(block=True, timeout=5*60)
            except Empty:
                continue

        if current_task.state != TaskState.SCHEDULED:
            current_task.state = TaskState.UNKOWN_ERROR
            task_finished_list.append(current_task)
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
            task_finished_list.append(current_task)
            logger.debug(f"Task '{str(current_task)}' was marked as DEPENDENCY_FAILED")
            continue
        elif not dependencies_resolved:
            current_task.state = TaskState.WAITING
            task_waiting_list.append(current_task)
            logger.debug(f"Task '{str(current_task)}' was marked as WAITING")
            continue

        logger.debug(f"Executing task '{str(current_task)}'")
        
        try:
            current_task.t_start = datetime.now()
            current_task.run()
        except TaskException as ex:
            current_task.state = TaskState.FAILED
            current_task.error = ex
            logger.info(f"Task {str(current_task)} failed: {ex.message}")
            continue
        except Exception as ex:
            current_task.state = TaskState.FAILED
            current_task.error = TaskException("Unexpected error")
            logger.warning(f"Failed to process task '{str(current_task)}': ", exc_info=True)
            continue
        finally:
            current_task.t_end = datetime.now()

        current_task.state = TaskState.FINISHED
        task_finished_list.append(current_task)
        logger.debug(f"Finished task '{str(current_task)}'")

def add_tasks(*tasks: Task) -> None:
    for t in tasks:
        task_queue.put(t)
        logger.debug(f"Added task '{str(t)}' to the queue")

def clean_up() -> None:
    """ Clean up the task lists """
    for t in task_finished_list.copy():
        if (datetime.now() - t.t_created).total_seconds() > (60*60):
            task_finished_list.remove(t)
            t.clean_up()
            logger.debug(f"Finished task '{str(t)}' garbage collected")
    for t in task_waiting_list.copy():
        if (datetime.now() - t.t_created).total_seconds() > (60*60):
            task_waiting_list.remove(t)
            t.clean_up()
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
        if current_task is not None:
            current_task.state = TaskState.ABORTED
        run()
    if not process.is_alive():
        return
    threading.Thread(target=_terminate, name="Abort pdf server loop").run()

process = Process(target=loop)
