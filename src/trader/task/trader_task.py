from asyncio import Queue
from datetime import datetime
from trader.common.logger import Logger

from trader.common.common import MIN_RECORDS_NUM, sleep, sleep_loop
from trader.common.config import Config
from trader.common.message import new_stat_msg
from trader.database.manager import DatabaseManager
from trader.exchange.binance.data import BinanceData
from trader.exchange.binance.exchange import BinanceExchange
from trader.statistics.stat import TraderStat
from trader.strategy.node import Node
from trader.strategy.strategy import parse_strategys
from trader.strategy.trader_result import TraderResult
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig
from trader.task.update_klines_task import download
from trader.utils.operate import OperateType
from trader.utils.symbol_interval import add_time_duration

DOWLOAD_SPACE_TIME = 5


class TraderTask(BaseTask):
    def __init__(
        self,
        tcfg: TaskConfig,
        cfg: Config,
        log: Logger,
        db_manager: DatabaseManager,
        exchange: BinanceExchange,
    ):
        super().__init__(tcfg, cfg, log, db_manager, exchange)

    async def start(self, queue: Queue):
        if not self.tcfg.strategys:
            self.log.error(f"No config strategy for {self.tcfg.to_dict()}")
            return
        if not self.exchange:
            self.log.error(f"No config exchange for {self.tcfg.to_dict()}")
            return
        if not self.db_manager:
            self.log.error(f"No config db_uri for {self.tcfg.to_dict()}")
            return

        super().start(queue)

        strategy = parse_strategys(self.tcfg.strategys)
        if strategy is None:
            self.log.error(f"Not support strategy:{self.tcfg.strategy_name()}")
            return

        # if self.exchange.spot_ws_client:
        #    self.exchange.spot_ws_client.klines(symbol=self.symbol_interval.symbol, interval=self.symbol_interval.interval.value, limit=1)

        self.collection = self.db_manager.kline.get_collection(self.tcfg.symbol_interval.name())

        commission = self.exchange.get_account_commission(self.tcfg.symbol_interval.symbol)
        if commission:
            self.cfg.commission = commission
            self.log.info(f"set commission for trader task config:{self.cfg.commission}")

        while not self.quit.is_set():
            ret = await download(
                self.name(),
                self.log,
                self.db_manager,
                self.collection,
                self.exchange,
                self.tcfg.symbol_interval,
                self.tcfg.start_time,
                self.quit,
            )
            if not ret:
                break

            kls_cache = self.db_manager.kline.get_latest_klines(self.collection, self.cfg.window)
            if len(kls_cache) <= MIN_RECORDS_NUM:
                await sleep(self.log, 2, "Try again...")
                continue
            latest_kline = kls_cache[len(kls_cache) - 1]

            position = self.exchange.get_account_balance(self.tcfg.symbol_interval.sy.base)

            node = Node(self.tcfg.strategy_name(), strategy, self.tcfg.symbol_interval, self.cfg, self.log, BinanceData(kls_cache), position, True)
            ret = node.start()
            if ret is None:
                continue

            self.process_result(ret)

            self.operate_exchange(ret)

            await queue.put(
                new_stat_msg(
                    TraderStat(self.tcfg.strategy_name(), self.tcfg.symbol_interval.name(), self.ts),
                    self.tcfg.id,
                )
            )

            while not self.quit.is_set():
                next_time = add_time_duration(latest_kline.open_time, self.tcfg.symbol_interval.interval, 1)
                if next_time < int(datetime.now().timestamp()):
                    break
                else:
                    dist = next_time - int(datetime.now().timestamp())
                    dist += 1
                    await sleep_loop(self.log, dist, self.quit, "next K-line...")

    def process_result(self, ret: TraderResult):
        last_task = self.db_manager.task.get_task(self.tcfg.id)
        if last_task and last_task.tret:
            ret.opts.append(last_task.tret.opts)

        self.ts.tret = ret
        self.db_manager.task.add_tasks([self.ts])

    def operate_exchange(self, ret: TraderResult):
        if ret.opts:
            op = ret.opts[-1]
            if op.otype == OperateType.BUY:
                cash = self.exchange.get_account_balance(self.tcfg.symbol_interval.sy.quote)
                free = cash - self.cfg.locked
                if free > 0:
                    self.exchange.new_order(self.tcfg.symbol_interval.symbol(), op.otype)
                else:
                    self.log.info(f"Due to insufficient balance, we have given up placing orders with the exchange")
            else:
                self.exchange.new_order(self.tcfg.symbol_interval.symbol(), op.otype)
