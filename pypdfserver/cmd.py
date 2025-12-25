""" Process commands to pyPDFserver """

from .core import *
from .server import *
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter

commands = ["exit", "version"]
completer = WordCompleter(commands, ignore_case=True)
session = PromptSession("> ", completer=completer)



def run():
    from . import __version__, server
    try:
        while True:
            cmd: str = session.prompt()
            match cmd.strip().lower():
                case "exit":
                    raise KeyboardInterrupt()
                case "version":
                    print(__version__)
                case "reload":
                    server.stop()
                    server = PDF_FTPServer()
                case _:
                    print(f"Invalid command '{cmd}'")
    except (KeyboardInterrupt, SystemExit):
        logger.info(f"Stopping pyPDFserver")
        try:
            server.stop()
        except Exception as ex:
            logger.error(f"Failed to stop the FTP server: ", exc_info=True)
    except ConfigError as ex:
        logger.error(ex.msg)
        logger.warning(f"Terminating pyPDFserver")
        try:
            server.stop()
        except Exception as ex:
            logger.error(f"Failed to stop the FTP server: ", exc_info=True)
    exit()