from datetime import datetime
from logging import Logger

from pymongo.synchronous.collection import Collection

from trader.app.database_manager import DatabaseManager
from trader.binance.exchange import BinanceExchange
from trader.common.common import Context, sleep
from trader.common.config import Config
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import SymbolInterval, add_time_duration

DOWLOAD_SPACE_TIME = 5

class UpdateKlinesTask:
    def __init__(self,cfg:Config,log:Logger,db_manager:DatabaseManager,exchange:BinanceExchange):
        self.log = log
        self.cfg = cfg
        self.db_manager = db_manager
        self.exchange = exchange
        self.symbol_interval:SymbolInterval=self.cfg.get_symbol_interval_list()[0]
        self.log.info(f"Init {self.name()}")

    def name(self):
        return f"{self.type()}({self.symbol_interval.name()})"

    def type(self):
        return TaskType.UPDATE_KLINES

    def start(self):
        self.start_time = datetime.now()

        self.log.info(f"Start {self.name()}")
        self.collection = self.db_manager.get_collection("trader", self.symbol_interval.name())

        download(self.name(),self.log,self.db_manager,self.collection,self.exchange,self.symbol_interval)

    def stop(self):
        elapsed = datetime.now() - self.start_time
        self.log.info(f"Stop {self.name()}, elapsed time:{elapsed}")



def download(name,log:Logger,db_manager:DatabaseManager,collection:Collection,exchange:BinanceExchange,symbol_interval:SymbolInterval):
    update_completed = False
    while not update_completed:
        if not Context.running:
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
            sleep(log,DOWLOAD_SPACE_TIME)
            continue

        ret = db_manager.add_klines(collection, kls)
        if ret != len(kls):
            log.warning(f"{name} add klines to DB: {ret} != {len(kls)}")
        else:
            log.info(f"{name} add klines to DB: {ret}")

        sleep(log,DOWLOAD_SPACE_TIME)

    return True