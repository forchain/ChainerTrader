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
    if name == TaskStateType.READY.name:
        return TaskStateType.READY
    elif name == TaskStateType.RUNNING.name:
        return TaskStateType.RUNNING
    elif name == TaskStateType.DONE.name:
        return TaskStateType.DONE

    return None


PRIMARY_KEY = "task_id"


class TaskState:
    def __init__(self, id: int, opts: list[Operate] = None, tret: TraderResult = None):
        self.id = id
        self.state = TaskStateType.READY
        self.tret = tret
        self.opts = opts

    def to_dict(self) -> dict[str, Any]:
        ret: dict[str, Any] = {
            PRIMARY_KEY: self.id,
            "state": self.state.name,
        }
        if self.opts:
            opts: list[Any] = []
            for opt in self.opts:
                opts.append(opt.to_dict())
            ret["opts"] = opts

        if self.tret:
            ret["tret"] = self.tret.to_dict()

        return ret

    def to_json(self):
        return json.dumps(self.to_dict(), indent=4)

    def get_digest(self) -> dict[str, Any]:
        ret: dict[str, Any] = {
            PRIMARY_KEY: self.id,
            "state": self.state.name,
        }

        if self.tret:
            ret["tret"] = self.tret.to_dict()

        return ret


def parse_task_state(data) -> TaskState:
    ts = TaskState(data[PRIMARY_KEY])
    ts.state = parse_task_state_type(data["state"])
    if "tret" in data:
        ts.tret = parse_trader_result(data["tret"])

    return ts
