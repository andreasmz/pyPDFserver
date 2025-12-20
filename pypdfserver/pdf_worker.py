import threading
from enum import Enum
from queue import Queue

class State(Enum):
    UNKOWN = 0
    SCHEDULED = 1
    RUNNING = 2
    FINISHED = 3
    ABORTED = 4
    FAILED = 5

class Job:
    
    def __init__(self) -> None:
        self.state = State.SCHEDULED


task_queue: Queue[Job] = Queue()

def loop() -> None:
    """ Implements the main thread loop """
    while task := task_queue.get():
        