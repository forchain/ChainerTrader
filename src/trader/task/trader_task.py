from asyncio import Queue
from datetime import datetime

from trader.common.common import MIN_RECORDS_NUM, sleep, sleep_loop
from trader.common.config import Config
from trader.common.logger import Logger
from trader.common.message import new_stat_msg
from trader.database.manager import DatabaseManager
from trader.exchange.binance.data import BinanceData
from trader.exchange.binance.exchange import BinanceExchange
from trader.notify.trade_notification import (
    MANUAL_NOTIFY_MODE,
    ManualTradeAccountState,
    ManualTradeNotificationEvent,
    normalize_live_execution_mode,
)
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
        self._manual_cash = self._manual_starting_cash()
        self._manual_position = float(getattr(tcfg, "manual_start_position", 0.0) or 0.0)

    def is_manual_notify_mode(self) -> bool:
        return normalize_live_execution_mode(getattr(self.tcfg, "live_execution_mode", None)) == MANUAL_NOTIFY_MODE

    def _manual_starting_cash(self) -> float:
        if getattr(self.tcfg, "free", -1) >= 0:
            return float(self.tcfg.free)
        return float(self.cfg.cash)

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

        if not self.is_manual_notify_mode():
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

            if self.is_manual_notify_mode():
                position = self._manual_position
                free_cash = self._manual_cash
            else:
                position = self.exchange.get_account_balance(self.tcfg.symbol_interval.sy.base)
                free_cash = self.tcfg.free

            node = Node(
                self.tcfg.strategy_name(),
                strategy,
                self.tcfg.symbol_interval,
                self.cfg,
                self.log,
                BinanceData(kls_cache),
                position,
                True,
                free_cash,
            )
            ret = node.start()
            if ret is None:
                continue

            self.process_result(ret)

            manual_trade_notifications = []
            if self.is_manual_notify_mode():
                manual_trade_notifications = self.handle_manual_trade_notifications(ret)
            else:
                self.operate_exchange(ret, position)

            stat = TraderStat(self.tcfg.strategy_name(), self.tcfg.symbol_interval.name(), self.ts)
            stat.manual_trade_notifications = manual_trade_notifications
            await queue.put(
                new_stat_msg(
                    stat,
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
            current_opts = list(ret.opts or [])
            previous_opts = list(last_task.tret.opts or [])
            ret.opts = previous_opts + current_opts

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

    def handle_manual_trade_notifications(self, ret: TraderResult) -> list[ManualTradeNotificationEvent]:
        if not ret.opts:
            return []

        op = ret.opts[-1]
        if not isinstance(op, object) or not hasattr(op, "otype"):
            return []

        price = float(op.price or 0.0)
        if price <= 0:
            self.log.warning(f"Skip manual notification due to invalid price: operateType={getattr(op, 'otype', None)} price={op.price}")
            return []

        if op.otype in (OperateType.BUY, OperateType.LONG, OperateType.SHORT):
            return [self._manual_entry_event(op, price)]
        if op.otype in (OperateType.SELL, OperateType.CLOSE):
            event = self._manual_exit_event(op, price)
            return [event] if event is not None else []

        self.log.warning(f"Skip unsupported manual notify operateType: {op.otype}")
        return []

    def _risk_reference(self, op, name: str):
        if hasattr(op, name):
            return getattr(op, name)
        return None

    def _manual_entry_event(self, op, price: float) -> ManualTradeNotificationEvent:
        cash_before = float(self._manual_cash)
        position_before = float(self._manual_position)
        amount = max(cash_before, 0.0)
        quantity = amount / price if price > 0 else 0.0
        if op.otype == OperateType.SHORT:
            position_after = position_before - quantity
        else:
            position_after = position_before + quantity
        cash_after = cash_before - amount
        self._manual_cash = cash_after
        self._manual_position = position_after
        return ManualTradeNotificationEvent(
            market=self.tcfg.symbol_interval.symbol(),
            strategy=self.tcfg.strategy_name(),
            task_id=self.tcfg.id,
            mode=MANUAL_NOTIFY_MODE,
            action="ENTRY",
            side=op.otype.name,
            signal_time=int(op.dtime),
            signal_price=price,
            suggested_amount=amount,
            suggested_quantity=quantity,
            trigger_reason="signal_entry",
            local_state=ManualTradeAccountState(cash_before, cash_after, position_before, position_after),
            stop_loss=self._risk_reference(op, "stop_loss"),
            take_profit=self._risk_reference(op, "take_profit"),
            risk_reward_ratio=self._risk_reference(op, "risk_reward_ratio"),
        )

    def _manual_exit_event(self, op, price: float) -> ManualTradeNotificationEvent | None:
        cash_before = float(self._manual_cash)
        position_before = float(self._manual_position)
        if position_before == 0.0:
            self.log.info(f"Skip manual exit notification due to empty local position: operateType={op.otype}")
            return None
        quantity = abs(position_before)
        amount = quantity * price
        cash_after = cash_before + amount
        position_after = 0.0
        self._manual_cash = cash_after
        self._manual_position = position_after
        return ManualTradeNotificationEvent(
            market=self.tcfg.symbol_interval.symbol(),
            strategy=self.tcfg.strategy_name(),
            task_id=self.tcfg.id,
            mode=MANUAL_NOTIFY_MODE,
            action="EXIT",
            side=op.otype.name,
            signal_time=int(op.dtime),
            signal_price=price,
            suggested_amount=amount,
            suggested_quantity=quantity,
            trigger_reason=getattr(op, "trigger_reason", "signal_exit"),
            local_state=ManualTradeAccountState(cash_before, cash_after, position_before, position_after),
        )
