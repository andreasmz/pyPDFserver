import hashlib
import io
import platformdirs
from pathlib import Path
from pyftpdlib.servers import FTPServer
from pyftpdlib.handlers import TLS_FTPHandler
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.filesystems import AbstractedFS
from threading import Thread

import os

os.path.realpath("")

from .core import *
from .pdf_worker import task_queue, Job


class FTPAuthorizer(DummyAuthorizer):

    def validate_authentication(self, username: str, password: str, handler):
        return super().validate_authentication(username, hashlib.sha256(password.encode("utf-8")), handler)
    

class PDF_AbstractedFS(AbstractedFS):

    def __init__(self, root, cmd_channel):
        logger.debug(f"[DEBUG 25]: {type(root)}, {type(cmd_channel)}")
        super().__init__(root, cmd_channel)

    # self.root
    # self.cmd
    # def ftpnorm
    # def ftp2fs
    # def fs2ftp
    
    def validpath(self, path: str):
        

    def open(self, filename, mode):
        buffer = io.BytesIO()
        return buffer
    
    def mkdir(self, path: Path) -> None:
        # Do not create directories
        pass

    def chdir(self, path) -> None:
        # Do not allow to change directories
        pass

    def rmdir(self, path):
        return super().rmdir(path)

    
    def listdir(self, path):
        return []
    

class PDF_FTPHandler(TLS_FTPHandler):

    banner = "pyPDFserver"
    abstracted_fs = PDF_AbstractedFS


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