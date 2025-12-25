import ftplib
import ocrmypdf
import ocrmypdf.exceptions
from enum import Enum
from io import BytesIO
from pathlib import Path
from queue import Queue

from .core import *

class TaskState(Enum):
    UNKOWN = 0
    SCHEDULED = 1
    RUNNING = 2
    FINISHED = 3
    ABORTED = 4
    FAILED = 5

class Job:
    
    def __init__(self) -> None:
        self.state = TaskState.SCHEDULED

    def run(self) -> None:
        """ Called when a job is executed """
        pass

    def __repr__(self) -> str:
        return f"<Generic Job>"
    
    def __str__(self) -> str:
        return self.__repr__()
    
class JobStack(Job):

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[Job] = []

    def run(self) -> None:
        for t in self.stack:
            if t.state != TaskState.SCHEDULED:
                    logger.debug(f"Unexpected TaskState {t.state} for task {t} in job stack {str(self)}")
                    continue
            t.state = TaskState.RUNNING
            try:
                t.run()
            except JobException as ex:
                t.state = TaskState.FAILED
                logger.info(f"{str(t)}: {ex.message}")
            except Exception as ex:
                t.state = TaskState.FAILED
                logger.warning(f"{str(t)}: Failed to process the job", exc_info=True)
            else:
                t.state = TaskState.FINISHED

class JobException(Exception):
    """ Should be raise inside a job's run() function when an expected error happens """

    def __init__(self, message: str, *args: object) -> None:
        super().__init__(*args)
        self.message = message

class UploadJob(Job):

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
        

    def run(self) -> None:
        if not self.file.exists():
            raise JobException(f"File '{self.file}' does not exit")
        if self.tls:
            ftp = ftplib.FTP_TLS()
        else:
            ftp = ftplib.FTP()
        try:
            ftp.connect(self.address[0], self.address[1], source_address=self.source_address)
            if isinstance(ftp, ftplib.FTP_TLS):
                ftp.auth()
                ftp.prot_p()
            ftp.login(user=self.username, passwd=self.password)
            ftp.cwd(self.folder)
            logger.debug(f"Connected to upload FTP server ('{ftp.getwelcome()}')")
            files = ftp.nlst()

            if self.file.name in files:
                raise JobException(f"File already present on the server")
            
            with open(self.file, "rb") as f:
                ftp.storbinary(f"STOR {self.file.name}", f)
            logger.info(f"Uploaded file '{self.file.name}' to the server")
        except ftplib.all_errors as ex:
            raise JobException(f"Failed to upload the file: {str(ex)}")
        finally:
            ftp.close()    

class OCRJob(Job):

    def __init__(self, file: Path, language: str, optimize: int, deskew: bool, rotate_pages: bool, jobs: int = 1, tesseract_timeout: int = 60) -> None:
        super().__init__()
        self.input = file
        self.output = file.parent / f"{file.stem}_OCR{file.suffix}"
        self.language = language
        self.deskew = deskew
        self.optimize = optimize
        self.rotate_pages = rotate_pages
        self.jobs = jobs
        self.tesseract_timeout = tesseract_timeout
        

    def run(self) -> None:
        try:
            exit_code = ocrmypdf.ocr(self.input, self.output, 
                                        language=self.language,
                                        deskew=self.deskew,
                                        rotate_pages=self.rotate_pages,
                                        jobs=self.jobs,
                                        optimize=self.optimize,
                                        tesseract_timeout=self.tesseract_timeout
                                        )
        except ocrmypdf.exceptions.ExitCodeException as ex:
            raise JobException(ex.message)
        if not exit_code == ocrmypdf.ExitCode.ok:
            raise JobException(exit_code.name)
        
    def __repr__(self) -> str:
        return f"<OCRJob for '{self.input.name}' (lang={self.language}, deskew={self.deskew}, optimize={self.optimize}, rotate_pages: {self.rotate_pages})>"

    def __str__(self) -> str:
        return f"Job <OCR for '{self.input.name}'>"
        
class DuplexJob(Job):

    def __init__(self) -> None:
        super().__init__()


task_queue: Queue[Job] = Queue()

def loop() -> None:
    """ Implements the main thread loop """
    while task := task_queue.get(block=True):
        if task.state != TaskState.SCHEDULED:
            logger.debug(f"Unexpected TaskState {task.state} for task {task} in queue")
            continue
        task.state = TaskState.RUNNING
        try:
            task.run()
        except JobException as ex:
            task.state = TaskState.FAILED
            logger.info(f"{str(task)}: {ex.message}")
        except Exception as ex:
            task.state = TaskState.FAILED
            logger.warning(f"{str(task)}: Failed to process the job", exc_info=True)
        else:
            task.state = TaskState.FINISHED