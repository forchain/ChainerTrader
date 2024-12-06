import time
from datetime import datetime
from logging import Logger

from trader.app.database_manager import DatabaseManager
from trader.binance.data import BinanceData
from trader.binance.exchange import BinanceExchange
from trader.common.common import Context
from trader.common.config import Config
from trader.strategy.node import Node
from trader.strategy.strategy import parseStrategy
from trader.task.task_type import TaskType
from trader.utils.kline import Kline
from trader.utils.symbol_interval import SymbolInterval, add_time_duration

DOWLOAD_SPACE_TIME = 5

class TraderTask:
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
        return TaskType.TRADER

    def start(self):
        if self.cfg.strategy is None:
           self.log.error(f"No config strategy")
           return
        strategy = parseStrategy(self.cfg.strategy)
        if strategy is None:
            self.log.error(f"Not support strategy:{self.cfg.strategy}")
            return

        if self.exchange.spot_ws_client:
            self.exchange.spot_ws_client.klines(symbol=self.symbol_interval.symbol, interval=self.symbol_interval.interval.value, limit=1)

        self.log.info(f"Start {self.name()}")
        self.collection = self.db_manager.get_collection("trader", self.symbol_interval.name())

        while Context.running:
            if not self.download():
                return
            kls_cache = self.db_manager.get_latest_klines(self.collection, self.cfg.window)
            if len(kls_cache) <= 0:
                continue
            latest_kline = kls_cache[len(kls_cache) - 1]
            node = Node(strategy, self.cfg, self.log,BinanceData(kls_cache),kls_cache[0].open_datetime(),latest_kline.close_datetime())
            node.start()

            while Context.running:
                next_time = add_time_duration(latest_kline.open_time, self.symbol_interval.interval, 1)
                if next_time < int(datetime.now().timestamp()):
                     break
                else:
                    dist = next_time - int(datetime.now().timestamp())
                    dist +=1
                    self.sleep(dist,"next K-line...")



    def download(self):
        update_completed = False
        while not update_completed:
            if not Context.running:
                self.log.info(f"exit {self.name()}")
                return False

            latest_kline = self.db_manager.get_latest_kline(self.collection)
            if latest_kline is None:
                kls = self.exchange.get_klines_by_start(self.symbol_interval)
            else:
                next_time = add_time_duration(latest_kline.open_time, self.symbol_interval.interval, 1)
                if next_time < int(datetime.now().timestamp()):
                    kls = self.exchange.get_klines_by_start(self.symbol_interval, next_time)
                else:
                    update_completed = True
                    self.log.info(f"{self.name()} update local klines DB is completed")
                    continue
            if len(kls) <= 0:
                self.log.error(f"{self.name()} get klines is empty")
                self.sleep(DOWLOAD_SPACE_TIME)
                continue

            ret = self.db_manager.add_klines(self.collection, kls)
            if ret != len(kls):
                self.log.warning(f"{self.name()} add klines to DB: {ret} != {len(kls)}")
            else:
                self.log.info(f"{self.name()} add klines to DB: {ret}")

            self.sleep(DOWLOAD_SPACE_TIME)

        return True


    def stop(self):
        pass

    def sleep(self,seconds,msg=None):
        if msg:
            self.log.debug(f"Waiting for {seconds} seconds for {msg}")
        else:
            self.log.debug(f"Waiting for {seconds} seconds")
        time.sleep(seconds)