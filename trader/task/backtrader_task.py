
from trader.strategy.node import Node
from trader.strategy.strategy import StrategyType, parseStrategy
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import SymbolInterval


class BackTraderTask:
    def __init__(self,tcfg:TaskConfig,cfg,log):
        self.log = log
        self.cfg=cfg
        self.symbol_interval: SymbolInterval = tcfg.symbol_interval
        self.log.info(f"Init {self.name()}")

    def start(self):
        if self.cfg.strategy:
            self.startStrategy()
        else:
            self.log.warning(f"No strategy")

    def startStrategy(self):
        strategy = parseStrategy(self.cfg.strategy)
        node = Node(strategy, self.cfg,self.log)
        node.start()

    def stop(self):
        pass

    def name(self):
        return f"{self.type()}({self.symbol_interval.name()})"

    def type(self):
        return TaskType.BACK_TRADER