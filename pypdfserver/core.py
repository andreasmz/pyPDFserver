from . import log, settings
from .log import logger, debug, ConfigError
from .settings import config, profiles_config, save_config

import shutil
import tempfile
from pathlib import Path
import atexit

def legacy_cleanup() -> None:
    """ Clear previously created, not delete temporary folder """
    temp_dir = Path(tempfile.gettempdir())
    logger.debug(f"Removing old temporary files from {temp_dir}")

    if not temp_dir.exists():
        logger.warning(f"The extracted temp dir at {temp_dir} does not exist")
        return
    for f in [p for p in temp_dir.glob(f"pyPDFserver*") if p.is_dir()]:
        shutil.rmtree(f)
        logger.debug(f"Removed old temporary working folder '{f.name}'")

def cleanup() -> None:
    try:
        pyPDFserver_temp_dir.cleanup()
    except Exception as ex:
        logger.warning(f"Failed to clear the temporary working directory: ", exc_info=True)
    else:
        logger.debug(f"Cleared the temporary working directory")

try:
    config.get("SETTINGS", "clean_old_temporary_files", fallback=False)
except ValueError:
    logger.debug(f"Invalid field 'clean_old_temporary_files' in section 'SETTINGS'")
legacy_cleanup()

pyPDFserver_temp_dir = tempfile.TemporaryDirectory(prefix="pyPDFserver_")
pyPDFserver_temp_dir_path = Path(pyPDFserver_temp_dir.name)

atexit.register(cleanup)

logger.info(f"Config directory: {settings.config_path}")
logger.debug(f"Temporary working directory: {pyPDFserver_temp_dir_path}")
save_config()