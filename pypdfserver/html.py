""" Implemnts a simple HTML web interface """

import threading
import uuid
from datetime import datetime, timedelta
from flask import Flask, render_template_string, render_template

from .core import *
from . import __version__
from .pdf_worker import Task, TaskState

app = Flask(__name__)

app.logger.addHandler(file_log_handler)
app.logger.setLevel(log.logging.WARNING)

# Disable server logging
log.logging.getLogger("werkzeug").setLevel(log.logging.ERROR)

class Webinterface:

    state_map: dict[TaskState, tuple[str, str]] = {
        TaskState.CREATED: ("", "bi-clock-fill text-secondary"),
        TaskState.SCHEDULED: ("Scheduled", "bi-clock-fill text-secondary"),
        TaskState.WAITING: ("Waiting", "bi-arrow-repeat text-secondary"),
        TaskState.RUNNING: ("Running", "bi-arrow-repeat text-primary"),
        TaskState.FINISHED: ("", "bi-check-circle-fill text-success"),
        TaskState.FAILED: ("Failed", "bi-x-circle-fill text-danger"),
        TaskState.ABORTED: ("Aborted", "bi-x-circle-fill text-danger"),
        TaskState.DEPENDENCY_FAILED: ("Canceled", "bi-x-circle-fill text-danger"),
        TaskState.UNKOWN_ERROR: ("Unknown error", "bi-x-circle-fill text-danger")
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
        logger.debug(f"Started flask server (thread {self.thread.ident})")
        app.run(host="0.0.0.0", port=self.port, debug=False, use_reloader=False)

    @app.route("/")
    def index():
        with open(Path(__file__).parent / "html" / "index.html", "r", encoding="utf-8") as f:
            html = f.read()

        (num_total_tasks, num_scheduled_tasks, num_failed_tasks), group_dict = Webinterface.get_tasks()

        task_groups = [{"uuid": group_uuid, 
                        "html_id": f"group_{group_uuid.replace('-','_')}", 
                        "name": group_name, 
                        "time_started": Webinterface.format_datetime(Webinterface.get_task_group_t_start(tasks)),
                        "time_finished": Webinterface.format_datetime(Webinterface.get_task_group_t_end(tasks)),
                        "runtime": Webinterface.format_timespan(Webinterface.get_task_group_runtime(tasks)),
                        "state_name": Webinterface.state_map.get(group_state, ("Unkown", "bi-question-circle"))[0],
                        "state_icon": Webinterface.state_map.get(group_state, ("Unkown", "bi-question-circle"))[1],
                        "tasks": [
                            {
                                "uuid": t.uuid,
                                "name": t.name,
                                "error": t.error.message if t.error is not None else "",
                                "desc": t.desc,
                                "time_started": Webinterface.format_datetime(t.t_start),
                                "time_finished": Webinterface.format_datetime(t.t_end),
                                "runtime": Webinterface.format_timespan(t.runtime),
                                "state_name": Webinterface.state_map.get(t.state, ("Unkown", "bi-question-circle"))[0],
                                "state_icon": Webinterface.state_map.get(t.state, ("Unkown", "bi-question-circle"))[1],
                            }
                        for t in tasks],
                       } for group_uuid, (group_name, group_state, tasks) in group_dict.items()]
        
        return render_template_string(html, task_groups=task_groups, version=__version__)


    @classmethod
    def get_task_group_t_created(cls, tasks: list[Task]) -> datetime|None:
        t_created = datetime.max
        for t in tasks:
            if t.t_created is None:
                continue
            t_created = min(t_created, t.t_created)
        if t_created == datetime.max:
            return None
        return t_created
    
    @classmethod
    def get_task_group_t_start(cls, tasks: list[Task]) -> datetime|None:
        start_time = datetime.max
        for t in tasks:
            if t.t_start is None:
                continue
            start_time = min(start_time, t.t_start)
        if start_time == datetime.max:
            return None
        return start_time
    
    @classmethod
    def get_task_group_t_end(cls, tasks: list[Task]) -> datetime|None:
        end_time = datetime.min
        for t in tasks:
            if t.t_end is None:
                return None
            end_time = max(end_time, t.t_end)
        if end_time == datetime.min:
            return None
        return end_time
    
    @classmethod
    def get_task_group_runtime(cls, tasks: list[Task]) -> timedelta|None:
        t_start, t_end = cls.get_task_group_t_start(tasks), cls.get_task_group_t_end(tasks)
        if t_start is None or t_end is None:
            return None
        return t_end - t_start

    @classmethod
    def format_datetime(cls, dt: datetime|None) -> str:
        if dt is None:
            return ""
        today = datetime.now()
        if dt.date() == today.date():
            return dt.strftime("%H:%M:%S")
        return dt.strftime("%Y-%m-%d")
    
    @classmethod
    def format_datetime_difference(cls, dt: datetime|None) -> str:
        if dt is None:
            return ""
        return cls.format_timespan(datetime.now() - dt) + " ago"
        
    @classmethod
    def format_timespan(cls, delta: timedelta|None) -> str:
        if delta is None:
            return ""
        days = delta.days
        seconds = delta.seconds
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60 
        seconds = seconds % 60
        if days > 0:
            return f"{days}:{hours:02d}:{minutes:02d};{seconds:02d}"
        elif hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        elif minutes > 0:
            return f"{minutes:02d}:{seconds:02d}"
        else:
            return f"{seconds} s"

    @classmethod
    def get_tasks(cls) -> tuple[tuple[int, int, int], dict[str, tuple[str, TaskState, list[Task]]]]:
        """ Returns the tasks grouped by their group
        
        (num_total_tasks, num_scheduled_tasks, num_failed_tasks), {group_uuid -> (group_name, list[tasks])}
        """
        task_groups: dict[str, tuple[str, list[Task]]] = {}
        i_total, i_scheduled, i_failed = 0, 0, 0
        for t in Task.task_list:
            if t.hidden:
                continue
            i_total += 1
            if t.state in [TaskState.CREATED, TaskState.SCHEDULED, TaskState.WAITING, TaskState.RUNNING]:
                i_scheduled += 1
            elif t.state not in [TaskState.FINISHED]:
                i_failed += 1
            group = t.group if t.group is not None else str(uuid.uuid4())
            if group not in task_groups:
                t_group_name = Task.groups.get(group, str(uuid.uuid4()))
                task_groups[group] = (t_group_name, [])
            task_groups[group][1].append(t)

        return ((i_total, i_scheduled, i_failed), 
                    {group_uuid: (group_name, TaskState.merge_states(*[t.state for t in tasks]), tasks) 
                     for group_uuid, (group_name, tasks) in task_groups.items()}
                )

def launch():
    global web_interface
    try:
        if not config.getboolean("WEBINTERFACE", "enabled"):
            return
    except ValueError:
        raise ConfigError(f"Missing or invalid field 'enabled' in section 'WEBINTERFACE'")
    web_interface = Webinterface()