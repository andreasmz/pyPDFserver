from . import log, settings
from .log import logger, debug
from .settings import config, profiles_config, save as save_config

import shutil
import tempfile
from pathlib import Path
import atexit

save_config()

class ConfigError(Exception):
    def __init__(self, msg: str = "") -> None:
        super().__init__()
        self.msg = msg

def clean_full() -> None:
    """ Clear previously created, not delete temporary folder """

    temp_dir = Path(tempfile.gettempdir())
    if not temp_dir.exists():
        logger.warning(f"The extracted temp dir at {temp_dir} does not exist")
        return
    for f in [p for p in temp_dir.glob(f"pyPDFserver*") if p.is_dir()]:
        shutil.rmtree(f)
        logger.debug(f"Removed old temporary working folder '{f.name}'")

clean_full()

pyPDFserver_temp_dir = tempfile.TemporaryDirectory(prefix="pyPDFserver_")
pyPDFserver_temp_dir_path = Path(pyPDFserver_temp_dir.name)
logger.debug(f"Temporary working directory: {pyPDFserver_temp_dir_path}")

def cleanup() -> None:
    try:
        pyPDFserver_temp_dir.cleanup()
    except Exception as ex:
        logger.warning(f"Failed to clear the temporary working directory: ", exc_info=True)
    else:
        logger.debug(f"Cleared the temporary working directory")

atexit.register(cleanup)