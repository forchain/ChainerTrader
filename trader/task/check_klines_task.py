import asyncio
from asyncio import Queue, Event
from datetime import datetime
from logging import Logger

from trader.app.database_manager import DatabaseManager
from trader.binance.exchange import BinanceExchange
from trader.common.config import Config
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import SymbolInterval, add_time_duration


class CheckKlinesTask(BaseTask):
    def __init__(self,tcfg:TaskConfig,cfg:Config,log:Logger,db_manager:DatabaseManager,exchange:BinanceExchange):
        super().__init__(tcfg,cfg,log,db_manager,exchange)

    async def start(self,queue:Queue,quit:Event):
        if not self.db_manager:
            self.log.error(f"No config db_uri for {self.tcfg.to_dict()}")
            return

        super().start(queue,quit)

        self.log.info(f"Start {self.name()}")
        collection = self.db_manager.get_collection(self.cfg.db_name, self.tcfg.symbol_interval.name())

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