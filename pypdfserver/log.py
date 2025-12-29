""" Module to handle the logging in pyPDFserver """

import logging
import platformdirs
import prompt_toolkit
import sys
import threading
import types
from logging.handlers import RotatingFileHandler

from .settings import config

class StdOutLogger(logging.Handler):
    """ Implements prompttoolkit logging """

    COLORS = {
        logging.DEBUG: "\x1b[38;5;244m",
        logging.INFO: "\x1b[38;5;39m",
        logging.WARNING: "\x1b[38;5;214m",
        logging.ERROR: "\x1b[38;5;196m",
        logging.CRITICAL: "\x1b[1;38;5;196m",
    }

    RESET_COLOR = "\x1b[0m"

    def __init__(self, level: int | str = 0) -> types.NoneType:
        try:
            self.use_colors = config.getboolean("SETTINGS", "log_colors")
        except ValueError:
            self.use_colors = False
        return super().__init__(level)

    def emit(self, record: logging.LogRecord) -> types.NoneType:
        color = self.COLORS.get(record.levelno, "")
        msg = self.format(record)
        if self.use_colors:
            msg = f"{color}{msg}{self.__class__.RESET_COLOR}"
        prompt_toolkit.print_formatted_text(prompt_toolkit.formatted_text.ANSI(msg))

log_dir = platformdirs.user_log_path(appname="pyPDFserver", appauthor=False, ensure_exists=True)

logger = logging.getLogger("pyPDFserver")
logger.setLevel(logging.INFO)

_formatter = logging.Formatter('[%(asctime)s %(levelname)s]: %(message)s')

_stream_handler = StdOutLogger()
_stream_handler.setFormatter(_formatter)
_stream_handler.setLevel(logging.DEBUG)
logger.addHandler(_stream_handler)

if config.getboolean("SETTINGS", "log_to_file", fallback=True):
    _file_handler = RotatingFileHandler(log_dir / "pyPDFserver.logs", mode="a", maxBytes=(1024**2), backupCount=5)
    _file_handler.setFormatter(_formatter)
    _file_handler.setLevel(logging.DEBUG)
    logger.addHandler(_file_handler)
    logger.info(f"Logging directory: {log_dir}")


def log_exceptions_hook(exc_type: type[BaseException], exc_value: BaseException, exc_traceback: types.TracebackType | None = None) -> None:
    global logger
    logger.exception(f"{exc_type.__name__}:", exc_info=(exc_type, exc_value, exc_traceback))
    #sys.__excepthook__(exc_type, exc_value, exc_traceback)

def thread_exceptions_hook(except_hook_args: threading.ExceptHookArgs):
    global logger
    exc_type, exc_value, exc_traceback, thread = except_hook_args.exc_type, except_hook_args.exc_value, except_hook_args.exc_traceback, except_hook_args.thread
    logger.exception(f"{exc_type.__name__} in thread '{thread.name if thread is not None else ''}':", 
                     exc_info=(exc_type, exc_value if exc_value is not None else BaseException(), exc_traceback))
    #sys.__excepthook__(exc_type, exc_value if exc_value is not None else BaseException(), exc_traceback)

sys.excepthook = log_exceptions_hook
threading.excepthook = thread_exceptions_hook


match _log_level := config.get("SETTINGS", "log_level", fallback="INFO").upper():
    case "DEBUG":
        logger.setLevel(logging.DEBUG)
    case "INFO":
        logger.setLevel(logging.INFO)
    case "WARNING":
        logger.setLevel(logging.WARNING)
    case "ERROR":
        logger.setLevel(logging.ERROR)
    case "CRITICAL":
        logger.setLevel(logging.CRITICAL)
    case _:
        logger.warning(f"Invalid value '{_log_level}' for log_level")


def debug() -> None:
    """ Start debugging """
    logger.setLevel(logging.DEBUG)
    logger.info(f"Started debugging")

if "-debug" in sys.argv:
    debug()

class ConfigError(Exception):
    def __init__(self, msg: str = "") -> None:
        super().__init__()
        self.msg = msg