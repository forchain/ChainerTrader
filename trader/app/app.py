import os
from datetime import datetime

from trader.strategy.node import Node
from trader.strategy.strategy import StrategyType, parseStrategy
from trader.common.logger import Logger
from trader.common import path


NAME = "trader"

class App:
    def __init__(self):
        self.logger=Logger(NAME)

    def name(self):
        return NAME

    def log(self):
        return self.logger.log()

    def start(self,cfg):
        self.cfg=cfg

        if cfg.log_file:
            self.logger.enableFile()

        self.startTime=datetime.now()

        self.log().info(f"Start {self.name()} App, config:{cfg.to_dict()}")
        if self.cfg.strategy:
            self.startStrategy()

        return True

    def stop(self):
        elapsed = datetime.now() - self.startTime
        self.log().info(f"Stop {self.name()} App, strategy type:{self.cfg.strategy.name}, elapsed time:{elapsed}")

    def version(self):
        filePath = os.path.join(path.GetTraderDir(), 'VERSION')

        with open(filePath, "r", encoding="utf-8") as file:
            content = file.read()
            return content

    def startStrategy(self):
        strategy = parseStrategy(self.cfg.strategy)
        node = Node(strategy, self.cfg.plot, self.cfg.commission, self.cfg.atr,self.cfg.mode)
        node.start()

    def info(self):
        return {
            "name":self.name(),
            "version":self.version(),
            "commission": self.cfg.commission,
            "period": self.cfg.period,
            "atr": self.cfg.atr,
        }