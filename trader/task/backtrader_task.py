import os
from datetime import datetime
import datetime as dt

from trader.app.database_manager import DatabaseManager
from trader.binance.csvdata import BinanceCSVData
from trader.binance.data import BinanceData
from trader.binance.exchange import BinanceExchange
from trader.common import path
from trader.strategy.node import Node
from trader.strategy.strategy import StrategyType, parseStrategy
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import SymbolInterval
from asyncio import Queue, Event

class BackTraderTask(BaseTask):
    def __init__(self,tcfg:TaskConfig,cfg,log,db_manager:DatabaseManager,exchange:BinanceExchange):
        super().__init__(tcfg,cfg,log,db_manager,exchange)

    async def start(self,queue:Queue,quit:Event):
        super().start(queue,quit)

        data = None
        if self.tcfg.csv:
                data_file = self.tcfg.csv
                if not os.path.isabs(self.tcfg.csv):
                    data_file = os.path.join(path.GetDatasDir(),self.tcfg.csv)
                if self.tcfg.start_time <= 0 and self.tcfg.end_time <= 0:
                    data = BinanceCSVData(
                        dataname=data_file,
                    )
                elif self.tcfg.start_time <= 0:
                    data = BinanceCSVData(
                        dataname=data_file,
                        todate=datetime.fromtimestamp(self.tcfg.end_time),
                    )
                elif  self.tcfg.end_time <= 0:
                    data = BinanceCSVData(
                        dataname=data_file,
                        fromdate=datetime.fromtimestamp(self.tcfg.start_time),
                    )
                else:
                    data = BinanceCSVData(
                        dataname=data_file,
                        fromdate=datetime.fromtimestamp(self.tcfg.start_time),
                        todate=datetime.fromtimestamp(self.tcfg.end_time),
                    )
        if self.db_manager:
            collection = self.db_manager.get_collection("trader", self.tcfg.symbol_interval.name())
            if data is None:
                kls_cache = self.db_manager.get_all_klines(collection)
                if len(kls_cache) <= 0:
                    self.log.error(f"No klines for {self.name()}")
                    return
                self.log.info(f"Create BinanceData({len(kls_cache)}) ")
                data = BinanceData(kls_cache)

        if data is None:
            self.log.error(f"No strategy data for {self.name()}")
            return
        strategy = parseStrategy(self.tcfg.strategy)
        if strategy is None:
            self.log.error(f"Not support strategy:{self.tcfg.strategy}")
            return
        node = Node(strategy, self.cfg, self.log,data)
        node.start()

        self.stop()
