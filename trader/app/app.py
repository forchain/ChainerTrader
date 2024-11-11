import logging,os

from trader.strategy.strategy import parseStrategyType
from trader.utils.logger import Logger
from trader.utils import path

NAME = "trader"

class App:
    def __init__(self):
        self.logger=Logger(NAME,logging.DEBUG)

    def name(self):
        return NAME

    def log(self):
        return self.logger.log()

    def start(self,strategyType,commission=0.001,atr=True,period=14,trend=False):
        self.strategy=parseStrategyType(strategyType)
        self.commission=commission
        self.period=period
        self.atr=atr
        self.trend=trend

        self.log().info(f"Start {self.name()} App, strategy type:{self.strategy.name} commission:{commission}")

        return True

    def stop(self):
        self.log().info(f"Stop {self.name()} App, strategy type:{self.strategy.name}")

    def version(self):
        filePath = os.path.join(path.GetTraderDir(), 'VERSION')

        with open(filePath, "r", encoding="utf-8") as file:
            content = file.read()
            return content
        return "None"