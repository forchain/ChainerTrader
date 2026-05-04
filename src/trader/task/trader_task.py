import asyncio
import contextvars
from asyncio import Queue
from datetime import datetime, timedelta

from trader.common.common import MIN_RECORDS_NUM, sleep, sleep_loop
from trader.common.config import Config
from trader.common.logger import Logger
from trader.common.message import new_stat_msg
from trader.database.manager import DatabaseManager
from trader.exchange.binance.data import BinanceData
from trader.exchange.binance.exchange import BinanceExchange
from trader.live.backtrader_runtime import BacktraderLiveRunner
from trader.live.dashboard import (
    build_risk_overlay_events,
    build_signal_marker_event,
    kline_update_event,
    notification_event,
    runtime_status_event,
    strategy_execution_event,
)
from trader.live.market_data import BackfillRequestKind, plan_initial_backfill
from trader.live.monitor import GLOBAL_LIVE_EVENT_BUS
from trader.live.stream import GLOBAL_MARKET_STREAM_HUB, MarketStreamKey
from trader.notify.trade_notification import (
    MANUAL_NOTIFY_MODE,
    ManualTradeAccountState,
    ManualTradeNotificationEvent,
    normalize_live_execution_mode,
)
from trader.statistics.stat import TraderStat
from trader.strategy.node import Node, build_strategy_kwargs
from trader.strategy.strategy import parse_strategies
from trader.strategy.trader_result import TraderResult
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig
from trader.task.update_klines_task import download_range
from trader.utils.operate import OperateType
from trader.utils.symbol_interval import add_time_duration

DOWLOAD_SPACE_TIME = 5
REALTIME_STREAM_QUEUE_TIMEOUT_SECONDS = 1.0


async def _maybe_await(value):
    if asyncio.iscoroutine(value):
        return await value
    return value


async def _add_repository_klines(kline_store, collection_name: str, klines: list):
    try:
        return await _maybe_await(kline_store.add_klines(collection_name, klines, source="exchange"))
    except TypeError as exc:
        if "source" not in str(exc):
            raise
        ret = kline_store.add_klines(collection_name, klines)
        if asyncio.iscoroutine(ret):
            return await ret
        return ret


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

        if getattr(self.tcfg, "live_data_mode", "polling") == "realtime":
            await self.start_realtime(queue, strategy)
            return

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

            kls_cache = await _maybe_await(self.db_manager.kline.get_latest_klines(self.tcfg.symbol_interval.name(), self.cfg.window))
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

            await self.process_result(ret)

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

    async def start_realtime(self, queue: Queue, strategy):
        if not self.is_manual_notify_mode():
            self.log.error("realtime live runtime currently supports manual_notify mode only")
            return

        async def publish_event(event):
            await GLOBAL_LIVE_EVENT_BUS.publish(event)

        collection_name = self.tcfg.symbol_interval.name()
        latest = await _maybe_await(self.db_manager.kline.get_latest_kline(collection_name))
        plan = plan_initial_backfill(latest, now=int(datetime.now().timestamp()), interval=self.tcfg.symbol_interval.interval)
        fetched = []
        if plan.kind == BackfillRequestKind.LATEST:
            fetched = self.exchange.get_latest_klines(self.tcfg.symbol_interval, plan.limit) or []
        elif plan.kind == BackfillRequestKind.RANGE:
            fetched = (
                self.exchange.get_klines(
                    self.tcfg.symbol_interval,
                    start_time=plan.start_time,
                    end_time=plan.end_time,
                    limit=plan.limit,
                )
                or []
            )
        if fetched:
            await _add_repository_klines(self.db_manager.kline, collection_name, fetched)

        warmup_limit = min(int(self.cfg.window), 500)
        warmup = await _maybe_await(self.db_manager.kline.get_latest_klines(collection_name, warmup_limit)) or []
        if len(warmup) < warmup_limit:
            fetched_warmup = self.exchange.get_latest_klines(self.tcfg.symbol_interval, warmup_limit) or []
            if fetched_warmup:
                await _add_repository_klines(self.db_manager.kline, collection_name, fetched_warmup)
                warmup = await _maybe_await(self.db_manager.kline.get_latest_klines(collection_name, warmup_limit)) or []
        self.log.info(f"Realtime live warmup ready: collection={collection_name} candles={len(warmup)}/{warmup_limit}")
        loop = asyncio.get_running_loop()
        live_operation_context = contextvars.copy_context()
        live_operation_tasks: set[asyncio.Task] = set()

        async def handle_live_operation(op):
            ret = self._trader_result_for_live_operation(op)
            await self.process_result(ret)
            feed_phase = str(getattr(op, "feed_phase", "") or "").lower()
            notifications = [] if feed_phase == "warmup" else self.handle_manual_trade_notifications(ret)
            event_time = int(getattr(op, "dtime", datetime.now().timestamp()))
            await publish_event(strategy_execution_event(self.tcfg.id, event_time, ret, [op]))
            if getattr(op, "otype", None) != OperateType.RISK_UPDATE:
                await publish_event(build_signal_marker_event(self.tcfg.id, op, getattr(self.tcfg, "live_execution_mode", "manual_notify")))
            for event in build_risk_overlay_events(self.tcfg.id, op):
                await publish_event(event)
            if notifications:
                await publish_event(notification_event(self.tcfg.id, event_time, notifications))
            stat = TraderStat(self.tcfg.strategy_name(), self.tcfg.symbol_interval.name(), self.ts)
            stat.manual_trade_notifications = notifications
            await queue.put(new_stat_msg(stat, self.tcfg.id))

        def schedule_live_operation(op):
            task = loop.create_task(handle_live_operation(op), context=live_operation_context.copy())
            live_operation_tasks.add(task)

            def discard_live_operation(done_task):
                live_operation_tasks.discard(done_task)
                if done_task.cancelled():
                    return
                exc = done_task.exception()
                if exc is not None:
                    self.log.error(f"Realtime live operation failed: {exc}")

            task.add_done_callback(discard_live_operation)

        def handle_operation(op):
            try:
                running_loop = asyncio.get_running_loop()
            except RuntimeError:
                running_loop = None
            if running_loop is loop:
                schedule_live_operation(op)
            else:
                loop.call_soon_threadsafe(schedule_live_operation, op, context=live_operation_context.copy())

        strategy_kwargs = build_strategy_kwargs(
            self.cfg,
            self.log,
            self._manual_position,
            True,
            getattr(self.tcfg, "strategy_params", None),
        )
        free_cash = self._manual_cash
        runner = BacktraderLiveRunner(
            strategy,
            cash=free_cash,
            commission=self.cfg.commission,
            strategy_kwargs=strategy_kwargs,
            operation_handler=handle_operation,
            inject_operation_sink=True,
        )
        runner.start(warmup=warmup)
        await asyncio.sleep(0)

        key = MarketStreamKey(self.exchange.name(), self.tcfg.symbol_interval.symbol(), self.tcfg.symbol_interval.interval.value)

        def runtime_status() -> dict:
            status = runner.status() if hasattr(runner, "status") else {}
            stream_status = GLOBAL_MARKET_STREAM_HUB.status(key) if hasattr(GLOBAL_MARKET_STREAM_HUB, "status") else None
            if stream_status is not None:
                status.update(
                    {
                        "stream_state": stream_status.state.value,
                        "stream_subscriber_count": stream_status.subscriber_count,
                        "stream_last_error": stream_status.last_error,
                    }
                )
            return status

        async def publish_runtime_status(event_time: int | None = None) -> None:
            await publish_event(runtime_status_event(self.tcfg.id, event_time or int(datetime.now().timestamp()), runtime_status()))

        async def catch_up_missing_closed_klines() -> None:
            latest = await _maybe_await(self.db_manager.kline.get_latest_kline(collection_name))
            plan = plan_initial_backfill(latest, now=int(datetime.now().timestamp()), interval=self.tcfg.symbol_interval.interval)
            fetched = []
            if plan.kind == BackfillRequestKind.LATEST:
                fetched = self.exchange.get_latest_klines(self.tcfg.symbol_interval, plan.limit) or []
            elif plan.kind == BackfillRequestKind.RANGE:
                fetched = (
                    self.exchange.get_klines(
                        self.tcfg.symbol_interval,
                        start_time=plan.start_time,
                        end_time=plan.end_time,
                        limit=plan.limit,
                    )
                    or []
                )
            if not fetched:
                await publish_runtime_status()
                return
            sorted_fetched = sorted(fetched, key=lambda item: int(item.open_time))
            for kline in sorted_fetched:
                await _add_repository_klines(self.db_manager.kline, collection_name, [kline])
                runner.put_kline(kline)
            await publish_runtime_status(int(sorted_fetched[-1].open_time))

        subscription = await GLOBAL_MARKET_STREAM_HUB.subscribe(key, reconnect_callback=catch_up_missing_closed_klines)
        await publish_runtime_status()
        try:
            while not self.quit.is_set():
                try:
                    update = await asyncio.wait_for(subscription.get(), timeout=REALTIME_STREAM_QUEUE_TIMEOUT_SECONDS)
                except asyncio.TimeoutError:
                    continue
                await publish_event(kline_update_event(self.tcfg.id, update))
                if not update.is_closed:
                    continue
                await _add_repository_klines(self.db_manager.kline, collection_name, [update.to_kline()])
                runner.put_kline(update.to_kline())
                await asyncio.sleep(0)
                await publish_runtime_status(update.open_time)
                stat = TraderStat(self.tcfg.strategy_name(), self.tcfg.symbol_interval.name(), self.ts)
                stat.manual_trade_notifications = []
                await queue.put(new_stat_msg(stat, self.tcfg.id))
        finally:
            runner.stop()
            if live_operation_tasks:
                await asyncio.gather(*live_operation_tasks, return_exceptions=True)
            await subscription.unsubscribe()

    def _trader_result_for_live_operation(self, op) -> TraderResult:
        return TraderResult(
            0.0,
            0.0,
            timedelta(0),
            0.0,
            0.0,
            0.0,
            0.0,
            0.0,
            1 if op.otype in (OperateType.BUY, OperateType.LONG) else 0,
            1 if op.otype in (OperateType.SELL, OperateType.SHORT, OperateType.CLOSE) else 0,
            [op],
            0.0,
            0,
        )

    async def process_result(self, ret: TraderResult):
        last_task = await _maybe_await(self.db_manager.task.get_task(self.tcfg.id))
        if last_task and last_task.tret:
            current_opts = list(ret.opts or [])
            previous_opts = list(last_task.tret.opts or [])
            ret.opts = previous_opts + current_opts

        self.ts.tret = ret
        await _maybe_await(self.db_manager.task.add_tasks([self.ts]))

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
        if op.otype == OperateType.RISK_UPDATE:
            return [self._manual_risk_update_event(op, price)]

        self.log.warning(f"Skip unsupported manual notify operateType: {op.otype}")
        return []

    def _risk_reference(self, op, name: str):
        if hasattr(op, name):
            return getattr(op, name)
        return None

    def _manual_event_common_kwargs(self, op) -> dict:
        return {
            "interval": self.tcfg.symbol_interval.interval.value,
            "strategy_id": str(self.tcfg.id),
            "signal_event_id": self._risk_reference(op, "signal_event_id"),
            "breakeven_new_stop": self._risk_reference(op, "breakeven_new_stop"),
            "breakeven_step": self._risk_reference(op, "breakeven_step"),
            "divergence_metadata": self._risk_reference(op, "divergence_metadata") or self._risk_reference(op, "signal_metadata"),
        }

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
            **self._manual_event_common_kwargs(op),
        )

    def _manual_risk_update_event(self, op, price: float) -> ManualTradeNotificationEvent:
        cash = float(self._manual_cash)
        position = float(self._manual_position)
        return ManualTradeNotificationEvent(
            market=self.tcfg.symbol_interval.symbol(),
            strategy=self.tcfg.strategy_name(),
            task_id=self.tcfg.id,
            mode=MANUAL_NOTIFY_MODE,
            action="RISK_UPDATE",
            side=op.otype.name,
            signal_time=int(op.dtime),
            signal_price=price,
            suggested_amount=0.0,
            suggested_quantity=0.0,
            trigger_reason=getattr(op, "trigger_reason", "risk_update"),
            local_state=ManualTradeAccountState(cash, cash, position, position),
            stop_loss=self._risk_reference(op, "stop_loss"),
            take_profit=self._risk_reference(op, "take_profit"),
            risk_reward_ratio=self._risk_reference(op, "risk_reward_ratio"),
            **self._manual_event_common_kwargs(op),
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
            stop_loss=self._risk_reference(op, "stop_loss"),
            take_profit=self._risk_reference(op, "take_profit"),
            risk_reward_ratio=self._risk_reference(op, "risk_reward_ratio"),
            **self._manual_event_common_kwargs(op),
        )
