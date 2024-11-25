
from trader.strategy.node import Node
from trader.strategy.strategy import StrategyType, parseStrategy

class StaticTask:
    def __init__(self,cfg,log):
        self.log = log
        self.cfg=cfg
        self.log.info(f"Init StaticTask")

    def start(self):
        if self.cfg.strategy:
            self.startStrategy()
        else:
            self.log.warning(f"No strategy")

    def startStrategy(self):
        strategy = parseStrategy(self.cfg.strategy)
        node = Node(strategy, self.cfg,self.log())
        node.start()

    def stop(self):
        pass