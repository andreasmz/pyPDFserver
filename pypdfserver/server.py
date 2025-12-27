from .core import *
from .pdf_worker import *

import hashlib
import pyftpdlib.log
import re
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from pyftpdlib.servers import FTPServer
from pyftpdlib.handlers import FTPHandler
try:
    from pyftpdlib.handlers import TLS_FTPHandler
except ImportError:
    logger.error(f"Failed to import the TLS_FTPHandler. Please check if pyOpenSSL has been installed")
    exit()
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.filesystems import AbstractedFS
from threading import Thread
from typing import cast

pyftpdlib.log.config_logging(level=pyftpdlib.log.logging.WARNING)

class FTPAuthorizer(DummyAuthorizer):

    def validate_authentication(self, username: str, password: str, handler):
        logger.debug(f"{password}, {hashlib.sha256(password.encode("utf-8")).hexdigest()}")
        return super().validate_authentication(username, hashlib.sha256(password.encode("utf-8")).hexdigest(), handler)


class PDF_FTPHandler(FTPHandler):

    banner = "pyPDFserver"

    def __init__(self, conn, server: "PDF_FTPServer", ioloop=None):
        super().__init__(conn, server, ioloop)
        self.server = server

    def on_connect(self) -> None:
        temp_dir = Path(pyPDFserver_temp_dir_path / "clients").mkdir(exist_ok=True, parents=False)
        self.temp_dir = tempfile.TemporaryDirectory(temp_dir, prefix="ftp_client")
        if self.fs is not None:
            self.fs.chdir(self.temp_dir)
        logger.debug(f"Client {self.remote_ip}:{self.remote_port} connected to temporary directory {self.temp_dir}")
        super().on_connect()    

    def on_disconnect(self) -> None:
        super().on_disconnect()
        logger.debug(f"Client {self.remote_ip}:{self.remote_port} disconected. Removing temporary directory {self.temp_dir}")
        self.temp_dir.cleanup()

    def on_file_received(self, file: str) -> None:
        super().on_file_received(file)
        profile = self.server.profiles[self.username]
        path = Path(file)
        file_name = path.name
        logger.info(f"Received file '{file_name}' by user '{self.username}'")

        artifact = FileArtifact(None, file_name)
        with open(path, "rb") as f_upload:
            with open(artifact.path, "wb+") as f_artifact:
                f_artifact.write(f_upload.read())

        if (r := profile.duplex1_regex.match(file_name)) is not None:
            logger.info(f"Received duplex front pages '{file_name}'")
            if profile.duplex_pdf_cache is not None:
                logger.info(f"Discarding previous duplex pront pages '{profile.duplex_pdf_cache[2]}'")

            tasks: list[Task] = [Task()]
            tasks[0].artifacts["export"] = artifact
            if profile.ocr_enabled:
                tasks.append(OCRTask(cast(FileArtifact, tasks[-1].artifacts["export"]), 
                                     file_name=file_name, 
                                     language="", 
                                     optimize=profile.ocr_optimize, 
                                     deskew=profile.ocr_deskew, 
                                     rotate_pages=profile.ocr_rotate_pages,
                                     num_jobs=1,
                                     tesseract_timeout=profile.ocr_tesseract_timeout
                                     ))
            tasks.append(PDFTask(cast(FileArtifact, tasks[-1].artifacts["export"]), file_name))
            for t1, t2 in zip(tasks[1:], tasks[2:]):
                t2.dependencies.append(t1)
            add_tasks(*tasks[1:])
            
            export_name = profile.export_duplex_template.replace("(lang)", r.groups("lang")[0])
            export_name = export_name.replace("(*)", r.groups("s")[0])

            profile.duplex_pdf_cache = (tasks[-1], datetime.now(), file_name, export_name)

        elif (r := profile.duplex2_regex.match(file_name)):
            
            if profile.duplex_pdf_cache is None:
                logger.info(f"Received duplex back pages '{file_name}', but discarded them as the pront pages are missing")
                return
            elif (d := (datetime.now() - profile.duplex_pdf_cache[1])).total_seconds() > self.server.duplex_timeout:
                logger.info(f"Received duplex back pages '{file_name}', but discarded them due to timeout (first file received {d.total_seconds()} ago)")
                return
            
            tasks: list[Task] = [Task()]
            tasks[0].artifacts["export"] = artifact
            if profile.ocr_enabled:
                tasks.append(OCRTask(cast(FileArtifact, tasks[-1].artifacts["export"]), 
                                     file_name=file_name, 
                                     language="", 
                                     optimize=profile.ocr_optimize, 
                                     deskew=profile.ocr_deskew, 
                                     rotate_pages=profile.ocr_rotate_pages,
                                     num_jobs=1,
                                     tesseract_timeout=profile.ocr_tesseract_timeout
                                     ))
            tasks.append(PDFTask(cast(FileArtifact, tasks[-1].artifacts["export"]), file_name))
            tasks.append(DuplexTask(
                cast(FileArtifact, profile.duplex_pdf_cache[0].artifacts["export"]),
                cast(FileArtifact, tasks[-1].artifacts["export"]),
                file1_name=profile.duplex_pdf_cache[2],
                file2_name=file_name,
                export_name=profile.duplex_pdf_cache[3]
            ))
            tasks.append(UploadToFTPTask(cast(FileArtifact, tasks[-1].artifacts["export"]), 
                file_name,
                address=(self.server.export_config.host, self.server.export_config.port),
                username=self.server.export_config.username,
                password=self.server.export_config.password,
                folder=self.server.export_config.destination_path,
                tls=True,
            ))
            for t1, t2 in zip(tasks[1:], tasks[2:]):
                t2.dependencies.append(t1)
            add_tasks(*tasks[1:])
            
        else: # Common scan file
            tasks: list[Task] = [Task()]
            tasks[0].artifacts["export"] = artifact
            if profile.ocr_enabled:
                tasks.append(OCRTask(cast(FileArtifact, tasks[-1].artifacts["export"]), 
                                     file_name=file_name, 
                                     language="", 
                                     optimize=profile.ocr_optimize, 
                                     deskew=profile.ocr_deskew, 
                                     rotate_pages=profile.ocr_rotate_pages,
                                     num_jobs=1,
                                     tesseract_timeout=profile.ocr_tesseract_timeout
                                     ))
            tasks.append(PDFTask(cast(FileArtifact, tasks[-1].artifacts["export"]), file_name))
            tasks.append(UploadToFTPTask(cast(FileArtifact, tasks[-1].artifacts["export"]), 
                file_name,
                address=(self.server.export_config.host, self.server.export_config.port),
                username=self.server.export_config.username,
                password=self.server.export_config.password,
                folder=self.server.export_config.destination_path,
                tls=True,
            ))
            for t1, t2 in zip(tasks[1:], tasks[2:]):
                t2.dependencies.append(t1)
            add_tasks(*tasks[1:])

class PDFProfile:

    TEMPLATE_STRINGS: dict[str, str] = {
        "(lang)": r"(?P<lang>[a-zA-Z]+)",
        "(*)": r"(?P<s>.*)",
    }

    def __init__(self, name: str) -> None:
        self.name = name

        username = profiles_config.get(self.name, "username", fallback=None)
        if username is None:
            raise ConfigError(f"Missing field 'username' in profile '{self.name}'")
        self.username = username
        password = profiles_config.get(self.name, "password", fallback=None)
        if password is None:
            raise ConfigError(f"Missing field 'password' in profile '{self.name}'")
        if password.startswith("$SHA256$") and password.endswith("$"):
            self.password = password.strip("$").replace("SHA256$", "")
        else:
            self.password = hashlib.sha256(password.encode("utf-8")).hexdigest()
            profiles_config.set(self.name, "password", f"$SHA256${self.password}$")
            save_config()
            logger.debug(f"Hashed password and saved it back to profiles")

        try:
            self.ocr_enabled = profiles_config.getboolean(self.name, "ocr_enabled")
        except ValueError:
            raise ConfigError(f"Missing field 'ocr_enabled' in profile '{self.name}'")
        
        ocr_language = profiles_config.get(self.name, "ocr_language", fallback=None)
        if ocr_language is None:
            raise ConfigError(f"Missing field 'ocr_language' in profile '{self.name}'")
        self.ocr_language = ocr_language

        try:
            self.ocr_deskew = profiles_config.getboolean(self.name, "ocr_deskew")
        except ValueError:
            raise ConfigError(f"Missing field 'ocr_deskew' in profile '{self.name}'")
        
        try:
            self.ocr_optimize = profiles_config.getint(self.name, "ocr_optimize")
        except ValueError:
            raise ConfigError(f"Missing field 'ocr_optimize' in profile '{self.name}'")
        if self.ocr_optimize < 0:
            raise ConfigError(f"Invalid field 'ocr_optimize' in profile '{self.name}'")
        
        try:
            self.ocr_rotate_pages = profiles_config.getboolean(self.name, "ocr_rotate_pages")
        except ValueError:
            raise ConfigError(f"Missing field 'ocr_rotate_pages' in profile '{self.name}'")
        
        try:
            self.ocr_tesseract_timeout = profiles_config.getint(self.name, "ocr_tesseract_timeout")
        except ValueError:
            raise ConfigError(f"Missing field 'ocr_tesseract_timeout' in profile '{self.name}'")
        
        if self.ocr_tesseract_timeout <= 0:
            self.ocr_tesseract_timeout = None


        duplex1_template = profiles_config.get(self.name, "input_duplex1_name", fallback=None)
        if duplex1_template is None:
            raise ConfigError(f"Missing field 'input_duplex1_name' in section '{self.name}'")
        for k, v in PDFProfile.TEMPLATE_STRINGS.items():
            duplex1_template = duplex1_template.replace(k, v)
        self.duplex1_regex = re.compile(duplex1_template)

        duplex2_template = profiles_config.get(self.name, "input_duplex2_name", fallback=None)
        if duplex2_template is None:
            raise ConfigError(f"Missing field 'input_duplex2_name' in section '{self.name}'")
        for k, v in PDFProfile.TEMPLATE_STRINGS.items():
            duplex2_template = duplex2_template.replace(k, v)
        self.duplex2_regex = re.compile(duplex2_template)

        export_duplex_template = profiles_config.get(self.name, "export_duplex_name", fallback=None)
        if export_duplex_template is None:
            raise ConfigError(f"Missing field 'export_duplex_name' in section '{self.name}'")
        self.export_duplex_template = export_duplex_template
        

        self.duplex_pdf_cache: None|tuple[Task, datetime, str, str] = None # Task, datetime, file_name, export_name


class PDF_FTPServer:

    def __init__(self) -> None:
        try:
            self.duplex_timeout = config.getint("SETTINGS", "duplex_timeout")
        except ValueError:
            raise ConfigError(f"Missing field 'duplex_timeout' in profile 'SETTINGS'")
        if self.duplex_timeout < 0:
            raise ConfigError(f"Invalid field 'duplex_timeout' in profile 'SETTINGS'")


        home_dir = pyPDFserver_temp_dir_path / "ftp_cache"
        home_dir.mkdir(exist_ok=True, parents=False)

        authorizer = FTPAuthorizer()

        self.default_profile = PDFProfile("DEFAULT")
        self.profiles: defaultdict[str, PDFProfile] = defaultdict(lambda: self.default_profile)

        for section in profiles_config.sections() + ["DEFAULT"]:
            p = PDFProfile(section)
            self.profiles[p.name] = p
            authorizer.add_user(
                p.username,
                p.password,
                homedir=home_dir,
                perm="w",
                msg_login="Connected to pyPDFserver"
            )
            logger.debug(f"Created FTP user {p.username} with password *****")

        host = config.get("FTP", "host", fallback="")
        if host == "":
            logger.info(f"No host set. Defaulting to 127.0.0.1")
            host = "127.0.0.1"

        try:
            port = config.getint("FTP", "port", fallback=-1)
        except ValueError:
            port = -1
        if port <= 0 or port >= 2**16:
            logger.info(f"No or invalid port set. Defaulting to 21")
            port = 21

        handler = PDF_FTPHandler
        handler.authorizer = authorizer

        self.server = FTPServer((host, port), handler)

        self.export_config = ExportFTP()

        self.thread = Thread(target=self._loop, name="PDF_FTPServer_main", daemon=True)
        self.thread.start()

    def _loop(self) -> None:
        self.server.serve_forever(handle_exit=True)

    def stop(self) -> None:
        """ Stop the server """
        if self.thread.is_alive():
            self.server.close_all()
            logger.debug(f"Stopped the FTP server")


class ExportFTP:

    def __init__(self) -> None:
        self.host = config.get("EXPORT_FTP_SERVER", "host", fallback="")
        if self.host == "":
            raise ConfigError(f"Missing field 'host' in section 'EXPORT_FTP_SERVER'")

        try:
            self.port = config.getint("EXPORT_FTP_SERVER", "port", fallback=-1)
        except ValueError:
            self.port = -1
        if self.port <= 0 or self.port >= 2**16:
            logger.info(f"No or invalid port for export FTP server set. Defaulting to 21")
            self.port = 21

        username = profiles_config.get("EXPORT_FTP_SERVER", "username", fallback=None)
        if username is None:
            raise ConfigError(f"Missing field 'username' in section 'EXPORT_FTP_SERVER'")
        self.username = username

        password = profiles_config.get("EXPORT_FTP_SERVER", "password", fallback=None)
        if password is None:
            raise ConfigError(f"Missing field 'password' in section 'EXPORT_FTP_SERVER'")
        self.password = password

        destination_path = profiles_config.get("EXPORT_FTP_SERVER", "destination_path", fallback=None)
        if destination_path is None:
            raise ConfigError(f"Missing field 'destination_path' in section 'EXPORT_FTP_SERVER'")
        self.destination_path = destination_path