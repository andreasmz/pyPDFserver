from pypdfserver.settings import save as save_config
from . import log, settings
from .log import logger, debug
from .settings import config

save_config()



class ConfigError(Exception):
    def __init__(self, msg: str = "") -> None:
        super().__init__()
        self.msg = msg
