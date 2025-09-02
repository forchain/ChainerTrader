from trader.utils.task_state import TaskState


class BackTraderStat:
    def __init__(self, strategy, symbol_interval, ts: TaskState):
        self.strategy = strategy
        self.symbol_interval = symbol_interval
        self.ts = ts


class TraderStat:
    def __init__(self, strategy, symbol_interval, ts: TaskState):
        self.strategy = strategy
        self.symbol_interval = symbol_interval
        self.ts = ts
