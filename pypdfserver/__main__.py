from . import  logger, __version__, start_pyPDFserver

logger.info(f"Loading pyPDFserver version {__version__}")
start_pyPDFserver()