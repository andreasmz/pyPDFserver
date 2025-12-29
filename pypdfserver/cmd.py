""" Process commands to pyPDFserver """

from .core import *
from .server import PDF_FTPServer
from . import pdf_worker
import inspect
import shlex
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from typing import Callable

class PromptShell:
    prompt = "> "

    def __init__(self):
        from . import __version__, pdf_server
        self.commands = self._collect_commands()
        self.session = PromptSession(
            completer=WordCompleter(list(self.commands.keys()), ignore_case=True)
        )

    def _collect_commands(self) -> dict[str, Callable]:
        """ Collect all cmd_ functions and register the commands """
        commands = {}
        for name, method in inspect.getmembers(self, inspect.ismethod):
            if name.startswith("cmd_"):
                commands[name[4:]] = method
        return commands

    def run(self):
        from . import pdf_server
        try:
            while True:
                input_str: str = self.session.prompt()

                if not input_str.strip():
                    continue

                parts = shlex.split(input_str)
                cmd = parts[0]
                args = parts[1:]

                logger.debug(f"User issued command {cmd} with arguments ({', '.join(args)})")

                if cmd in self.commands:
                    try:
                        self.commands[cmd](args)
                    except Exception as ex:
                        logger.error(f"Error processing command {cmd}: ", exc_info=True)
                else:
                    logger.error(f"Unkown command {cmd}")

        except (KeyboardInterrupt, SystemExit):
            logger.info(f"Stopping pyPDFserver")
            try:
                if pdf_server is not None: pdf_server.stop()
            except Exception as ex:
                logger.error(f"Failed to stop the FTP server: ", exc_info=True)
        exit()

class CmdLib(PromptShell):

    def cmd_exit(self, *args: str):
        raise KeyboardInterrupt()

    def cmd_version(self, *args: str):
        from . import __version__
        logger.info(f"pyPDFserver version {__version__}")

    def cmd_tasks(self, *args: str):
        cmd = args[0].lower() if len(args) > 0 else ""
        match cmd:
            case "list":
                s = []
                for t in pdf_worker.Task.task_list:
                    s.append(f"{t.state.name:>18}   {str(t):<40}")
                logger.info('\n'.join(s))
            case "force_clear":
                for t in pdf_worker.Task.task_list.copy():
                    if t.state != pdf_worker.TaskState.RUNNING:
                        logger.debug(f"Forced removed tasks '{str(t)}' (state {t.state})")
                        pdf_worker.Task.task_list.remove(t)
                        t.clean_up()    
            case _:
                logger.info(f"Syntax: tasks list|force_clear")
        

def start_pyPDFserver():
    from . import pdf_server

    try:
        pdf_server = PDF_FTPServer()
    except ConfigError as ex:
        logger.error(f"Configuration error: {ex.msg}. Terminating pyPDFserver")
        try:
            if pdf_server is not None: pdf_server.stop()
        except Exception as ex:
            logger.error(f"Failed to stop the FTP server: ", exc_info=True)
    cmd_lib = CmdLib()