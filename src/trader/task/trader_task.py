from asyncio import Queue
from datetime import datetime

from trader.common.common import MIN_RECORDS_NUM, sleep, sleep_loop
from trader.common.config import Config
from trader.common.logger import Logger
from trader.common.message import new_stat_msg
from trader.database.manager import DatabaseManager
from trader.exchange.binance.data import BinanceData
from trader.exchange.binance.exchange import BinanceExchange
from trader.statistics.stat import TraderStat
from trader.strategy.node import Node
from trader.strategy.strategy import parse_strategies
from trader.strategy.trader_result import TraderResult
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig
from trader.task.update_klines_task import download_range
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
        if not self.tcfg.strategies:
            self.log.error(f"No config strategy for {self.tcfg.to_dict()}")
            return
        if not self.exchange:
            self.log.error(f"No config exchange for {self.tcfg.to_dict()}")
            return
        if not self.db_manager:
            self.log.error(f"No config db_uri for {self.tcfg.to_dict()}")
            return

        super().start(queue)

        strategy = parse_strategies(self.tcfg.strategies)
        if strategy is None:
            self.log.error(f"Not support strategy:{self.tcfg.strategy_name()}")
            return

        # if self.exchange.spot_ws_client:
        #    self.exchange.spot_ws_client.klines(symbol=self.symbol_interval.symbol, interval=self.symbol_interval.interval.value, limit=1)

        self.collection = self.db_manager.kline.get_collection(self.tcfg.symbol_interval.name())

        commission = self.exchange.get_account_commission(self.tcfg.symbol_interval.symbol())
        if commission:
            self.cfg.commission = commission
            self.log.info(f"set commission for trader task config:{self.cfg.commission}")
            self.ts.commission = commission

        collection_name = self.tcfg.symbol_interval.name()
        while not self.quit.is_set():
            end_time = int(datetime.now().timestamp())
            ret = await download_range(
                self.name(),
                self.log,
                self.db_manager,
                collection_name,
                self.exchange,
                self.tcfg.symbol_interval,
                self.tcfg.start_time,
                end_time,
                self.quit,
            )
            if not ret:
                break

            kls_cache = self.db_manager.kline.get_latest_klines(self.tcfg.symbol_interval.name(), self.cfg.window)
            if len(kls_cache) <= MIN_RECORDS_NUM:
                await sleep(self.log, 2, "Try again...")
                continue
            latest_kline = kls_cache[len(kls_cache) - 1]

            position = self.exchange.get_account_balance(self.tcfg.symbol_interval.sy.base)

            node = Node(
                self.tcfg.strategy_name(),
                strategy,
                self.tcfg.symbol_interval,
                self.cfg,
                self.log,
                BinanceData(kls_cache),
                position,
                True,
                self.tcfg.free,
            )
            ret = node.start()
            if ret is None:
                continue

            self.process_result(ret)

            self.operate_exchange(ret, position)

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

    def operate_exchange(self, ret: TraderResult, position: float):
        if not ret.opts:
            return

        op = ret.opts[-1]
        symbol = self.tcfg.symbol_interval.sy

        if not op.price or op.price <= 0:
            self.log.warning(f"Skip order due to invalid price: symbol={symbol.name()} operateType={op.otype} price={op.price}")
            return

        trade_quantity = self.tcfg.free / op.price
        if trade_quantity <= 0:
            self.log.warning(f"Skip order due to invalid quantity: symbol={symbol.name()} operateType={op.otype} quantity={trade_quantity}")
            return

        if op.otype in (OperateType.BUY, OperateType.LONG):
            cash = self.exchange.get_account_balance(symbol.quote)
            if getattr(self.exchange, "margin_mode", None) is not None and self.exchange.margin_mode.name != "SPOT":
                cash_ok = True
            else:
                cash_ok = self.tcfg.free <= cash

            if not cash_ok:
                self.log.info("Due to insufficient balance, we have given up placing orders with the exchange")
                return

            self.log.info(f"New order:symbol={symbol.name()},operateType={op.otype},quantity={trade_quantity}")
            self.exchange.new_order(symbol, op.otype, trade_quantity)
            return

        if op.otype == OperateType.SHORT:
            if getattr(self.exchange, "margin_mode", None) is not None and self.exchange.margin_mode.name == "SPOT":
                self.log.warning(f"Skip SHORT order in SPOT mode: symbol={symbol.name()}")
                return
            self.log.info(f"New order:symbol={symbol.name()},operateType={op.otype},quantity={trade_quantity}")
            self.exchange.new_order(symbol, op.otype, trade_quantity)
            return

        if op.otype == OperateType.SELL:
            if position <= 0:
                self.log.info(f"Skip SELL due to empty position: symbol={symbol.name()} position={position}")
                return
            self.log.info(f"New order:symbol={symbol.name()},operateType={op.otype},quantity={position}")
            self.exchange.new_order(symbol, op.otype, position)
            return

        if op.otype == OperateType.CLOSE:
            if position > 0:
                self.log.info(f"New order:symbol={symbol.name()},operateType={op.otype},quantity={position}")
                self.exchange.new_order(symbol, OperateType.SELL, position)
            else:
                self.log.warning(f"Skip CLOSE due to unknown short position size: symbol={symbol.name()} position={position}")
            return

        self.log.warning(f"Skip unsupported operateType: symbol={symbol.name()} operateType={op.otype}")
