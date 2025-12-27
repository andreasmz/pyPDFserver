""" Process commands to pyPDFserver """

from .core import *
from .server import PDF_FTPServer
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter

commands = ["exit", "version"]
completer = WordCompleter(commands, ignore_case=True)
session = PromptSession("> ", completer=completer)



def start_pyPDFserver():
    from . import __version__, pdf_server
    
    try:
        pdf_server = PDF_FTPServer()
        while True:
            cmd: str = session.prompt()
            match cmd.strip().lower():
                case "exit":
                    raise KeyboardInterrupt()
                case "version":
                    print(__version__)
                case "reload":
                    pdf_server.stop()
                    pdf_server = PDF_FTPServer()
                case _:
                    print(f"Invalid command '{cmd}'")
    except (KeyboardInterrupt, SystemExit):
        logger.info(f"Stopping pyPDFserver")
        try:
            if pdf_server is not None: pdf_server.stop()
        except Exception as ex:
            logger.error(f"Failed to stop the FTP server: ", exc_info=True)
    except ConfigError as ex:
        logger.error(f"Configuration error: {ex.msg}. Terminating pyPDFserver")
        try:
            if pdf_server is not None: pdf_server.stop()
        except Exception as ex:
            logger.error(f"Failed to stop the FTP server: ", exc_info=True)
    exit()