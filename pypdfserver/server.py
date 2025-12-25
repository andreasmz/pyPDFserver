from .core import *
#from .pdf_worker import task_queue, Job

import hashlib
import platformdirs
import tempfile
import shutil
import pyftpdlib.log
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

class PDF_FTPServer:

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