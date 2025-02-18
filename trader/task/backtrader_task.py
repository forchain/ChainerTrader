import os
from datetime import datetime
import datetime as dt

from trader.app.database_manager import DatabaseManager
from trader.binance.csvdata import BinanceCSVData
from trader.binance.data import BinanceData
from trader.binance.exchange import BinanceExchange
from trader.common import path
from trader.common.config import Config
from trader.common.logger import Logger
from trader.common.message import new_stat_msg
from trader.statistics.stat import BackTraderStat
from trader.statistics.statistics import Statistics
from trader.strategy.node import Node
from trader.strategy.strategy import StrategyType, parseStrategy
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from trader.task.update_klines_task import download
from trader.utils.symbol_interval import SymbolInterval, add_time_duration
from asyncio import Queue, Event

class BackTraderTask(BaseTask):
    def __init__(self,tcfg:TaskConfig,cfg:Config,log:Logger,db_manager:DatabaseManager,exchange:BinanceExchange):
        super().__init__(tcfg,cfg,log,db_manager,exchange)

    async def start(self,queue,quit:Event):
        if not self.tcfg.csv and not self.db_manager:
            self.log.error(f"No config data_file or db for {self.tcfg.to_dict()}")
            return None
        if not self.tcfg.strategy:
            self.log.error(f"No config strategy for {self.tcfg.to_dict()}")
            return None

        super().start(queue,quit)

        data = None
        if self.tcfg.csv:
                data_file = path.get_file_path(self.tcfg.csv)
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
        if self.db_manager and data is None:
            collection = self.db_manager.get_collection(self.cfg.db_name, self.tcfg.symbol_interval.name())
            kls_cache = self.db_manager.get_klines(collection,self.tcfg.start_time,self.tcfg.end_time)
            if kls_cache is None or len(kls_cache) <= 0:
                if self.tcfg.auto_download:
                    if not self.exchange:
                        self.log.error(f"No exchange config for {self.name()}")
                        return None
                    if not await download(self.name(), self.log, self.db_manager, collection, self.exchange,self.tcfg.symbol_interval, quit):
                        self.log.error(f"Fail download for {self.name()}")
                        return None
                    kls_cache = self.db_manager.get_klines(collection, self.tcfg.start_time, self.tcfg.end_time)

            if kls_cache is None or len(kls_cache) <= 0:
                self.log.error(f"No klines for {self.name()}")
                return None
            self.log.info(f"Create BinanceData({len(kls_cache)}) ")
            data = BinanceData(kls_cache)

        if data is None:
            self.log.error(f"No strategy data for {self.name()}")
            return None
        strategy = parseStrategy(self.tcfg.strategy)
        if strategy is None:
            self.log.error(f"Not support strategy:{self.tcfg.strategy}")
            return None
        return [strategy,data]

def process_backtrader(parmas,result):
    cfg = parmas[0]
    data = parmas[1]
    strategy = parmas[2]
    tcfg = parmas[3]
    logger = Logger(cfg)

    logger.log().info(f"start do backtrader: {tcfg.id}")
    node = Node(tcfg.strategy.name,strategy, cfg, logger.log(), data)
    ret = node.start()
    logger.log().info(f"end do backtrader: {tcfg.id}")
    if ret.operate:
        next_time = add_time_duration(ret.operate.dtime, tcfg.symbol_interval.interval, 1)
        if next_time < int(datetime.now().timestamp()):
            ret.operate=None
        else:
            ret.operate.symbol_interval=tcfg.symbol_interval
    result.append(new_stat_msg(BackTraderStat(tcfg.strategy.name, tcfg.symbol_interval.name(), ret), tcfg.id))
