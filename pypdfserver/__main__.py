from . import  __version__
from .core import *
from .server import PDF_FTPServer
from .cmd import start_pyPDFserver

logger.info(f"Loading pyPDFserver version {__version__}")

pdf_server: PDF_FTPServer|None = None

if __name__ == "__main__":
    start_pyPDFserver()