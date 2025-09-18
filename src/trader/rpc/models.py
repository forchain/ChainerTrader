from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime

from trader.app.app import App
from trader.utils.task_state import TaskStateType


class TasksInfo(BaseModel):
    total: int = 0
    completed: int = 0
    tasks: list[dict[str, Any]]


def get_taskinfo(app: App) -> TasksInfo:
    tss = app.task_manager.get_all_task_state()
    completed = 0
    tasks: list[dict[str, Any]] = []
    for ts in tss:
        if ts.state == TaskStateType.DONE:
            completed += 1
        tasks.append(ts.to_dict())

    return TasksInfo(total=len(tss), completed=completed, tasks=tasks)

def