from enum import Enum
from typing import Any
import json

from trader.strategy.trader_result import TraderResult, parse_trader_result
from trader.utils.operate import Operate


class TaskStateType(Enum):
    READY = "READY"
    RUNNING = "RUNNING"
    DONE = "DONE"


def parse_task_state_type(name):
    if name is None:
        return TaskStateType.READY  # Default to READY if name is None

    if name == TaskStateType.READY.name:
        return TaskStateType.READY
    elif name == TaskStateType.RUNNING.name:
        return TaskStateType.RUNNING
    elif name == TaskStateType.DONE.name:
        return TaskStateType.DONE

    return TaskStateType.READY  # Default to READY for unknown states


PRIMARY_KEY = "task_id"


class TaskState:
    def __init__(self, id: int, tret: TraderResult = None):
        self.id = id
        self.state = TaskStateType.READY
        self.tret = tret

    def to_dict(self) -> dict[str, Any]:
        ret: dict[str, Any] = {
            PRIMARY_KEY: self.id,
            "state": self.state.name,
        }

        if self.tret:
            ret["tret"] = self.tret.to_dict()

        return ret

    def to_json(self):
        return json.dumps(self.to_dict(), indent=4)

    def is_running(self) -> bool:
        return self.state == TaskStateType.RUNNING


def parse_task_state(data) -> TaskState:
    # Safely handle PRIMARY_KEY
    task_id = data.get(PRIMARY_KEY)
    if task_id is None:
        raise ValueError(f"Missing required field: {PRIMARY_KEY}")

    # Convert task_id to int if it's a string
    if isinstance(task_id, str):
        try:
            task_id = int(task_id)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid task_id format: {task_id}")

    ts = TaskState(task_id)

    # Safely handle state field
    state_name = data.get("state")
    if state_name:
        ts.state = parse_task_state_type(state_name)

    # Safely handle tret field
    if "tret" in data and data["tret"] is not None:
        try:
            ts.tret = parse_trader_result(data["tret"])
        except Exception as e:
            # Log error and continue without tret
            print(f"Error parsing trader result: {e}")
            ts.tret = None

    return ts
