from .core import *
from .log import _file_handler
from .pdf_worker import Task, PDFTask, OCRTask, DuplexTask, UploadToFTPTask, Artifact, FileArtifact
from . import pdf_worker

import hashlib
import pyftpdlib.log
import re
import tempfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer
from threading import Thread
from typing import cast

pyftpdlib.log.config_logging(pyftpdlib.log.logging.WARNING)
pyftpdlib.log.logger.addHandler(_file_handler)
pyftpdlib.log

class PDFAuthorizer(DummyAuthorizer):
    """ Extend the Dummy Authorizer class with hashed password storage """

    def validate_authentication(self, username: str, password: str, handler):
        return super().validate_authentication(username, hashlib.sha256(password.encode("utf-8")).hexdigest(), handler)


class PDF_FTPHandler(FTPHandler):

    banner = "pyPDFserver"
    server: "PDF_FTPServer"

    def __init__(self, conn, server, ioloop=None):
        super().__init__(conn, server, ioloop)

    def on_connect(self) -> None:
        super().on_connect()    
        self.temp_dir = tempfile.TemporaryDirectory(dir=str(PDF_FTPHandler.server.home_dir), prefix="ftp_client_", ignore_cleanup_errors=True)
        self.temp_path = Path(self.temp_dir.name)
        logger.debug(f"Client {self.remote_ip}:{self.remote_port} connected (temporary directory {self.temp_path.name})")
        
    def on_login(self, username) -> None:
        super().on_login(username)
        if self.fs is not None:
            self.fs.root = (str(self.temp_path))

    def on_disconnect(self) -> None:
        super().on_disconnect()
        logger.debug(f"Client {self.remote_ip}:{self.remote_port} disconected. Removing temporary directory {self.temp_path.name}")
        self.temp_dir.cleanup()

    def on_file_received(self, file: str) -> None:
        super().on_file_received(file)
        profile = PDF_FTPHandler.server.profiles[self.username]
        path = Path(file)
        file_name = path.name

        if not profile.input_case_sensitive:
            file_name = file_name.lower()

        logger.debug(f"Received file '{file_name}' on profile '{profile.name}'")

        artifact = FileArtifact(None, file_name)
        with open(path, "rb") as f_upload:
            with open(artifact.path, "wb+") as f_artifact:
                f_artifact.write(f_upload.read())
        path.unlink()

        if not path.suffix.lower() == ".pdf":
            logger.info(f"Discarded file '{file_name}' because it is no PDF file")
            return

        if (r := profile.duplex1_regex.match(file_name)) is not None:
            logger.info(f"Received duplex front pages '{file_name}' by user '{self.username}'")
            if profile.duplex_pdf_cache is not None:
                logger.info(f"Discarding previous duplex pront pages '{profile.duplex_pdf_cache[2]}'")

            tasks: list[Task] = [Task()]
            tasks[0].artifacts["export"] = artifact
            if profile.ocr_enabled:
                tasks.append(OCRTask(cast(FileArtifact, tasks[-1].artifacts["export"]), 
                                     file_name=file_name, 
                                     language=profile.ocr_language, 
                                     optimize=profile.ocr_optimize, 
                                     deskew=profile.ocr_deskew, 
                                     rotate_pages=profile.ocr_rotate_pages,
                                     num_jobs=1,
                                     tesseract_timeout=profile.ocr_tesseract_timeout
                                     ))
            for t in tasks[1:]:
                t.schedule()

            profile.duplex_pdf_cache = (tasks[-1], datetime.now(), file_name, r.group("s"))

        elif (r := profile.duplex2_regex.match(file_name)):
            
            if profile.duplex_pdf_cache is None:
                logger.info(f"Received duplex back pages '{file_name}', but discarded them as the pront pages are missing")
                return
            elif (d := (datetime.now() - profile.duplex_pdf_cache[1])).total_seconds() > PDF_FTPHandler.server.duplex_timeout:
                logger.info(f"Received duplex back pages '{file_name}', but discarded them due to timeout (first file received {d.total_seconds()} ago)")
                profile.duplex_pdf_cache = None
                return
            
            logger.info(f"Received duplex back pages '{file_name}' by user '{self.username}'")


            export_name = profile.export_duplex_template
            export_name = export_name.replace("(lang)", profile.ocr_language)
            export_name = export_name.replace("(*)", profile.duplex_pdf_cache[3])
            export_name = export_name.replace("(*1)", profile.duplex_pdf_cache[3])
            if "s" in r.groups():
                export_name = export_name.replace("(*2)", r.group("s"))
            
            tasks: list[Task] = [Task()]
            tasks[0].artifacts["export"] = artifact
            if profile.ocr_enabled:
                tasks.append(OCRTask(cast(FileArtifact, tasks[-1].artifacts["export"]), 
                                     file_name=file_name, 
                                     language=profile.ocr_language, 
                                     optimize=profile.ocr_optimize, 
                                     deskew=profile.ocr_deskew, 
                                     rotate_pages=profile.ocr_rotate_pages,
                                     num_jobs=1,
                                     tesseract_timeout=profile.ocr_tesseract_timeout
                                     ))
            tasks.append(DuplexTask(
                cast(FileArtifact, profile.duplex_pdf_cache[0].artifacts["export"]),
                cast(FileArtifact, tasks[-1].artifacts["export"]),
                file1_name=profile.duplex_pdf_cache[2],
                file2_name=file_name,
                export_name=export_name
            ))
            if type(profile.duplex_pdf_cache[0]) != Task: # Add file 1 dependency only if not dummy artifact Task
                tasks[-1].dependencies.append(profile.duplex_pdf_cache[0])
            tasks.append(UploadToFTPTask(cast(FileArtifact, tasks[-1].artifacts["export"]), 
                file_name=export_name,
                address=(PDF_FTPHandler.server.export_config.host, PDF_FTPHandler.server.export_config.port),
                username=PDF_FTPHandler.server.export_config.username,
                password=PDF_FTPHandler.server.export_config.password,
                folder=profile.export_path,
                tls=True,
                source_address=((PDF_FTPHandler.server.local_ip, PDF_FTPHandler.server.export_config.control_port) if PDF_FTPHandler.server.export_config.control_port is not None else None)
            ))
            for t1, t2 in zip(tasks[1:], tasks[2:]):
                t2.dependencies.append(t1)
            for t in tasks[1:]:
                t.schedule()

            profile.duplex_pdf_cache = None
            
        elif (r := profile.input_pdf_regex.match(file_name)):
            logger.info(f"Received file '{file_name}' by user '{self.username}'")

            export_name = profile.export_pdf_template
            export_name = export_name.replace("(lang)", profile.ocr_language)
            if "s" in r.groups():
                export_name = export_name.replace("(*2)", r.group("s"))

            tasks: list[Task] = [Task()]
            tasks[0].artifacts["export"] = artifact
            if profile.ocr_enabled:
                tasks.append(OCRTask(cast(FileArtifact, tasks[-1].artifacts["export"]), 
                                     file_name=file_name, 
                                     language=profile.ocr_language, 
                                     optimize=profile.ocr_optimize, 
                                     deskew=profile.ocr_deskew, 
                                     rotate_pages=profile.ocr_rotate_pages,
                                     num_jobs=1,
                                     tesseract_timeout=profile.ocr_tesseract_timeout
                                     ))
            tasks.append(PDFTask(cast(FileArtifact, tasks[-1].artifacts["export"]), file_name))
            tasks.append(UploadToFTPTask(cast(FileArtifact, tasks[-1].artifacts["export"]), 
                file_name,
                address=(PDF_FTPHandler.server.export_config.host, PDF_FTPHandler.server.export_config.port),
                username=PDF_FTPHandler.server.export_config.username,
                password=PDF_FTPHandler.server.export_config.password,
                folder=profile.export_path,
                tls=True,
                source_address=((PDF_FTPHandler.server.local_ip, PDF_FTPHandler.server.export_config.control_port) if PDF_FTPHandler.server.export_config.control_port is not None else None)
            ))
            for t1, t2 in zip(tasks[1:], tasks[2:]):
                t2.dependencies.append(t1)
            for t in tasks[1:]:
                t.schedule()
        else:
            logger.info(f"Discarded file '{file_name}' not matching any rules")

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

        try:
            self.input_case_sensitive = profiles_config.getboolean(self.name, "input_case_sensitive")
        except ValueError:
            raise ConfigError(f"Missing field 'input_case_sensitive' in profile '{self.name}'")

        input_pdf_name = profiles_config.get(self.name, "input_pdf_name", fallback=None)
        if input_pdf_name is None:
            raise ConfigError(f"Missing field 'input_pdf_name' in profile '{self.name}'")
        if not self.input_case_sensitive:
            input_pdf_name = input_pdf_name.lower()
        for k, v in PDFProfile.TEMPLATE_STRINGS.items():
            input_pdf_name = input_pdf_name.replace(k, v)
        self.input_pdf_regex = re.compile(input_pdf_name)

        input_duplex1_name = profiles_config.get(self.name, "input_duplex1_name", fallback=None)
        if input_duplex1_name is None:
            raise ConfigError(f"Missing field 'input_duplex1_name' in profile '{self.name}'")
        for k, v in PDFProfile.TEMPLATE_STRINGS.items():
            input_duplex1_name = input_duplex1_name.replace(k, v)
        if not self.input_case_sensitive:
            input_duplex1_name = input_duplex1_name.lower()
        self.duplex1_regex = re.compile(input_duplex1_name)

        input_duplex2_name = profiles_config.get(self.name, "input_duplex2_name", fallback=None)
        if input_duplex2_name is None:
            raise ConfigError(f"Missing field 'input_duplex2_name' in profile '{self.name}'")
        for k, v in PDFProfile.TEMPLATE_STRINGS.items():
            input_duplex2_name = input_duplex2_name.replace(k, v)
        if not self.input_case_sensitive:
            input_duplex2_name = input_duplex2_name.lower()
        self.duplex2_regex = re.compile(input_duplex2_name)

        export_pdf_template = profiles_config.get(self.name, "export_pdf_name", fallback=None)
        if export_pdf_template is None:
            raise ConfigError(f"Missing field 'export_pdf_name' in profile '{self.name}'")
        self.export_pdf_template = export_pdf_template

        export_duplex_template = profiles_config.get(self.name, "export_duplex_name", fallback=None)
        if export_duplex_template is None:
            raise ConfigError(f"Missing field 'export_duplex_name' in profile '{self.name}'")
        self.export_duplex_template = export_duplex_template

        export_path = profiles_config.get(self.name, "export_path", fallback=None)
        if export_path is None:
            raise ConfigError(f"Missing field 'export_path' in profile '{self.name}'")
        self.export_path = export_path
        
        self.duplex_pdf_cache: None|tuple[Task, datetime, str, str] = None # Task, datetime, file_name, export_name


class PDF_FTPServer:

    def __init__(self) -> None:
        try:
            self.duplex_timeout = config.getint("SETTINGS", "duplex_timeout")
        except ValueError:
            raise ConfigError(f"Missing field 'duplex_timeout' in profile 'SETTINGS'")
        if self.duplex_timeout < 0:
            raise ConfigError(f"Invalid field 'duplex_timeout' in profile 'SETTINGS'")


        self.home_dir = pyPDFserver_temp_dir_path / "ftp_cache"
        self.home_dir.mkdir(exist_ok=True, parents=False)

        authorizer = PDFAuthorizer()

        self.default_profile = PDFProfile("DEFAULT")
        self.profiles: defaultdict[str, PDFProfile] = defaultdict(lambda: self.default_profile)

        for section in profiles_config.sections() + ["DEFAULT"]:
            p = PDFProfile(section)
            self.profiles[p.username] = p
            authorizer.add_user(
                p.username,
                p.password,
                homedir=self.home_dir,
                perm="w",
                msg_login="Connected to pyPDFserver"
            )
            logger.debug(f"Created FTP user {p.username} with password *****")

        

        self.local_ip = config.get("FTP", "local_ip", fallback="")
        if self.local_ip == "":
            logger.info(f"No local_ip set. Defaulting to 127.0.0.1")
            self.local_ip = "127.0.0.1"

        self.host = config.get("FTP", "host", fallback="")
        if self.host == "":
            logger.info(f"No host set. Defaulting to the local_ip value '{self.local_ip}'")
            self.host = self.local_ip

        try:
            self.port = config.getint("FTP", "port", fallback=-1)
        except ValueError:
            self.port = -1
        if self.port <= 0 or self.port >= 2**16:
            logger.info(f"No or invalid port set. Defaulting to 21")
            self.port = 21

        passive_ports = config.get("FTP", "passive_ports", fallback="")
        self.passive_ports: list[int]|None = None
        if passive_ports.strip() != "":
            self.passive_ports = []
            try:
                for x in passive_ports.split(","):
                    if len(x.split("-")) == 2:
                        a, b = x.split("-")
                        a, b = int(a.strip()), int(b.strip())
                        self.passive_ports.extend(range(a, b))
                    else:
                        self.passive_ports.append(int(x.strip()))
            except ValueError:
                raise ConfigError(f"Invalid list of ports in field 'passive_ports' of section 'FTP'")

        handler = PDF_FTPHandler
        handler.authorizer = authorizer
        handler.server = self
        handler.passive_ports = self.passive_ports # type: ignore
        if self.local_ip != self.host:
            handler.masquerade_address = self.host # type: ignore

        self.server = FTPServer((self.local_ip, self.port), handler)

        self.export_config = ExportFTP()

        self.thread = Thread(target=self._loop, name="PDF_FTPServer_main", daemon=True)
        self.thread.start()

        logger.info(f"pyPDFserver started on {self.host}:{self.port} (listening on {self.local_ip}) with {len(self.profiles)} profiles loaded")

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

        try:
            self.control_port = config.getint("EXPORT_FTP_SERVER", "control_port", fallback=-1)
        except ValueError:
            self.control_port = -1
        if self.control_port <= 0 or self.control_port >= 2**16:
            self.control_port = None

        username = config.get("EXPORT_FTP_SERVER", "username", fallback=None)
        if username is None:
            raise ConfigError(f"Missing field 'username' in section 'EXPORT_FTP_SERVER'")
        self.username = username

        password = config.get("EXPORT_FTP_SERVER", "password", fallback=None)
        if password is None:
            raise ConfigError(f"Missing field 'password' in section 'EXPORT_FTP_SERVER'")
        self.password = password