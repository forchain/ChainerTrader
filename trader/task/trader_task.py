import time
from datetime import datetime
from logging import Logger

from trader.app.database_manager import DatabaseManager
from trader.binance.data import BinanceData
from trader.binance.exchange import BinanceExchange
from trader.common.common import Context, sleep
from trader.common.config import Config
from trader.common.message import new_stat_msg
from trader.statistics.stat import BackTraderStat, TraderStat
from trader.strategy.node import Node
from trader.strategy.strategy import parseStrategy, parse_strategys
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from trader.task.update_klines_task import download
from trader.utils.kline import Kline
from trader.utils.symbol_interval import SymbolInterval, add_time_duration
from asyncio import Queue, Event


DOWLOAD_SPACE_TIME = 5

class TraderTask(BaseTask):
    def __init__(self,tcfg:TaskConfig,cfg:Config,log:Logger,db_manager:DatabaseManager,exchange:BinanceExchange):
        super().__init__(tcfg, cfg, log, db_manager, exchange)

    async def start(self,queue:Queue,quit:Event):
        if not self.tcfg.strategys:
            self.log.error(f"No config strategy for {self.tcfg.to_dict()}")
            return
        if not self.exchange:
            self.log.error(f"No config exchange for {self.tcfg.to_dict()}")
            return
        if not self.db_manager:
            self.log.error(f"No config db_uri for {self.tcfg.to_dict()}")
            return

        super().start(queue, quit)

        strategy = parse_strategys(self.tcfg.strategys)
        if strategy is None:
            self.log.error(f"Not support strategy:{self.tcfg.strategy_name()}")
            return

        #if self.exchange.spot_ws_client:
        #    self.exchange.spot_ws_client.klines(symbol=self.symbol_interval.symbol, interval=self.symbol_interval.interval.value, limit=1)

        self.collection = self.db_manager.get_collection(self.cfg.db_name, self.tcfg.symbol_interval.name())

        while Context.running:
            ret = await download(self.name(),self.log,self.db_manager,self.collection,self.exchange,self.tcfg.symbol_interval,quit)
            if not ret:
               break

            kls_cache = self.db_manager.get_latest_klines(self.collection, self.cfg.window)
            if len(kls_cache) <= 0:
                continue
            latest_kline = kls_cache[len(kls_cache) - 1]
            node = Node(self.tcfg.strategy_name(),strategy, self.cfg, self.log,BinanceData(kls_cache))
            ret=node.start()
            await queue.put(new_stat_msg(TraderStat(self.tcfg.strategy_name(), self.tcfg.symbol_interval.name(), ret),self.tcfg.id))

            while Context.running:
                next_time = add_time_duration(latest_kline.open_time, self.tcfg.symbol_interval.interval, 1)
                if next_time < int(datetime.now().timestamp()):
                     break
                else:
                    dist = next_time - int(datetime.now().timestamp())
                    dist +=1
                    await sleep(self.log,dist,"next K-line...")

        self.stop()