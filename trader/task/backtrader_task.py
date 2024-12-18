import os
from datetime import datetime
import datetime as dt

from trader.app.database_manager import DatabaseManager
from trader.binance.csvdata import BinanceCSVData
from trader.binance.data import BinanceData
from trader.common import path
from trader.strategy.node import Node
from trader.strategy.strategy import StrategyType, parseStrategy
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import SymbolInterval
from asyncio import Queue, Event

class BackTraderTask:
    def __init__(self,tcfg:TaskConfig,cfg,log,db_manager:DatabaseManager):
        self.log = log
        self.cfg=cfg
        self.tcfg = tcfg
        self.db_manager = db_manager
        self.log.info(f"Init {self.name()}")

    async def start(self,queue:Queue,quit:Event):
        self.start_time = datetime.now()
        data = None
        if self.cfg.data_file:
                datafile = self.cfg.data_file
                if not os.path.isabs(self.cfg.data_file):
                    datafile = os.path.join(path.GetDatasDir(), self.cfg.data_file)
                if self.tcfg.start_time <= 0 and self.tcfg.end_time <= 0:
                    data = BinanceCSVData(
                        dataname=datafile,
                    )
                elif self.tcfg.start_time <= 0:
                    data = BinanceCSVData(
                        dataname=datafile,
                        todate=datetime.fromtimestamp(self.tcfg.end_time),
                    )
                elif  self.tcfg.end_time <= 0:
                    data = BinanceCSVData(
                        dataname=datafile,
                        fromdate=datetime.fromtimestamp(self.tcfg.start_time),
                    )
                else:
                    data = BinanceCSVData(
                        dataname=datafile,
                        fromdate=datetime.fromtimestamp(self.tcfg.start_time),
                        todate=datetime.fromtimestamp(self.tcfg.end_time),
                    )
        if self.db_manager:
            collection = self.db_manager.get_collection("trader", self.tcfg.symbol_interval.name())
            if data is None:
                kls_cache = self.db_manager.get_latest_klines(collection, self.cfg.window)
                if len(kls_cache) <= 0:
                    self.log.error(f"No klines for {self.name()}")
                    return
                data = BinanceData(kls_cache)

        if data is None:
            self.log.error(f"No strategy data for {self.name()}")
            return
        strategy = parseStrategy(self.cfg.strategy)
        node = Node(strategy, self.cfg, self.log,data)
        node.start()

        self.stop()

    def stop(self):
        elapsed = datetime.now() - self.start_time
        self.log.info(f"Stop {self.name()}, elapsed time:{elapsed}")

    def name(self):
        return f"{self.type()}({self.tcfg.symbol_interval.name()})"

    def type(self):
        return TaskType.BACK_TRADER