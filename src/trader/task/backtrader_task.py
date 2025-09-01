from asyncio import Event
from datetime import datetime

from trader.common import path
from trader.common.common import MIN_RECORDS_NUM
from trader.common.config import Config
from trader.common.logger import Logger
from trader.common.message import new_stat_msg
from trader.database.manager import DatabaseManager
from trader.exchange.binance.csvdata import BinanceCSVData
from trader.exchange.binance.data import BinanceData
from trader.exchange.binance.exchange import BinanceExchange
from trader.statistics.stat import BackTraderStat
from trader.strategy.node import Node
from trader.strategy.strategy import parse_strategys
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig
from trader.task.update_klines_task import download
from trader.utils.symbol_interval import add_time_duration
from trader.utils.task_state import TaskState


class BackTraderTask(BaseTask):
    def __init__(
        self,
        tcfg: TaskConfig,
        cfg: Config,
        log: Logger,
        db_manager: DatabaseManager,
        exchange: BinanceExchange,
    ):
        super().__init__(tcfg, cfg, log, db_manager, exchange)

    async def start(self, queue):
        if not self.tcfg.csv and not self.db_manager:
            self.log.error(f"No config data_file or db for {self.tcfg.to_dict()}")
            return None
        if not self.tcfg.strategys:
            self.log.error(f"No config strategy for {self.tcfg.to_dict()}")
            return None

        super().start(queue)

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
            elif self.tcfg.end_time <= 0:
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
            collection = self.db_manager.kline.get_collection(self.tcfg.symbol_interval.name())
            kls_cache = self.db_manager.kline.get_klines(collection, self.tcfg.start_time, self.tcfg.end_time)
            if kls_cache is None or len(kls_cache) <= 0:
                if self.tcfg.auto_download:
                    if not self.exchange:
                        self.log.error(f"No exchange config for {self.name()}")
                        return None
                    if not await download(
                        self.name(),
                        self.log,
                        self.db_manager,
                        collection,
                        self.exchange,
                        self.tcfg.symbol_interval,
                        self.tcfg.start_time,
                        self.quit,
                    ):
                        self.log.error(f"Fail download for {self.name()}")
                        return None
                    kls_cache = self.db_manager.kline.get_klines(collection, self.tcfg.start_time, self.tcfg.end_time)

            if kls_cache is None or len(kls_cache) <= 0:
                self.log.error(f"No klines for {self.name()}")
                return None
            if len(kls_cache) < MIN_RECORDS_NUM:
                self.log.error(f"The current number of records {len(kls_cache)} is lower than the minimum number {MIN_RECORDS_NUM}")
                return None

            self.log.info(f"Create BinanceData({len(kls_cache)}) ")
            data = BinanceData(kls_cache)

        if data is None:
            self.log.error(f"No strategy data for {self.name()}")
            return None
        strategy = parse_strategys(self.tcfg.strategys)
        if strategy is None:
            self.log.error(f"Not support strategy:{self.tcfg.strategy_name()}")
            return None
        return [strategy, data]


def process_backtrader(parmas, result):
    cfg = parmas[0]
    data = parmas[1]
    strategy = parmas[2]
    tcfg = parmas[3]
    ts = parmas[4]
    db_manager = parmas[5]

    logger = Logger(cfg)

    logger.log().info(f"start do backtrader: {tcfg.id}")
    node = Node(tcfg.strategy_name(), strategy, tcfg.symbol_interval, cfg, logger.log(), data)
    ret = node.start()
    logger.log().info(f"end do backtrader: {tcfg.id}")
    if ret is None:
        return

    ts.tret = ret
    db_manager.task.add_tasks(ts)

    if ret.operate:
        next_time = add_time_duration(ret.operate.dtime, tcfg.symbol_interval.interval, 1)
        if next_time < int(datetime.now().timestamp()):
            ret.operate = None

    result.append(
        new_stat_msg(
            BackTraderStat(tcfg.strategy_name(), tcfg.symbol_interval.name(), ts),
            tcfg.id,
        )
    )
