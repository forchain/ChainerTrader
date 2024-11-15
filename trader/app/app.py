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

        if self.cfg.strategy is None:
            self.log().info(f"Start {self.name()} App, commission:{cfg.commission}")
        else:
            self.log().info(f"Start {self.name()} App, strategy type:{cfg.strategy.name} commission:{cfg.commission}")
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
        if self.cfg.strategy == StrategyType.ShihunMACD:
            shihunMACD(True, self.cfg.commission)

        elif self.cfg.strategy == StrategyType.ShihunRSI:
            shihunRSI(True, self.cfg.commission, self.cfg.atr)

        elif self.cfg.strategy == StrategyType.ShihunMACD2:
            shihunMACD2(True, self.cfg.commission, self.cfg.atr)

        elif self.cfg.strategy == StrategyType.ShihunRSI2:
            shihunRSI2(True, self.cfg.commission, self.cfg.atr)

        elif self.cfg.strategy == StrategyType.ShihunMACDRISBB:
            shihunMacdRsiBollingerBand(True, self.cfg.commission, self.cfg.atr)

        elif self.cfg.strategy == StrategyType.ShihunMACDRSIBBUP:
            shihunMacdRsiBollingerBandUp(True, self.cfg.commission, self.cfg.atr)

    def info(self):
        return {
            "name":self.name(),
            "version":self.version(),
            "commission": self.cfg.commission,
            "period": self.cfg.period,
            "atr": self.cfg.atr,
        }