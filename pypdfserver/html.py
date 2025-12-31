""" Implemnts a simple HTML web interface """

import threading
import uuid
from flask import Flask, render_template_string

from .core import *
from .pdf_worker import Task, TaskState

app = Flask(__name__)

class Webinterface:

    state_map: dict[TaskState, tuple[str, str]] = {
        TaskState.CREATED: ("Created", "bi-clock-fill"),
        TaskState.SCHEDULED: ("Scheduled", "bi-clock-fill"),
        TaskState.WAITING: ("Waiting", "bi-arrow-repeat"),
        TaskState.RUNNING: ("Running", "bi-arrow-repeat"),
        TaskState.FINISHED: ("Finished", "bi-check-circle-fill"),
        TaskState.FAILED: ("Failed", "bi-x-circle-fill"),
        TaskState.ABORTED: ("Aborted", "bi-x-circle-fill"),
        TaskState.DEPENDENCY_FAILED: ("Dependency failed", "bi-x-circle-fill"),
        TaskState.UNKOWN_ERROR: ("Unknown error", "bi-x-circle-fill")
    }

    def __init__(self) -> None:
        try:
            port = config.getint("WEBINTERFACE", "port")
        except ValueError:
            port = -1
        if port <= 0 or port >= 2**16:
            logger.info(f"No or invalid port set for web server. Defaulting to 80")
            port = 80
        self.port = port
        
        self.thread = threading.Thread(target=self._run, name="Flask webserver", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        app.run(host="0.0.0.0", port=self.port, debug=False, use_reload=False)

    @app.route("/")
    def index():
        with open(Path(__file__).parent / "html" / "index.html", "r", encoding="utf-8") as f:
            html = f.read()

        i, group_dict = Webinterface.get_tasks()
        s = Webinterface.render_task_groups(group_dict)

        return render_template_string(
            html,
            Tasks=s,
            num_scheduled=i
        )
    
    @classmethod
    def render_task_groups(cls, group_dict: dict[str, tuple[str, list[Task]]]) -> str:
        with open(Path(__file__).parent / "html" / "task_group_template.html", "r", encoding="utf-8") as f:
            html = f.read()

        s = ""

        for group_uuid, (group_name, tasks) in group_dict.items():
            group_state = TaskState.merge_states(*[t.state for t in tasks])
            state_name, state_icon = Webinterface.state_map.get(group_state, ("Unkown", "bi-question-circle"))

            s_tasks = cls.render_tasks(tasks)

            s += render_template_string(
                html,
                uuid=group_uuid,
                name=group_name,
                state_name=state_name,
                state_icon=state_icon,
                tasks=s_tasks
            )

        return s

    @classmethod
    def render_tasks(cls, tasks: list[Task]) -> str:
        with open(Path(__file__).parent / "html" / "task_template.html", "r", encoding="utf-8") as f:
            html = f.read()

        s = ""
        for t in tasks:
            state_name, state_icon = Webinterface.state_map.get(t.state, ("Unkown", "bi-question-circle"))
            s += render_template_string(
                html,
                uuid=t.uuid,
                name=str(t),
                state=state_name,
                state_icon=state_icon
            )
        return s
    

    @classmethod
    def get_tasks(cls) -> tuple[int, dict[str, tuple[str, list[Task]]]]:
        task_groups: dict[str, tuple[str, list[Task]]] = {}
        i = 0
        for t in Task.task_list:
            if t.hidden:
                continue
            if t.state in [TaskState.CREATED, TaskState.SCHEDULED, TaskState.WAITING, TaskState.RUNNING]:
                i += 1
            group = t.group if t.group is not None else str(uuid.uuid4())
            if group not in task_groups:
                t_group_name = Task.groups.get(group, str(uuid.uuid4()))
                task_groups[group] = (t_group_name, [])
            task_groups[group][1].append(t)
        return (i, task_groups)

def launch():
    global web_interface
    try:
        if not config.getboolean("WEBINTERFACE", "enabled"):
            return
    except ValueError:
        raise ConfigError(f"Missing or invalid field 'enabled' in section 'WEBINTERFACE'")
    web_interface = Webinterface()