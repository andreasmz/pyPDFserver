import queue
import threading


task_queue = queue.Queue()

def loop() -> None:
    """ Implements the main thread loop """
    while task := task_queue.get():
        