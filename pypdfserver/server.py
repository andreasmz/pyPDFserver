import hashlib
import io
import platformdirs
import tempfile
from pathlib import Path
from pyftpdlib.servers import FTPServer
from pyftpdlib.handlers import TLS_FTPHandler
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.filesystems import AbstractedFS
from threading import Thread


from .core import *
from .pdf_worker import task_queue, Job

class FTPAuthorizer(DummyAuthorizer):

    def validate_authentication(self, username: str, password: str, handler):
        return super().validate_authentication(username, hashlib.sha256(password.encode("utf-8")), handler)
    


class PDF_FTPHandler(TLS_FTPHandler):

    banner = "pyPDFserver"

    def on_connect(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory(prefix="pyPDFserver")
        if self.fs is not None:
            self.fs.chdir(self.temp_dir)
        logger.debug(f"Client {self.remote_ip}:{self.remote_port} connected to temporary directory {self.temp_dir}")
        super().on_connect()    

    def on_disconnect(self) -> None:
        super().on_disconnect()
        logger.debug(f"Client {self.remote_ip}:{self.remote_port} disconected. Removing temporary directory {self.temp_dir}")
        self.temp_dir.cleanup()

    def on_file_received(self, file: str):
        super().on_file_received(file)
        logger.debug(f"Received file '{file}'")


class PDF_FTPServer:

    def __init__(self) -> None:
        username = config.get("FTP", "username")
        if username is None:
            raise ConfigError(f"Missing field 'username' in section 'FTP' in the given config file")
        password = config.get("FTP", "password")
        if password is None:
            raise ConfigError(f"Missing field 'password' in section 'FTP' in the given config file")
        if password.startswith("$SHA256$") and password.endswith("$"):
            password = password.strip("$").strip("SHA256$")
        else:
            password = hashlib.sha256(password.encode("utf-8"))
            config.set("FTP", "password", f"$SHA256${password}$")
            logger.debug(f"Hashed password and saved it back to config")

        home_dir = platformdirs.site_cache_path(appname="pyPDFserver", appauthor=False, ensure_exists=True) / "ftp_cache"

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
        if host is None:
            logger.info(f"No host set. Defaulting to 127.0.0.1")
            host = "127.0.0.1"

        port = config.getint("FTP", "port", fallback=-1)
        if port <= 0 or port >= 2**16:
            logger.info(f"No or invalid port set. Defaulting to 80")
            port = 80

            
        handler = PDF_FTPHandler
        handler.authorizer = authorizer
        
        self.server = FTPServer((host, port), handler)

        self.thread = Thread(target=self._loop, name="PDF_FTPServer_main", daemon=True)
        self.thread.start()

    def _loop(self) -> None:
        self.server.serve_forever()