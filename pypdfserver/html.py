""" Implemnts a simple HTML web interface """

import uuid
from flask import Flask, render_template_string

from .core import *
from .pdf_worker import Task

app = Flask(__name__)

class Webinterface:

    @app.route("/")
    def index():
        with open("html/index.html", "r", encoding="utf-8") as f:
            html = f.read()

        return render_template_string(
            html
        )
    
    def get_tasks(self) -> dict[str, tuple[str, list[Task]]]:
        task_groups: dict[str, tuple[str, list[Task]]] = {}
        for t in Task.task_list:
            group = t.group if t.group is not None else str(uuid.uuid4())
            if group not in task_groups:
                t_group_name = Task.groups.get(group, str(uuid.uuid4()))
                task_groups[group] = (t_group_name, [])
            task_groups[group][1].append(t)
        return task_groups

def launch():
    try:
        if not config.getboolean("WEBINTERFACE", "enabled"):
            return
    except ValueError:
        raise ConfigError(f"Missing or invalid field 'enabled' in section 'WEBINTERFACE'")
    
    try:
        port = profiles_config.getint("WEBINTERFACE", "port")
    except ValueError:
        port = -1
    if port <= 0 or port >= 2**16:
        logger.info(f"No or invalid port set for web server. Defaulting to 80")
        port = 80
    
    app.run(host="0.0.0.0", port=port, threaded=True)
