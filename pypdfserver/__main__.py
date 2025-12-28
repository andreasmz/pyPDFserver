from .pkg import RUN_AS_MAIN
RUN_AS_MAIN = True
from . import  logger, __version__, start_pyPDFserver

logger.info(f"Loading pyPDFserver version {__version__}")
start_pyPDFserver()