from .core import *

import hashlib
import platformdirs
import pyftpdlib.log
import re
import tempfile
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

pyftpdlib.log.config_logging(level=pyftpdlib.log.logging.WARNING)

class FTPAuthorizer(DummyAuthorizer):

    def validate_authentication(self, username: str, password: str, handler):
        logger.debug(f"{password}, {hashlib.sha256(password.encode("utf-8")).hexdigest()}")
        return super().validate_authentication(username, hashlib.sha256(password.encode("utf-8")).hexdigest(), handler)


class PDF_FTPHandler(FTPHandler):

    banner = "pyPDFserver"
    _temp_dir_prefix = "pyPDFserver_tmp_"

    def __init__(self, conn, server: "PDF_FTPServer", ioloop=None):
        super().__init__(conn, server, ioloop)
        self.server = server
        self.duplex_pdf_cache: None|tuple[str, datetime] = None

    def on_connect(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix=PDF_FTPHandler._temp_dir_prefix)
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
        logger.debug(f"Received file '{file}'")

        if (r := self.server.duplex1_regex.match(file)):
            logger.info(f"Received duplex front pages '{file}'")
            if self.duplex_pdf_cache is not None:
                logger.info(f"Discarding previous duplex pront pages '{self.duplex_pdf_cache[0]}'")
            self.duplex_pdf_cache = (file, datetime.now())
        elif (r := self.server.duplex2_regex.match(file)):
            
            if self.duplex_pdf_cache is None:
                logger.info(f"Received duplex back pages '{file}', but discarded them as the pront pages are missing")
                return
            elif (d := (datetime.now() - self.duplex_pdf_cache[1])).total_seconds() > self.server.duplex_timeout:
                logger.info(f"Received duplex back pages '{file}', but discarded them due to timeout (first file received {d.total_seconds()} ago)")
                return
            


class PDF_FTPServer:

    TEMPLATE_STRINGS: dict[str, str] = {
        "%lang%": r"(?P<lang>[a-zA-Z]+)",
        "%s%": r"(?P<s>.*)",
    }

    def __init__(self) -> None:
        self.clear() # Perform artifact cleaning first

        username = config.get("FTP", "username", fallback=None)
        if username is None:
            raise ConfigError(f"Missing field 'username' in section 'FTP' in the given config file")
        password = config.get("FTP", "password", fallback=None)
        if password is None:
            raise ConfigError(f"Missing field 'password' in section 'FTP' in the given config file")
        if password.startswith("$SHA256$") and password.endswith("$"):
            password = password.strip("$").replace("SHA256$", "")
        else:
            password = hashlib.sha256(password.encode("utf-8")).hexdigest()
            config.set("FTP", "password", f"$SHA256${password}$")
            save_config()
            logger.debug(f"Hashed password and saved it back to config")

        logger.debug(password)
            
        home_dir = platformdirs.site_cache_path(appname="pyPDFserver", appauthor=False, ensure_exists=True) / "ftp_cache"
        home_dir.mkdir(exist_ok=True, parents=False)

        authorizer = FTPAuthorizer()
        authorizer.add_user(
            username,
            password,
            homedir=home_dir,
            perm="w",
            msg_login="Connected to pyPDFserver"
        )
        logger.debug(f"Created user {username} and password ***** on virtual cache directory {home_dir}")

        host = config.get("FTP", "host")
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

        scan_template = config.get("FILE_NAMES", "input_scan", fallback=None)
        if scan_template is None:
            raise ConfigError(f"Missing field 'input_scan' in section 'FILE_NAME'")
        scan_template = re.escape(scan_template)
        for k, v in PDF_FTPServer.TEMPLATE_STRINGS.items():
            scan_template = scan_template.replace(k, v)
        self.scan_regex = re.compile(scan_template)

        duplex1_template = config.get("FILE_NAMES", "input_duplex1", fallback=None)
        if duplex1_template is None:
            raise ConfigError(f"Missing field 'input_duplex1' in section 'FILE_NAME'")
        duplex1_template = re.escape(duplex1_template)
        for k, v in PDF_FTPServer.TEMPLATE_STRINGS.items():
            duplex1_template = duplex1_template.replace(k, v)
        self.duplex1_regex = re.compile(duplex1_template)

        duplex2_template = config.get("FILE_NAMES", "input_duplex2", fallback=None)
        if duplex2_template is None:
            raise ConfigError(f"Missing field 'input_duplex2' in section 'FILE_NAME'")
        duplex2_template = re.escape(duplex2_template)
        for k, v in PDF_FTPServer.TEMPLATE_STRINGS.items():
            duplex2_template = duplex2_template.replace(k, v)
        self.duplex2_regex = re.compile(duplex2_template)

        self.export_template = config.get("FILE_NAMES", "export_name", fallback=None)
        if self.export_template is None:
            raise ConfigError(f"Missing field 'export_name' in section 'FILE_NAME'")
        
        try:
            duplex_timeout = config.getint("SETTINGS", "duplex_timeout", fallback=None)
        except ValueError:
            duplex_timeout = None
        if duplex_timeout is None:
            raise ConfigError(f"Missing or invalid field 'duplex_timeout' in section 'SETTINGS'")
        self.duplex_timeout = max(0, duplex_timeout)

        self.thread = Thread(target=self._loop, name="PDF_FTPServer_main", daemon=True)
        self.thread.start()

    def _loop(self) -> None:
        self.server.serve_forever()

    def stop(self) -> None:
        """ Stop the server """
        if self.thread.is_alive():
            self.server.close_all()
            logger.debug(f"Stopped the FTP server")

    def clear(self) -> None:
        """ 
        Clears all not automatically cleared temp files. Note that this only occurs when pyPDFserver
        is hard interupted
        """
        temp_dir = Path(tempfile.gettempdir())
        if not temp_dir.exists():
            logger.warning(f"The extracted temp dir at {temp_dir} does not exist")
            return
        for f in [p for p in temp_dir.glob(f"{PDF_FTPHandler._temp_dir_prefix}*") if p.is_dir()]:
            # TODO: Actually delete the file
            #shutil.rmtree(f)
            logger.warning(f"Removed artifact temp folder '{f.name}'")