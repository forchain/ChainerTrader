import asyncio
from asyncio import Queue, Event
from datetime import datetime
from logging import Logger

from trader.app.database_manager import DatabaseManager
from trader.binance.exchange import BinanceExchange
from trader.common.config import Config
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import SymbolInterval, add_time_duration


class CheckKlinesTask:
    def __init__(self,tcfg:TaskConfig,cfg:Config,log:Logger,db_manager:DatabaseManager):
        self.log = log
        self.cfg = cfg
        self.db_manager = db_manager
        self.tcfg = tcfg
        self.log.info(f"Init {self.name()}")

    async def start(self,queue:Queue,quit:Event):
        self.start_time = datetime.now()

        self.log.info(f"Start {self.name()}")
        collection = self.db_manager.get_collection("trader", self.tcfg.symbol_interval.name())

        first_kl = self.db_manager.get_first_kline(collection)
        if first_kl is None:
            self.log.error(f"{self.name()} can't find first kline")
            return

        latest_kl = self.db_manager.get_latest_kline(collection)
        if latest_kl is None:
            self.log.error(f"{self.name()} can't find latest kline")
            return
        if first_kl.key() == latest_kl.key():
            self.log.error(f"{self.name()} no need check")
            return

        count = 0
        total = 0
        next_time = first_kl.open_time
        while True:
            if quit.is_set():
                break
            total +=1
            next_time = add_time_duration(next_time, self.tcfg.symbol_interval.interval, 1)
            if next_time < latest_kl.open_time:
               kl = self.db_manager.get_kline(collection,next_time)
               if kl is None:
                   count +=1
                   self.log.warning(f"{self.name()} no kline: open_time={next_time}")
            else:
               self.log.info(f"{self.name()} is completed")
               break

        self.log.info(f"{self.name()} process result:{count}/{total}")
        self.stop()


    def stop(self):
        elapsed = datetime.now() - self.start_time
        self.log.info(f"Stop {self.name()}, elapsed time:{elapsed}")

    def name(self):
        return f"{self.type()}({self.tcfg.symbol_interval.name()})"

    def type(self):
        return TaskType.CHECK_KLINES