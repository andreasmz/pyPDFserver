from pypdfserver.settings import save as save_config
from . import log, settings
from .log import logger, debug
from .settings import config
import tempfile

save_config()

class ConfigError(Exception):
    def __init__(self, msg: str = "") -> None:
        super().__init__()
        self.msg = msg


pyPDFserver_temp_dir = tempfile.TemporaryDirectory(prefix="pyPDFserver")