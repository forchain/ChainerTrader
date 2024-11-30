import time
from datetime import datetime
from logging import Logger

from trader.app.database_manager import DatabaseManager
from trader.binance.exchange import BinanceExchange
from trader.common.common import Context
from trader.common.config import Config
from trader.utils.symbol_interval import SymbolInterval, add_time_duration

DOWLOAD_SPACE_TIME = 25

class DynamicTask:
    def __init__(self,cfg:Config,log:Logger,db_manager:DatabaseManager,exchange:BinanceExchange):
        self.log = log
        self.cfg = cfg
        self.db_manager = db_manager
        self.exchange = exchange
        self.symbol_interval:SymbolInterval=self.cfg.get_symbol_interval_list()[0]
        self.log.info(f"Init {self.name()}")

    def name(self):
        return f"DynamicTask({self.symbol_interval.name()})"

    def start(self):
        self.log.info(f"Start {self.name()}")
        self.collection = self.db_manager.get_collection("trader", self.symbol_interval.name())

        update_completed = False
        while not update_completed:
            if not Context.running:
                self.log.info(f"exit {self.name()}")
                return

            latest_kline = self.db_manager.get_latest_kline(self.collection)
            if latest_kline is None:
                kls = self.exchange.get_klines_by_start(self.symbol_interval)
            else:
                next_time = add_time_duration(latest_kline.open_time,self.symbol_interval.interval,1)
                if next_time < int(datetime.now().timestamp()):
                    kls = self.exchange.get_klines_by_start(self.symbol_interval,next_time)
                else:
                    update_completed=True
                    self.log.info(f"{self.name()} update local klines DB is completed")
                    continue
            if len(kls) <= 0:
                self.log.error(f"{self.name()} get klines is empty")
                time.sleep(DOWLOAD_SPACE_TIME)
                continue

            ret = self.db_manager.add_klines(self.collection,kls)
            if ret != len(kls):
                self.log.warning(f"{self.name()} add klines to DB: {ret} != {len(kls)}")
            else:
                self.log.info(f"{self.name()} add klines to DB: {ret}")

            time.sleep(DOWLOAD_SPACE_TIME)



    def stop(self):
        pass