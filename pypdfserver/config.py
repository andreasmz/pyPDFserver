import platformdirs
import configparser
from pathlib import Path

config_path = platformdirs.site_config_path(appname="pyPDFserver", appauthor=False, ensure_exists=True) / "pyPDFserver.ini"

config = configparser.ConfigParser()
config.read(Path(__file__).parent / "default.ini")
config.read(config_path)

from .log import logger

def save() -> None:
    """ Save the config file """
    try:
        with open(config_path, "w") as f:
            config.write(f)
    except Exception as ex:
        logger.error(f"Failed to save the config file:", exc_info=True)
    else:
        logger.debug(f"Saved config file to {config_path}")


save()