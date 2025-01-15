import asyncio
from datetime import datetime
from logging import Logger

from pymongo.synchronous.collection import Collection

from trader.app.database_manager import DatabaseManager
from trader.binance.exchange import BinanceExchange
from trader.common.common import Context, sleep
from trader.common.config import Config
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import SymbolInterval, add_time_duration
from asyncio import Queue, Event

DOWLOAD_SPACE_TIME = 5

class UpdateKlinesTask(BaseTask):
    def __init__(self,tcfg:TaskConfig,cfg:Config,log:Logger,db_manager:DatabaseManager,exchange:BinanceExchange):
        super().__init__(tcfg, cfg, log, db_manager, exchange)


    async def start(self,queue:Queue,quit:Event):
        if not self.exchange:
            self.log.error(f"No config exchange for {self.tcfg.to_dict()}")
            return
        if not self.db_manager:
            self.log.error(f"No config db_uri for {self.tcfg.to_dict()}")
            return

        super().start(queue,quit)

        self.collection = self.db_manager.get_collection(self.cfg.db_name, self.tcfg.symbol_interval.name())

        await download(self.name(),self.log,self.db_manager,self.collection,self.exchange,self.tcfg.symbol_interval,quit)

        self.stop()

async def download(name,log:Logger,db_manager:DatabaseManager,collection:Collection,exchange:BinanceExchange,symbol_interval:SymbolInterval,quit:Event):
    update_completed = False
    max_try = 5
    while not update_completed:
        if quit.is_set():
            log.info(f"exit {name}")
            return False

        latest_kline = db_manager.get_latest_kline(collection)
        if latest_kline is None:
            kls = exchange.get_klines_by_start(symbol_interval)
        else:
            next_time = add_time_duration(latest_kline.open_time, symbol_interval.interval, 1)
            if next_time < int(datetime.now().timestamp()):
                kls = exchange.get_klines_by_start(symbol_interval, next_time)
            else:
                update_completed = True
                log.info(f"{name} update klines to DB is completed")
                continue
        if len(kls) <= 0:
            log.error(f"{name} get klines is empty")
            if max_try > 0:
                await sleep(log, DOWLOAD_SPACE_TIME, f"next try {max_try}, {name}")
                max_try -= 1
                continue
            else:
                log.warning(f"exit {name}, because get empty klines")
                return False


        ret = db_manager.add_klines(collection, kls)
        if ret != len(kls):
            log.warning(f"{name} add klines to DB: {ret} != {len(kls)}")
        else:
            log.info(f"{name} add klines to DB: {ret}")

        #await sleep(log,DOWLOAD_SPACE_TIME,name)

    return True


async def download_test(name,log:Logger,db_manager:DatabaseManager,collection:Collection,exchange:BinanceExchange,symbol_interval:SymbolInterval,quit:Event):
    update_completed = False
    while not update_completed:
        if quit.is_set():
            log.info(f"exit {name}")
            return False

        await sleep(log,DOWLOAD_SPACE_TIME,name)

    return True