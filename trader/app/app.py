import logging

from trader.strategy.strategy import parseStrategyType
from trader.utils.logger import Logger

NAME = "trader"

class App:
    def __init__(self):
        self.logger=Logger(NAME,logging.DEBUG)

    def name(self):
        return NAME

    def log(self):
        return self.logger.log()

    def start(self,strategyType):
        self.strategy=parseStrategyType(strategyType)

        self.log().info(f"Start {self.name()} App, strategy type:{self.strategy.name}")

    def stop(self):
        self.log().info(f"Stop {self.name()} App, strategy type:{self.strategy.name}")