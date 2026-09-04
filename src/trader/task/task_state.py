from enum import Enum

from trader.strategy.trader_result import TraderResult


class TaskStateType(Enum):
    READY = "READY"
    RUNNING = "RUNNING"
    DONE = "DONE"


class TaskState:
    def __init__(self, id: int, tret: TraderResult):
        self.id = id
        self.state = TaskStateType.READY
        self.tret = tret
