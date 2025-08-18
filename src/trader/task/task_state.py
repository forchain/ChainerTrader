from enum import Enum

from trader.strategy.trader_result import TraderResult
from trader.utils.operate import Operate


class TaskStateType(Enum):
    READY = "READY"
    RUNNING = "RUNNING"
    DONE = "DONE"


class TaskState:
    def __init__(self, id: int,opts:list[Operate]=None, tret: TraderResult=None):
        self.id = id
        self.state = TaskStateType.READY
        self.tret = tret
        self.opts = opts
