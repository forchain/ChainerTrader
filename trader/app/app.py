import os
from datetime import datetime
from time import sleep

from mypyc.common import SELF_NAME

from trader.app.database_manager import DatabaseManager
from trader.app.task_manager import TaskManager
from trader.binance.exchange import EXCHANGE_NAME, BinanceExchange
from trader.common.config import Config
from trader.common.logger import Logger
from trader.common import path


NAME = "trader"

class App:
    def __init__(self):
        self.logger=Logger(NAME)
        self.log().info(f"Init App {self.name()}")
        self.running = False

    def name(self):
        return NAME

    def log(self):
        return self.logger.log()

    def start(self,cfg:Config):
        self.running=True

        self.cfg=cfg
        self.logger.setLevel(cfg.log_level)
        if cfg.log_file:
            self.logger.enableFile()

        self.startTime=datetime.now()

        self.log().info(f"Start {self.name()} App, config:{cfg.to_dict()}")

        if self.cfg.db_uri:
            self.db_manager=DatabaseManager(cfg,self.logger)
            self.db_manager.start()
        if self.cfg.exchange == EXCHANGE_NAME:
            self.exchange = BinanceExchange(self.cfg,self.log)
            self.exchange.start()

        self.task_manager = TaskManager(self)

        try:
            self.task_manager.start()
        except KeyboardInterrupt:
            self.shutdown()

        return True

    def stop(self):
        self.task_manager.stop()

        if self.db_manager:
            self.db_manager.stop()
        if self.exchange:
            self.exchange.stop()

        elapsed = datetime.now() - self.startTime
        self.log().info(f"Stop {self.name()} App, elapsed time:{elapsed}")

    def version(self):
        filePath = os.path.join(path.GetTraderDir(), 'VERSION')

        with open(filePath, "r", encoding="utf-8") as file:
            content = file.read()
            return content

    def info(self):
        return {
            "name":self.name(),
            "version":self.version(),
            "commission": self.cfg.commission,
            "period": self.cfg.period,
            "atr": self.cfg.atr,
        }

    def config(self):
        return self.cfg

    def shutdown(self):
        if not self.running:
            self.log().warn(f"{self.name()} already exited")
            return
        self.running=False
        self.log().info(f"Exit the {self.name()}")