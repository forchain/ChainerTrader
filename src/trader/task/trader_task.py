import asyncio
import contextvars
from asyncio import Queue
from datetime import datetime, timedelta

from trader.common.config import Config
from trader.common.logger import Logger
from trader.common.message import new_stat_msg
from trader.database.manager import DatabaseManager
from trader.exchange.binance.exchange import BinanceExchange
from trader.live.auto_execution import AutoExecutionRouter, execution_outcome_event
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
    ManualTradeNotificationEvent,
    normalize_live_execution_mode,
)
from trader.statistics.stat import TraderStat
from trader.strategy.node import build_strategy_kwargs
from trader.strategy.strategy import parse_strategies
from trader.strategy.trader_result import TraderResult
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig
from trader.utils.operate import OperateType
from trader.utils.symbol_interval import get_time_duration

DOWLOAD_SPACE_TIME = 5
REALTIME_STREAM_QUEUE_TIMEOUT_SECONDS = 1.0


async def _maybe_await(value):
    if asyncio.iscoroutine(value):
        return await value
    return value


async def _run_blocking(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


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
        self._auto_execution_router = AutoExecutionRouter(
            tcfg,
            exchange=exchange,
            cfg=cfg,
            log=log,
        )
        self.ts.auto_execution_outcomes = []
        self.ts.execution_reconcile = []

    def is_manual_notify_mode(self) -> bool:
        return normalize_live_execution_mode(getattr(self.tcfg, "live_execution_mode", None)) == MANUAL_NOTIFY_MODE

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

        await _maybe_await(super().start(queue))

        strategy = parse_strategies(self.tcfg.strategies)
        if strategy is None:
            self.log.error(f"Not support strategy:{self.tcfg.strategy_name()}")
            return

        # if self.exchange.spot_ws_client:
        #    self.exchange.spot_ws_client.klines(symbol=self.symbol_interval.symbol, interval=self.symbol_interval.interval.value, limit=1)

        if not self.is_manual_notify_mode():
            commission = await _run_blocking(self.exchange.get_account_commission, self.tcfg.symbol_interval.symbol())
            if commission:
                self.cfg.commission = commission
                self.log.info(f"set commission for trader task config:{self.cfg.commission}")
                self.ts.commission = commission

        await self.start_realtime(queue, strategy)

    async def start_realtime(self, queue: Queue, strategy):
        async def publish_event(event):
            await GLOBAL_LIVE_EVENT_BUS.publish(event)

        collection_name = self.tcfg.symbol_interval.name()
        key = MarketStreamKey(self.exchange.name(), self.tcfg.symbol_interval.symbol(), self.tcfg.symbol_interval.interval.value)
        latest = await _maybe_await(self.db_manager.kline.get_latest_kline(collection_name))
        plan = plan_initial_backfill(latest, now=int(datetime.now().timestamp()), interval=self.tcfg.symbol_interval.interval)
        self.log.info(
            f"Realtime startup backfill started: task_id={self.tcfg.id} collection={collection_name} "
            f"stream={key.stream_name()} kind={plan.kind.value} limit={plan.limit} missing_count={plan.missing_count}"
        )
        synced = await self._sync_realtime_backfill(plan)
        self.log.info(
            f"Realtime startup backfill completed: task_id={self.tcfg.id} collection={collection_name} "
            f"stream={key.stream_name()} synced={synced}"
        )

        warmup_cap = max(1, int(getattr(self.cfg, "warmup_candles", 500) or 500))
        warmup_limit = min(int(self.cfg.window), warmup_cap)
        self.log.info(f"Realtime live warmup started: task_id={self.tcfg.id} collection={collection_name} target={warmup_limit}")
        warmup = await _maybe_await(self.db_manager.kline.get_latest_klines(collection_name, warmup_limit)) or []
        if len(warmup) < warmup_limit:
            fetched_warmup = await _run_blocking(self.exchange.get_latest_klines, self.tcfg.symbol_interval, warmup_limit) or []
            if fetched_warmup:
                await _add_repository_klines(self.db_manager.kline, collection_name, fetched_warmup)
                warmup = await _maybe_await(self.db_manager.kline.get_latest_klines(collection_name, warmup_limit)) or []
        self.log.info(f"Realtime live warmup ready: collection={collection_name} candles={len(warmup)}/{warmup_limit}")
        await self._reconcile_execution_state()
        loop = asyncio.get_running_loop()
        live_operation_context = contextvars.copy_context()
        live_operation_tasks: set[asyncio.Task] = set()
        live_tick_operations: dict[int, list[str]] = {}
        auto_execution_lock = asyncio.Lock()

        def operation_name(op) -> str:
            otype = getattr(op, "otype", None)
            return getattr(otype, "name", str(otype or "UNKNOWN"))

        async def handle_live_operation(op):
            ret = self._trader_result_for_live_operation(op)
            feed_phase = str(getattr(op, "feed_phase", "") or "").lower()
            if feed_phase != "warmup":
                await self.process_result(ret)
            notifications = []
            auto_execution_outcomes = []
            if self.is_manual_notify_mode():
                notifications = [] if feed_phase == "warmup" else self._auto_execution_router.handle_manual_trade_notifications(ret)
            else:
                if feed_phase == "warmup":
                    self.log.info(
                        f"Realtime warmup operation ignored for auto execution: task_id={self.tcfg.id} "
                        f"strategy={self.tcfg.strategy_name()} operation={operation_name(op)} event_time={int(getattr(op, 'dtime', 0) or 0)}"
                    )
                else:
                    async with auto_execution_lock:
                        outcome = await _run_blocking(self._auto_execution_router.route, op)
                    auto_execution_outcomes = [outcome]
                    await self._persist_auto_execution_state(outcome)
                    self.ts.auto_execution_outcomes = list(getattr(self.ts, "auto_execution_outcomes", []) or []) + auto_execution_outcomes
                    await _maybe_await(self.db_manager.task.add_tasks([self.ts]))
            event_time = int(getattr(op, "dtime", datetime.now().timestamp()))
            await publish_event(strategy_execution_event(self.tcfg.id, event_time, ret, [op]))
            for outcome in auto_execution_outcomes:
                await publish_event(execution_outcome_event(self.tcfg.id, outcome))
            if getattr(op, "otype", None) != OperateType.RISK_UPDATE:
                self.log.info(
                    f"Realtime strategy signal: task_id={self.tcfg.id} strategy={self.tcfg.strategy_name()} "
                    f"stream={key.stream_name()} open_time={event_time} operations=1 op_types=[{operation_name(op)}] "
                    f"notifications={len(notifications)} execution_outcomes={len(auto_execution_outcomes)}"
                )
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
            event_time = int(getattr(op, "dtime", 0) or 0)
            if event_time:
                live_tick_operations.setdefault(event_time, []).append(operation_name(op))
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
            getattr(self._auto_execution_router, "manual_position", float(getattr(self.tcfg, "manual_start_position", 0.0) or 0.0)),
            True,
            getattr(self.tcfg, "strategy_params", None),
        )
        starting_cash = float(self.tcfg.free) if getattr(self.tcfg, "free", -1) >= 0 else float(self.cfg.cash)
        free_cash = getattr(self._auto_execution_router, "manual_cash", starting_cash)
        runner = BacktraderLiveRunner(
            strategy,
            cash=free_cash,
            commission=self.cfg.commission,
            strategy_kwargs=strategy_kwargs,
            operation_handler=handle_operation,
            inject_operation_sink=True,
        )
        await _run_blocking(runner.start, warmup=warmup)
        await asyncio.sleep(0)

        connector = getattr(GLOBAL_MARKET_STREAM_HUB, "connector", None)
        set_exchange = getattr(connector, "set_exchange", None)
        if set_exchange is not None:
            set_exchange(self.exchange)

        def runtime_status() -> dict:
            status = runner.status() if hasattr(runner, "status") else {}
            execution_reconcile = list(getattr(self.ts, "execution_reconcile", []) or [])
            status["execution_reconcile_open_count"] = len(execution_reconcile)
            status["execution_reconcile"] = execution_reconcile
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
            await self._reconcile_execution_state()
            latest = await _maybe_await(self.db_manager.kline.get_latest_kline(collection_name))
            plan = plan_initial_backfill(latest, now=int(datetime.now().timestamp()), interval=self.tcfg.symbol_interval.interval)
            fetched = []
            if plan.kind != BackfillRequestKind.NONE:
                await self._sync_realtime_backfill(plan)
                step = int(get_time_duration(self.tcfg.symbol_interval.interval))
                if plan.kind == BackfillRequestKind.RANGE:
                    fetch_start, fetch_end = int(plan.start_time), int(plan.end_time)
                else:
                    fetch_start = int(latest.open_time) + step if latest is not None else 0
                    fetch_end = int(datetime.now().timestamp())
                fetched = (
                    await _maybe_await(self.db_manager.kline.get_klines(collection_name, fetch_start, fetch_end))
                    or []
                )
            if not fetched:
                await publish_runtime_status()
                return
            sorted_fetched = sorted(fetched, key=lambda item: int(item.open_time))
            for kline in sorted_fetched:
                await _add_repository_klines(self.db_manager.kline, collection_name, [kline])
                await _run_blocking(runner.put_kline, kline)
                self.log.debug(
                    f"Realtime catch-up kline processed: task_id={self.tcfg.id} collection={collection_name} "
                    f"stream={key.stream_name()} open_time={int(kline.open_time)} close={kline.close} volume={kline.volume}"
                )
            await publish_runtime_status(int(sorted_fetched[-1].open_time))

        subscription = await GLOBAL_MARKET_STREAM_HUB.subscribe(key, reconnect_callback=catch_up_missing_closed_klines)
        self.log.info(f"Realtime stream subscribed: task_id={self.tcfg.id} stream={key.stream_name()}")
        self.log.info(f"Realtime waiting for next closed kline: task_id={self.tcfg.id} stream={key.stream_name()}")
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
                kline = update.to_kline()
                self.log.debug(
                    f"Realtime kline accepted: task_id={self.tcfg.id} collection={collection_name} "
                    f"stream={key.stream_name()} open_time={update.open_time} close_time={update.close_time} "
                    f"close={update.close} volume={update.volume}"
                )
                await _add_repository_klines(self.db_manager.kline, collection_name, [kline])
                self.log.debug(
                    f"Realtime kline persisted: task_id={self.tcfg.id} collection={collection_name} "
                    f"stream={key.stream_name()} open_time={update.open_time}"
                )
                await _run_blocking(runner.put_kline, kline)
                await asyncio.sleep(0)
                await publish_runtime_status(update.open_time)
                op_types = live_tick_operations.pop(int(update.open_time), [])
                self.log.debug(
                    f"Realtime strategy tick completed: task_id={self.tcfg.id} strategy={self.tcfg.strategy_name()} "
                    f"stream={key.stream_name()} open_time={update.open_time} operations={len(op_types)} "
                    f"op_types={op_types} mode={getattr(self.tcfg, 'live_execution_mode', 'manual_notify')}"
                )
                stat = TraderStat(self.tcfg.strategy_name(), self.tcfg.symbol_interval.name(), self.ts)
                stat.manual_trade_notifications = []
                await queue.put(new_stat_msg(stat, self.tcfg.id))
        finally:
            runner.stop()
            if live_operation_tasks:
                await asyncio.gather(*live_operation_tasks, return_exceptions=True)
            await subscription.unsubscribe()

    async def _sync_realtime_backfill(self, plan) -> int:
        """Sync a backfill range through the canonical dataset resolver seam."""
        from trader.task.dataset_resolver import DatasetResolver

        step = int(get_time_duration(self.tcfg.symbol_interval.interval))
        if plan.kind == BackfillRequestKind.LATEST:
            end_time = int(datetime.now().timestamp())
            start_time = end_time - max(1, int(plan.limit)) * step
        elif plan.kind == BackfillRequestKind.RANGE:
            start_time, end_time = int(plan.start_time), int(plan.end_time)
        else:
            return 0
        resolver = DatasetResolver(self.db_manager, self.exchange, self.log)
        result = await resolver.sync_range(
            self.tcfg.symbol_interval,
            start_time,
            end_time,
            allow_download=True,
            allow_incomplete_coverage=True,
        )
        if not result.ok:
            reason = result.failure.reason if result.failure is not None else "unknown"
            message = result.failure.message if result.failure is not None else ""
            self.log.error(f"Realtime backfill sync failed: reason={reason} message={message}")
            return 0
        return max(0, int(plan.missing_count))

    async def _reconcile_execution_state(self) -> list[dict]:
        if self.is_manual_notify_mode():
            self.ts.execution_reconcile = []
            return []
        store = getattr(self.db_manager, "execution_state", None)
        if store is None:
            self.ts.execution_reconcile = []
            return []
        list_open_by_task = getattr(store, "list_open_by_task", None)
        if callable(list_open_by_task):
            records = await _maybe_await(list_open_by_task(self.tcfg.id))
        else:
            records = await _maybe_await(store.list_open_by_symbol(self.tcfg.symbol_interval.symbol()))
        payload = self._auto_execution_router.reconcile(records)
        self.ts.execution_reconcile = payload
        return payload

    async def _persist_auto_execution_state(self, outcome) -> None:
        await self._auto_execution_router.persist_outcome(
            outcome,
            state_store=getattr(self.db_manager, "execution_state", None),
            reservation_store=getattr(self.db_manager, "account_fund_reservation", None),
        )

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

    def handle_manual_trade_notifications(self, ret: TraderResult) -> list[ManualTradeNotificationEvent]:
        return self._auto_execution_router.handle_manual_trade_notifications(ret)
