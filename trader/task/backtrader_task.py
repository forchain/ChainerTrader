import os
from datetime import datetime
import datetime as dt

from trader.app.database_manager import DatabaseManager
from trader.binance.csvdata import BinanceCSVData
from trader.binance.data import BinanceData
from trader.binance.exchange import BinanceExchange
from trader.common import path
from trader.common.logger import Logger
from trader.common.message import new_stat_msg
from trader.statistics.stat import BackTraderStat
from trader.statistics.statistics import Statistics
from trader.strategy.node import Node
from trader.strategy.strategy import StrategyType, parseStrategy
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import SymbolInterval
from asyncio import Queue, Event

class BackTraderTask(BaseTask):
    def __init__(self,tcfg:TaskConfig,cfg,log,db_manager:DatabaseManager,exchange:BinanceExchange):
        logger = Logger(cfg)
        plog=logger.log()
        super().__init__(tcfg,cfg,plog,db_manager,exchange)

    def start(self,queue,quit:Event):
        if not self.tcfg.csv and not self.db_manager:
            self.log.error(f"No config data_file or db_uri for {self.tcfg.to_dict()}")
            return
        if not self.tcfg.strategy:
            self.log.error(f"No config strategy for {self.tcfg.to_dict()}")
            return

        super().start(None,quit)

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
        total_return_rate = node.start()
        queue.append(new_stat_msg(BackTraderStat(self.tcfg.strategy,self.tcfg.symbol_interval.name(),total_return_rate),self.tcfg.id))
        self.stop()
