import hashlib
import io
import platformdirs
import queue
from pyftpdlib.servers import FTPServer
from pyftpdlib.handlers import TLS_FTPHandler
from pyftpdlib.authorizers import DummyAuthorizer
from threading import Thread

from .core import *


class FTPAuthorizer(DummyAuthorizer):

    def validate_authentication(self, username, password, handler):
        password = hashlib.sha256(password.encode("utf-8"))
        return super().validate_authentication(username, password, handler)

class PDF_FTPHandler(TLS_FTPHandler):

    banner = "pyPDFserver"

    def ftp_STOR(self, file, mode="w"):
        buffer = io.BytesIO()
        self.uploaded_files[file] = buffer

        def data_consumer(data):
            buffer.write(data)

        self.push_dtp_data(
            data_consumer,
            isproducer=False,
            file=None
        )



        return super().ftp_STOR(file, mode)



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

        authorizer = FTPAuthorizer()
        authorizer.add_user(
            username,
            password,
            homedir=platformdirs.site_cache_path(appname="pyPDFserver", appauthor=False, ensure_exists=True) / "ftp_cache"
        )
        logger.debug(f"Created user {username} and password *****")

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