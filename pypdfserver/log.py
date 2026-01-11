""" Module to handle the logging in pyPDFserver """

import logging
import platformdirs
import prompt_toolkit
import sys
import threading
import types
from logging.handlers import RotatingFileHandler

from .settings import config

class ColorFormatter(logging.Formatter):

    COLORS = {
        logging.DEBUG: "\x1b[38;5;244m",
        logging.INFO: "\x1b[38;5;39m",
        logging.WARNING: "\x1b[38;5;214m",
        logging.ERROR: "\x1b[38;5;196m",
        logging.CRITICAL: "\x1b[1;38;5;196m",
    }

    RESET_COLOR = "\x1b[0m"

    def format(self, record: logging.LogRecord) -> str:
        global use_colors
        msg = super().format(record)
        if use_colors:
            color = self.COLORS.get(record.levelno, "")
            return f"{color}{msg}{self.__class__.RESET_COLOR}"
        return msg

class PromptToolkitHandler(logging.Handler):
    """ Implements prompttoolkit logging """

    def emit(self, record: logging.LogRecord) -> None:
        prompt_toolkit.print_formatted_text(prompt_toolkit.formatted_text.ANSI(self.format(record)))

log_dir = platformdirs.user_log_path(appname="pyPDFserver", appauthor=False, ensure_exists=True)

logger = logging.getLogger("pyPDFserver")
logger.setLevel(logging.DEBUG)

_file_formatter = logging.Formatter('[%(asctime)s %(levelname)s %(name)s]: %(message)s')
_stream_formatter = ColorFormatter('[%(asctime)s %(levelname)s]: %(message)s')
_lib_stream_formatter = logging.Formatter('[%(asctime)s %(levelname)s %(name)s]: %(message)s')

try:
    use_colors = config.getboolean("SETTINGS", "log_colors")
except ValueError:
    use_colors = False

try:
    interactive_shell = config.getboolean("SETTINGS", "interactive_shell")
except ValueError:
    interactive_shell = False

_log_handler = PromptToolkitHandler() if interactive_shell else logging.StreamHandler()
_log_handler.setFormatter(_stream_formatter)
logger.addHandler(_log_handler)

lib_log_handler = PromptToolkitHandler() if interactive_shell else logging.StreamHandler()
lib_log_handler.setFormatter(_lib_stream_formatter)

file_log_handler = None

if config.getboolean("SETTINGS", "log_to_file", fallback=True):
    file_log_handler = RotatingFileHandler(log_dir / "pyPDFserver.logs", mode="a", maxBytes=(1024**2), backupCount=5, encoding="utf-8")
    file_log_handler.setFormatter(_file_formatter)
    file_log_handler.setLevel(logging.DEBUG)
    logger.addHandler(file_log_handler)
    logger.info(f"Logging directory: {log_dir}")

def log_exceptions_hook(exc_type: type[BaseException], exc_value: BaseException, exc_traceback: types.TracebackType | None = None) -> None:
    global logger
    logger.exception(f"{exc_type.__name__}:", exc_info=(exc_type, exc_value, exc_traceback))

def thread_exceptions_hook(except_hook_args: threading.ExceptHookArgs):
    global logger
    exc_type, exc_value, exc_traceback, thread = except_hook_args.exc_type, except_hook_args.exc_value, except_hook_args.exc_traceback, except_hook_args.thread
    logger.exception(f"{exc_type.__name__} in thread '{thread.name if thread is not None else ''}':", 
                     exc_info=(exc_type, exc_value if exc_value is not None else BaseException(), exc_traceback))

sys.excepthook = log_exceptions_hook
threading.excepthook = thread_exceptions_hook


match _log_level := config.get("SETTINGS", "log_level", fallback="INFO").upper():
    case "DEBUG":
        _log_handler.setLevel(logging.DEBUG)
        lib_log_handler.setLevel(logging.DEBUG)
    case "INFO":
        # Use warning for external logging (e.g. OCRmyPDF) to not have to much logs
        _log_handler.setLevel(logging.INFO)
        lib_log_handler.setLevel(logging.WARNING)
    case "WARNING":
        _log_handler.setLevel(logging.WARNING)
        lib_log_handler.setLevel(logging.WARNING)
    case "ERROR":
        _log_handler.setLevel(logging.ERROR)
        lib_log_handler.setLevel(logging.ERROR)
    case "CRITICAL":
        _log_handler.setLevel(logging.CRITICAL)
        lib_log_handler.setLevel(logging.CRITICAL)
    case _:
        logger.warning(f"Invalid value '{_log_level}' for log_level. Defaulting to {logging.getLevelName(_log_handler.level)}")


def debug() -> None:
    """ Start debugging """
    _log_handler.setLevel(logging.DEBUG)
    lib_log_handler.setLevel(logging.DEBUG)
    logger.info(f"Started debugging")

if "-debug" in sys.argv:
    debug()

class ConfigError(Exception):
    def __init__(self, msg: str = "") -> None:
        super().__init__()
        self.msg = msg