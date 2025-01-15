import asyncio
from asyncio import Queue, Event
from datetime import datetime
from logging import Logger

from trader.app.database_manager import DatabaseManager
from trader.binance.exchange import BinanceExchange
from trader.common.config import Config
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType


class BaseTask:
    def __init__(self,tcfg:TaskConfig,cfg:Config,log:Logger,db_manager:DatabaseManager,exchange:BinanceExchange):
        self.log = log
        self.cfg = cfg
        self.db_manager = db_manager
        self.exchange = exchange
        self.tcfg = tcfg
        self.log.info(f"Init {self.name()}")
        self.start_time= datetime.now()

    def start(self,queue:Queue,quit:Event):
        self.start_time = datetime.now()
        self.log.info(f"Start {self.name()}")

    def stop(self):
        elapsed = datetime.now() - self.start_time
        self.log.info(f"Stop {self.name()}, elapsed time:{elapsed}")

    def name(self):
        return f"{self.tcfg.id}.{self.type().name}.{self.tcfg.symbol_interval.name()}"

    def type(self):
        return self.tcfg.ttype