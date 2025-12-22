"""
pyPDFserver - A locally hosted scan destination to apply OCR and duplex to scans
"""
__author__ = "Andreas Brilka"
__version__ = "0.1.0"

from .core import *
from .server import PDF_FTPServer

logger.info(f"Loading pyPDFserver version {__version__}")
logger.debug(f"Log dir: {log.log_dir}")
logger.debug(f"Config path: {settings.config_path}")

server = PDF_FTPServer()

try:
    while True:
        cmd = input("> ")
        match cmd.strip().upper():
            case "exit":
                raise KeyboardInterrupt()
            case _:
                print(f"Invalid command '{cmd}'")
except (KeyboardInterrupt, SystemExit):
    logger.info(f"Stopping pyPDFserver")
except ConfigError as ex:
    logger.error(ex.msg)
    logger.warning(f"Terminating pyPDFserver")

exit()