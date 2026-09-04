from enum import Enum
from typing import Any

from trader.strategy.trader_result import TraderResult
from trader.utils.operate import Operate


class TaskStateType(Enum):
    READY = "READY"
    RUNNING = "RUNNING"
    DONE = "DONE"


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

    def get_digest(self) -> dict[str, Any]:
        ret: dict[str, Any] = {
            PRIMARY_KEY: self.id,
            "state": self.state.name,
        }

        if self.tret:
            ret["tret"] = self.tret.to_dict()

        return ret
