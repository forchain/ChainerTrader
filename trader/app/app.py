import logging,os
from datetime import datetime

from trader.strategy.shihunmacd import shihunMACD
from trader.strategy.shihunrsi import shihunRSI
from trader.strategy.strategy import parseStrategyType, StrategyType
from trader.utils.logger import Logger
from trader.utils import path

from trader.strategy.shihunmacdrsibb import shihunMacdRsiBollingerBand
from trader.strategy.shihunmacdrsibbup import shihunMacdRsiBollingerBandUp
from trader.strategy.shihunrsi2 import shihunRSI2
from trader.strategy.shihunmacd2 import shihunMACD2

NAME = "trader"

class App:
    def __init__(self):
        self.logger=Logger(NAME,logging.DEBUG)

    def name(self):
        return NAME

    def log(self):
        return self.logger.log()

    def start(self,strategyType,commission=0.001,atr=True,period=14):
        self.strategy=parseStrategyType(strategyType)
        self.commission=commission
        self.period=period
        self.atr=atr
        self.startTime=datetime.now()

        self.log().info(f"Start {self.name()} App, strategy type:{self.strategy.name} commission:{commission}")

        self.startStrategy()
        return True

    def stop(self):
        elapsed = datetime.now() - self.startTime
        self.log().info(f"Stop {self.name()} App, strategy type:{self.strategy.name}, elapsed time:{elapsed}")

    def version(self):
        filePath = os.path.join(path.GetTraderDir(), 'VERSION')

        with open(filePath, "r", encoding="utf-8") as file:
            content = file.read()
            return content
        return "None"

    def startStrategy(self):
        if self.strategy == StrategyType.ShihunMACD:
            shihunMACD(True, self.commission)

        elif self.strategy == StrategyType.ShihunRSI:
            shihunRSI(True, self.commission, self.atr)

        elif self.strategy == StrategyType.ShihunMACD2:
            shihunMACD2(True, self.commission, self.atr)

        elif self.strategy == StrategyType.ShihunRSI2:
            shihunRSI2(True, self.commission, self.atr)

        elif self.strategy == StrategyType.ShihunMACDRISBB:
            shihunMacdRsiBollingerBand(True, self.commission, self.atr)

        elif self.strategy == StrategyType.ShihunMACDRSIBBUP:
            shihunMacdRsiBollingerBandUp(True, self.commission, self.atr)