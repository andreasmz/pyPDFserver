import platformdirs
import configparser
from pathlib import Path

config_path = platformdirs.site_config_path(appname="pyPDFserver", appauthor=False, ensure_exists=True) / "pyPDFserver.ini"

config = configparser.ConfigParser()
config.read(Path(__file__).parent / "default.ini")
config.read(config_path)
