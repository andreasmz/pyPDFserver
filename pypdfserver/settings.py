import platformdirs
import configparser
from pathlib import Path

config_path = platformdirs.site_config_path(appname="pyPDFserver", appauthor=False, ensure_exists=True) / "pyPDFserver.ini"

config = configparser.ConfigParser()
config.read(Path(__file__).parent / "default.ini")
config.read(config_path)

profiles_path = platformdirs.site_config_path(appname="pyPDFserver", appauthor=False, ensure_exists=True) / "profiles.ini"

profiles_config = configparser.ConfigParser()
profiles_config.read(Path(__file__).parent / "default_profiles.ini")
profiles_config.read(profiles_path)

def save_config() -> None:
    """ Save the config file """
    from .log import logger
    try:
        with open(config_path, "w") as f:
            config.write(f)
    except Exception as ex:
        logger.error(f"Failed to save the config file: ", exc_info=True)
    else:
        logger.debug(f"Saved config file")

    try:
        with open(profiles_path, "w") as f:
            profiles_config.write(f)
    except Exception as ex:
        logger.error(f"Failed to save the profile file: ", exc_info=True)
    else:
        logger.debug(f"Saved profile file")