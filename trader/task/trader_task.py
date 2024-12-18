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
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from trader.task.update_klines_task import download
from trader.utils.kline import Kline
from trader.utils.symbol_interval import SymbolInterval, add_time_duration
from asyncio import Queue, Event


DOWLOAD_SPACE_TIME = 5

class TraderTask:
    def __init__(self,tcfg:TaskConfig,cfg:Config,log:Logger,db_manager:DatabaseManager,exchange:BinanceExchange):
        self.log = log
        self.cfg = cfg
        self.tcfg = tcfg
        self.db_manager = db_manager
        self.exchange = exchange
        self.symbol_interval:SymbolInterval=tcfg.symbol_interval
        self.log.info(f"Init {self.name()}")

    def name(self):
        return f"{self.type()}({self.symbol_interval.name()})"

    def type(self):
        return TaskType.TRADER

    async def start(self,queue:Queue,quit:Event):
        if self.tcfg.strategy is None:
           self.log.error(f"No config strategy")
           return
        strategy = parseStrategy(self.tcfg.strategy)
        if strategy is None:
            self.log.error(f"Not support strategy:{self.tcfg.strategy}")
            return

        #if self.exchange.spot_ws_client:
        #    self.exchange.spot_ws_client.klines(symbol=self.symbol_interval.symbol, interval=self.symbol_interval.interval.value, limit=1)

        self.log.info(f"Start {self.name()}")
        self.start_time = datetime.now()
        self.collection = self.db_manager.get_collection("trader", self.symbol_interval.name())

        while Context.running:
            if not download(self.name(),self.log,self.db_manager,self.collection,self.exchange,self.symbol_interval,quit):
               break

            kls_cache = self.db_manager.get_latest_klines(self.collection, self.cfg.window)
            if len(kls_cache) <= 0:
                continue
            latest_kline = kls_cache[len(kls_cache) - 1]
            node = Node(strategy, self.cfg, self.log,BinanceData(kls_cache))
            node.start()

            while Context.running:
                next_time = add_time_duration(latest_kline.open_time, self.symbol_interval.interval, 1)
                if next_time < int(datetime.now().timestamp()):
                     break
                else:
                    dist = next_time - int(datetime.now().timestamp())
                    dist +=1
                    self.sleep(dist,"next K-line...")

        self.stop()

    def stop(self):
        elapsed = datetime.now() - self.start_time
        self.log.info(f"Stop {self.name()}, elapsed time:{elapsed}")

    def sleep(self,seconds,msg=None):
        if msg:
            self.log.debug(f"Waiting for {seconds} seconds for {msg}")
        else:
            self.log.debug(f"Waiting for {seconds} seconds")
        time.sleep(seconds)