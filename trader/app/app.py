import os
from datetime import datetime
from math import trunc

from trader.app.database_manager import DatabaseManager
from trader.task.task_manager import TaskManager
from trader.binance.exchange import EXCHANGE_NAME, BinanceExchange
from trader.common.common import Context, sleep
from trader.common.config import Config, default
from trader.common.logger import Logger
from trader.common import path


NAME = "trader"

class App:
    def __init__(self,cfg:Config=default()):
        self.cfg = cfg
        self.logger=Logger(NAME)
        self.logger.setLevel(cfg.log_level)
        if cfg.log_file:
            self.logger.enableFile()
        self.logger.resetRoot()

        self.log().info(f"Init App {self.name()}")

        self.db_manager=None
        self.exchange=None

        if self.cfg.db_uri:
            self.db_manager = DatabaseManager(cfg, self.logger)
        if self.cfg.exchange == EXCHANGE_NAME:
            self.exchange = BinanceExchange(self.cfg, self.log())

        self.task_manager=None
        if self.cfg.task:
            self.task_manager = TaskManager(self.cfg, self.log(), self.db_manager, self.exchange)

        Context.running=False
        self.startTime = datetime.now()

    def name(self):
        return NAME

    def log(self):
        return self.logger.log()

    def start(self):
        if self.cfg.task is None:
            self.log().warn(f"No tasks can be executed")
            sleep(self.log(),5,"测试")
            return True

        Context.running=True

        self.log().info(f"Start {self.name()} App, config:{self.cfg.to_dict()}")

        if self.db_manager:
            self.db_manager.start()
        if  self.exchange:
            self.exchange.start()

        if self.task_manager:
            self.task_manager = TaskManager(self.cfg,self.log(),self.db_manager,self.exchange)

            try:
                self.task_manager.start()
            except KeyboardInterrupt:
                self.shutdown()

        return True

    def stop(self):
        Context.running = False

        if self.task_manager:
            self.task_manager.stop()

        if self.db_manager:
            self.db_manager.stop()
        if self.exchange:
            self.exchange.stop()

        elapsed = datetime.now() - self.startTime
        self.log().info(f"Stop {self.name()} App, elapsed time:{elapsed}")

    def version(self):
        return version()

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
        if not Context.running:
            self.log().warn(f"{self.name()} already exited")
            return
        Context.running=False
        self.log().info(f"Exit the {self.name()}")

def version():
    filePath = os.path.join(path.GetTraderDir(), 'VERSION')

    with open(filePath, "r", encoding="utf-8") as file:
        content = file.read()
        return content