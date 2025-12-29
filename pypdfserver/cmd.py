""" Process commands to pyPDFserver """

from .core import *
from .server import PDF_FTPServer
from . import pdf_worker
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter

commands = ["exit", "version", "tasks", "tasks_force_clear"]
completer = WordCompleter(commands, ignore_case=True)
session = PromptSession("> ", completer=completer)



def start_pyPDFserver():
    from . import __version__, pdf_server
    
    try:
        pdf_server = PDF_FTPServer()
        while True:
            cmd: str = session.prompt()
            logger.debug(f"User issued command '{cmd}'")
            match cmd.strip().lower():
                case "exit":
                    raise KeyboardInterrupt()
                case "version":
                    print(__version__)
                case "reload":
                    logger.info("Reloading the FTP server")
                    pdf_server.stop()
                    pdf_server = PDF_FTPServer()
                case "tasks":
                    s = []
                    for t in pdf_worker.Task.task_list:
                        s.append(f"{t.state.name:>18}   {str(t):<40}")
                    logger.info('\n'.join(s))
                case "tasks_force_clear":
                    for t in pdf_worker.Task.task_list.copy():
                        if t.state != pdf_worker.TaskState.RUNNING:
                            logger.debug(f"Forced removed tasks '{str(t)}' (state {t.state})")
                            pdf_worker.Task.task_list.remove(t)
                            t.clean_up()
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