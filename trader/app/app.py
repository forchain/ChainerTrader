import os
from datetime import datetime
from time import sleep

from trader.app.task_manager import TaskManager
from trader.common.logger import Logger
from trader.common import path


NAME = "trader"

class App:
    def __init__(self):
        self.logger=Logger(NAME)
        self.log().info(f"Init App {self.name()}")

    def name(self):
        return NAME

    def log(self):
        return self.logger.log()

    def start(self,cfg):
        self.cfg=cfg
        self.logger.setLevel(cfg.log_level)
        if cfg.log_file:
            self.logger.enableFile()

        self.startTime=datetime.now()

        self.log().info(f"Start {self.name()} App, config:{cfg.to_dict()}")

        self.task_manager = TaskManager(cfg,self.log())
        self.task_manager.start()

        return True

    def stop(self):
        self.task_manager.stop()

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