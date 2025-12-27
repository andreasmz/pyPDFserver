"""
pyPDFserver - A locally hosted scan destination to apply OCR and duplex to scans
"""
__author__ = "Andreas Brilka"
__version__ = "0.1.0"

from .core import *
from .server import PDF_FTPServer
from .cmd import start_pyPDFserver

logger.info(f"Loading pyPDFserver version {__version__}")

pdf_server: PDF_FTPServer|None = None