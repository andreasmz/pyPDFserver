import ftplib
import logging
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
from pathlib import Path
from queue import Queue, Empty
from typing import cast

from .core import *

ocrmypdf_logger = logging.getLogger("ocrmypdf")
ocrmypdf_logger.handlers.clear()
ocrmypdf_logger.addHandler(stream_log_handler)
ocrmypdf_logger.addHandler(file_log_handler)

class TaskState(Enum):
    """ 
    Defines the status of a task. 
    Values 0-9 indicate a state before finishing, 10-19 indicate sucessfull finish and >20 indicate errors
    """
    CREATED = (0, 80)
    SCHEDULED = (1, 83)
    WAITING = (2, 82)
    RUNNING = (3, 84)
    FINISHED = (10, 81)
    FAILED = (20, 92)
    ABORTED = (21, 91)
    DEPENDENCY_FAILED = (22, 90)
    UNKOWN_ERROR = (0, 93)

    def __init__(self, value: int, priority: int):
        self._value_ = value      # behält den ursprünglichen Enum-Wert
        self.priority = priority # zusätzliches Attribut

    @classmethod
    def merge_states(cls, *states: "TaskState") -> "TaskState":
        if len(states) == 0:
            raise ValueError(f"Can't merge zeros TaskStates")
        return max(states, key=lambda s: s.priority)

class Artifact:
    """ 
    Implements an artifact class to pass results between tasks. Any subclass should implement garbage collection in the cleanup() method called when the 
    artifact goes out of scope
    """

    temp_dir = pyPDFserver_temp_dir_path / "artifacts"

    def __init__(self, task: "Task|None", name: str, _log: bool = True) -> None:
        self.task = task
        self._name = name
        if _log:
            logger.debug(f"Created artifact '{name}'" + (f" for task '{str(task)}'" if task is not None else ""))

    @property
    def name(self) -> str:
        return self._name
    
    @name.setter
    def name(self, val: str) -> None:
        logger.debug(f"Renamed artifact '{self._name}' to '{val}'")
        self._name = val

    def cleanup(self) -> None:
        """ Clean up the resources of the artifact """
        pass

    def __del__(self) -> None:
        self.cleanup()

    def __str__(self) -> str:
        return f"Artifact '{self.name}'"
    
    def __repr__(self) -> str:
        return f"<{str(self)}>"

Artifact.temp_dir.mkdir(exist_ok=True, parents=False)

class FileArtifact(Artifact):
    """
    Implements a file artifact class to pass files between tasks. Access the data with the given .path attribute.
    Once the object goes out of scope, the cleanup() method is called to remove the temporary file.
    
    """

    def __init__(self, task: "Task|None", name: str) -> None:
        super().__init__(task, name, _log=False)

        prefix = f"artifact_{name}"
        if self.task is not None:
            prefix = f"{type(task).__name__}_{name}."

        self._temp_file = tempfile.NamedTemporaryFile(dir=Artifact.temp_dir, prefix=prefix, suffix=".bin", delete=False)
        self._temp_file.close()
        self.path = Path(self._temp_file.name)

        self._finalizer = weakref.finalize(self, FileArtifact._cleanup, self.path, self.name, str(self.task) if self.task is not None else None)

        try:
            logger.debug(f"Created FileArtifact '{self.name}' at '{self.path.relative_to(Artifact.temp_dir)}'" + (f" of task '{str(task)}'" if self.task is not None else ""))
        except ValueError:
            logger.error(f"Failed to create FileArtifact '{self.name}': '{self.path}' is not in the temporary directory ('{Artifact.temp_dir}')")

    def cleanup(self) -> None:
        logger.debug(f"Cleanup for temporary artifact '{self.name}'"+ (f" of task '{str(self.task)}'" if self.task is not None else ""))
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
            logger.debug(f"Garbage collected temporary artifact '{name}'" + (f" of task '{task_name}'" if task_name is not None else ""))


class ArtifactLink:

    def __init__(self, artifact_name: str, task: "Task") -> None:
        self.artifact_name = artifact_name
        self.task = task
    
    def get(self) -> "Artifact":
        return self.task.artifacts[self.artifact_name]
    
    def __str__(self) -> str:
        return f"Link to '{str(self.get())}'"
    
    def __repr__(self) -> str:
        return f"<{str(self)}>"

class FileArtifactLink(ArtifactLink):

    def get(self) -> FileArtifact:
        return cast(FileArtifact, super().get())

class Task:
    """ A task can define any workload scheduled to run asynchronously in the run() method. To pass results to other tasks, use the store_artifacts() method """
    
    task_list: list["Task"] = []
    groups: dict[str, str] = {}

    def __init__(self, group: str|None = None, group_name: str|None = None, hidden: bool = False) -> None:
        self.state = TaskState.CREATED
        self.uuid = str(uuid.uuid4())
        self.dependencies: list[Task] = []
        self.external_dependencies: set[str] = set()
        self.t_created: datetime = datetime.now()
        self.t_start: datetime|None = None
        self.t_end: datetime|None = None
        self.artifacts: dict[str, Artifact] = {}
        self.error: TaskException|None = None
        self.group = group
        self.hidden = hidden

        Task.task_list.append(self)

    def set_group_name(self, name: str) -> None:
        if self.group is not None:
            Task.groups[self.group] = name

    def run(self) -> None:
        """ Called when a Task is executed """
        raise NotImplementedError(f"The given task does not implement a run() method")
    
    def try_abort(self) -> None:
        if self.state in [TaskState.CREATED, TaskState.SCHEDULED, TaskState.WAITING]:
            self.state = TaskState.ABORTED
            logger.info(f"Aborted task '{str(self)}'")
        elif self.state == TaskState.RUNNING:
            logger.debug(f"Task '{str(self)}' is running and can not be aborted")
        else:
            logger.debug(f"Task '{str(self)}' has finished and can not be aborted")
    
    def add_external_dependency(self, name: str) -> None:
        """ Call this function """
        if self.state in [TaskState.CREATED, TaskState.SCHEDULED, TaskState.WAITING]:
            self.external_dependencies.add(name)
        elif self.state == TaskState.RUNNING:
            logger.debug(f"Can not add external dependency '{name}' to task '{str(self)}' as the task is already running")
        else:
            logger.debug(f"Can not add external dependency '{name}' to task '{str(self)}' as the task has already finished")

    def release_external_dependency(self, name: str) -> None:
        if name not in self.external_dependencies:
            logger.debug(f"'{str(self)}': Trying to release a not existing external dependency")
            return
        self.external_dependencies.remove(name)

    def clean_up(self) -> None:
        """ Clean up the artifacts and release their resources """
        logger.debug(f"Cleaning up task '{str(self)}'")
        for a in self.artifacts.values():
            a.cleanup()
            del a
        self.artifacts = {}

    def schedule(self) -> None:
        self.state = TaskState.SCHEDULED
        task_queue.put(self)

    def register_artifact(self, artifact: Artifact) -> Artifact:
        """ Store an artifact to be used in other dependend tasks """
        self.artifacts[artifact.name] = artifact
        return artifact
    
    @property
    def runtime(self) -> timedelta|None:
        if self.t_start is None or self.t_end is None:
            return None
        return self.t_end - self.t_start
    
    @property
    def name(self) -> str:
        return "Generic Task"
    
    @property
    def desc(self) -> str:
        return ""
    
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

class WaitForFileTask(Task):
    """
    Wait for a file before proceding
    """

    def __init__(self, 
                 display_name: str,
                 display_desc: str,
                 group: str | None = None, 
                 group_name: str | None = None, 
                 hidden: bool = False) -> None:
        super().__init__(group, group_name, hidden)
        self.display_name = display_name
        self.display_desc = display_desc

        self.register_artifact(FileArtifact(self, "file"))
        self.file_artifact_link = FileArtifactLink("file", self)
        logger.debug(f"Created WaitForFileTask '{str(self)}'")

    @property
    def file_artifact(self) -> FileArtifact:
        return cast(FileArtifact, self.artifacts["file"])
    
    @file_artifact.setter
    def file_artifact(self, val: FileArtifact) -> None:
        self.artifacts["file"] = val
    
    def run(self):
        pass

    def __str__(self) -> str:
        return f"WaitForFileTask '{self.name}'"
    
    @property
    def name(self) -> str:
        return self.display_name
    
    @property
    def desc(self) -> str:
        return self.display_desc

class UploadToFTPTask(Task):
    """
    Upload an file to an external FTP server
    """

    def __init__(self, 
                 input: Path|FileArtifactLink, 
                 file_name: str,
                 address: tuple[str, int], 
                 username: str, password: str, 
                 folder: str, 
                 tls: bool,
                 source_address: tuple[str, int]|None = None,
                 group: str|None = None, 
                 hidden: bool = False) -> None:
        super().__init__(group=group, hidden=hidden)
        self.input = input
        self.file_name = file_name
        self.address = address
        self.username = username
        self.password = password
        self.folder = folder
        self.tls = tls
        self.source_address = source_address

        logger.debug(f"Created UploadToFTPTask '{str(self)}'")

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
            
            path = self.input.get().path if isinstance(self.input, FileArtifactLink) else self.input
            if not path.exists():
                raise TaskException(f"Missing input file '{self.input}'")
            
            with open(path, "rb") as f:
                ftp.storbinary(f"STOR {self.file_name}", f)

            logger.info(f"Uploaded file '{self.file_name}' to the remote FTP server")
        except ftplib.all_errors as ex:
            raise TaskException(f"Failed to upload the file: {str(ex)}")
        finally:
            ftp.close()    

    @property
    def name(self) -> str:
        return "Upload to FTP"
    
    @property
    def desc(self) -> str:
        return f"{self.address[0]}:{self.address[1]}@{self.username}:{self.folder}"


    def __str__(self) -> str:
        return f"Upload '{self.file_name}'"

class PDFTask(Task):
    """ Process a given PDF file """

    def __init__(self, input: Path|FileArtifactLink, file_name: str, group: str|None = None, hidden: bool = False) -> None:
        super().__init__(group=group, hidden=hidden)
        self.input = input
        self.file_name = file_name
        self.num_pages: int|None = None

        self.register_artifact(FileArtifact(self, "export"))
        self.export_artifact_link = FileArtifactLink("export", self)

        logger.debug(f"Created PDFTask '{str(self)}'")

    @property
    def export_artifact(self) -> FileArtifact:
        return cast(FileArtifact, self.artifacts["export"])


    def run(self) -> None:
        path = self.input.get().path if isinstance(self.input, FileArtifactLink) else self.input
        if not path.exists():
            raise TaskException(f"Missing input file '{self.input}'")

        try:
            writer = pypdf.PdfWriter(clone_from=path)

            if writer.is_encrypted:
                raise TaskException(f"Input file '{self.file_name}' is encrypted")

            self.num_pages = writer.get_num_pages()

            writer.add_metadata({"/Producer": "pyPDFserver"})
            writer.write(self.export_artifact.path)
        except pypdf.errors.PyPdfError as ex:
            raise TaskException(f"Failed to process '{self.file_name}': {str(ex)}")

    def __str__(self) -> str:
        return f"Decode PDF '{self.file_name}'"

    @property
    def name(self) -> str:
        return "Decode PDF"
    
    @property
    def desc(self) -> str:
        return ""
        

class OCRTask(Task):

    def __init__(self, input: Path|FileArtifactLink, 
                 file_name: str, 
                 language: str, 
                 optimize: int, 
                 deskew: bool, 
                 rotate_pages: bool, 
                 num_jobs: int = 1, 
                 tesseract_timeout: int|None = 60,
                 group: str|None = None, 
                 hidden: bool = False) -> None:
        super().__init__(group=group, hidden=hidden)
        self.input = input
        self.file_name = file_name
        self.language = language
        self.deskew = deskew
        self.optimize = optimize
        self.rotate_pages = rotate_pages
        self.num_jobs = num_jobs
        self.tesseract_timeout = tesseract_timeout

        self.register_artifact(FileArtifact(self, "export"))
        self.export_artifact_link = FileArtifactLink("export", self)
        logger.debug(f"Created OCRTask '{str(self)}'")

    @property
    def export_artifact(self) -> FileArtifact:
        return cast(FileArtifact, self.artifacts["export"])

    def run(self) -> None:
        path = self.input.get().path if isinstance(self.input, FileArtifactLink) else self.input
        if not path.exists():
            raise TaskException(f"Missing input file '{self.input}'")

        try:
            exit_code = ocrmypdf.ocr(path, self.export_artifact.path, 
                                        language=self.language,
                                        deskew=self.deskew,
                                        rotate_pages=self.rotate_pages,
                                        jobs=self.num_jobs,
                                        optimize=self.optimize,
                                        tesseract_timeout=self.tesseract_timeout,
                                        skip_text=True,
                                        progress_bar=False,
                                        )
        except ocrmypdf.exceptions.ExitCodeException as ex:
            raise TaskException(str(ex))
        if not exit_code == ocrmypdf.ExitCode.ok:
            raise TaskException(exit_code.name)
        logger.debug(f"Applied OCR for '{self.file_name}' (lang={self.language}, deskew={self.deskew}, optimize={self.optimize}, rotate_pages: {self.rotate_pages})")
        
    @property
    def name(self) -> str:
        return "OCR"
    
    @property
    def desc(self) -> str:
        return self.param_str
    
    @property
    def param_str(self) -> str:
        return f"lang={self.language}, deskew={self.deskew}, optimize={self.optimize}, rotate_pages: {self.rotate_pages}"

    def __repr__(self) -> str:
        return f"<OCR '{self.file_name}' ({self.param_str})>"

    def __str__(self) -> str:
        return f"OCR '{self.file_name}'"
    
        
class DuplexTask(Task):

    def __init__(self, 
                 input1: Path|FileArtifactLink, 
                 input2: Path|FileArtifactLink, 
                 file1_name: str, 
                 file2_name: str, 
                 export_name: str,
                 group: str|None = None, 
                 hidden: bool = False) -> None:
        super().__init__(group=group, hidden=hidden)
        self.input1 = input1
        self.input2 = input2
        self.file1_name = file1_name
        self.file2_name = file2_name
        self.export_name = export_name

        self.register_artifact(FileArtifact(self, "export"))
        self.export_artifact_link = FileArtifactLink("export", self)

        logger.debug(f"Created DuplexTask '{str(self)}'")

    @property
    def export_artifact(self) -> FileArtifact:
        return cast(FileArtifact, self.artifacts["export"])

    def run(self):
        path1 = self.input1.get().path if isinstance(self.input1, FileArtifactLink) else self.input1
        if not path1.exists():
            raise TaskException(f"Missing input file '{self.input1}'")
        
        path2 = self.input2.get().path if isinstance(self.input2, FileArtifactLink) else self.input2
        if not path2.exists():
            raise TaskException(f"Missing input file '{self.input2}'")

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

            pdf_merged.add_metadata({"/Producer": "pyPDFserver"})
            pdf_merged.write(self.export_artifact.path)
        except pypdf.errors.PyPdfError as ex:
            raise TaskException(f"Failed to merge '{self.file1_name}' with '{self.file2_name}': {str(ex)}")
        
            
    @property
    def name(self) -> str:
        return "Merge to duplex"
    
    @property
    def desc(self) -> str:
        return ""
        
    def __str__(self) -> str:
        return f"Create duplex pdf '{self.export_name}'"


task_queue: Queue[Task] = Queue()
task_priority_queue: Queue[Task] = Queue()
current_task: Task|None = None

def _pdfworker_handler() -> None:
    try:
        _pdfworker_loop()
    except Exception as ex:
        logger.error(f"The pdf worker loop crashed", exc_info=True)
        logger.critical(f"Terminating pyPDFserver")
        exit()

def clean() -> None:
    for t in Task.task_list.copy():
        # First remove old tasks
        if (datetime.now() - t.t_created).total_seconds() > (60*60):
            Task.task_list.remove(t)
            t.clean_up()
            match t.state:
                case TaskState.RUNNING:
                    logger.info(f"Running task '{str(t)}' marked for time out")
                case TaskState.CREATED | TaskState.SCHEDULED | TaskState.WAITING:
                    logger.info(f"Task '{str(t)}' timed out")
                case _:
                    logger.debug(f"Garbage collected task '{str(t)}'")
            continue

        # Now check if waiting task is ready (put to priority queue) or has failed dependencies
        if t.state != TaskState.WAITING:
            continue

        task_ready = True
        if len(t.external_dependencies) > 0:
            task_ready = False
        for d in t.dependencies:
            match d.state:
                case TaskState.CREATED | TaskState.SCHEDULED | TaskState.WAITING | TaskState.RUNNING:
                    task_ready = False
                case TaskState.FINISHED:
                    pass
                case _:
                    task_ready = False
                    t.state = TaskState.DEPENDENCY_FAILED
                    break
        if t.state != TaskState.WAITING:
            logger.debug(f"Task '{str(t)}' was marked as DEPENDENCY_FAILED")
        elif task_ready:
            t.state = TaskState.SCHEDULED
            task_priority_queue.put(t)
            logger.debug(f"Task '{str(t)}' was moved from WAITING to SCHEDULED")

def _pdfworker_loop() -> None:
    """ Implements the main thread loop """
    global current_task
    logger.debug(f"Started the pdf server")
    while True:
        current_task = None

        clean()

        # Get next task
        try:
            current_task = task_priority_queue.get_nowait()
        except Empty:
            try:
                current_task = task_queue.get(block=True, timeout=5*60)
            except Empty:
                continue

        if current_task not in Task.task_list:
            logger.debug(f"Skipped task '{str(current_task)}' as it timed out")
            continue
        elif current_task.state == TaskState.ABORTED:
            continue
        elif current_task.state != TaskState.SCHEDULED:
            current_task.state = TaskState.UNKOWN_ERROR
            logger.debug(f"Unexpected TaskState {current_task.state} for task '{current_task}' in queue. Skipping it")
            continue

        current_task.state = TaskState.RUNNING

        # Check if all dependencies for the task are resolved
        dependencies_resolved = True
        if len(current_task.external_dependencies) > 0:
            dependencies_resolved = False
        for d in current_task.dependencies:
            match d.state:
                case TaskState.FINISHED:
                    pass
                case TaskState.CREATED | TaskState.SCHEDULED | TaskState.WAITING | TaskState.RUNNING:
                    dependencies_resolved = False
                case _:
                    dependencies_resolved = False
                    current_task.state = TaskState.DEPENDENCY_FAILED
                    break
        if current_task.state != TaskState.RUNNING:
            logger.debug(f"Task '{str(current_task)}' was marked as DEPENDENCY_FAILED")
            continue
        elif not dependencies_resolved:
            current_task.state = TaskState.WAITING
            logger.debug(f"Task '{str(current_task)}' was marked as WAITING")
            continue

        logger.debug(f"Executing task '{str(current_task)}'")
        
        try:
            current_task.t_start = datetime.now()
            current_task.run()
        except TaskException as ex:
            current_task.state = TaskState.FAILED
            current_task.error = ex
            logger.info(f"Task '{str(current_task)}' failed: {ex.message}")
            continue
        except Exception as ex:
            current_task.state = TaskState.FAILED
            current_task.error = TaskException("Unexpected error")
            logger.warning(f"Failed to process task '{str(current_task)}': ", exc_info=True)
            continue
        finally:
            current_task.t_end = datetime.now()

        current_task.state = TaskState.FINISHED
        logger.debug(f"Finished task '{str(current_task)}'")

def run() -> None:
    """ Start the server loop """
    global worker_thread, current_task

    if current_task is not None and current_task.state.value < 10:
        current_task.state = TaskState.ABORTED

    worker_thread = threading.Thread(target=_pdfworker_handler, name="PDFworker loop", daemon=True)
    worker_thread.start()

run()