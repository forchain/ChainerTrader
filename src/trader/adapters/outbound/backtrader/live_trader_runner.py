"""Live trader task runner adapter over exchange, execution, marketdata, notification, and task ports."""

from __future__ import annotations

import asyncio
import contextvars
from datetime import datetime, timedelta
from typing import Any, Callable

from trader.adapters.outbound.backtrader.catalog import parse_strategies
from trader.adapters.outbound.backtrader.live_runtime import BacktraderLiveRunner
from trader.core.exchange.interfaces import ExchangeClient
from trader.core.execution import ExecutionGateway, ExecutionStateStore
from trader.core.marketdata.interfaces import KlineRepository, MarketStreamPort
from trader.core.marketdata.stream import MarketStreamKey
from trader.core.notification.domain import (
    ManualTradeAccountState,
    ManualTradeNotificationEvent,
)
from trader.core.notification.interfaces import NotificationSender
from trader.core.notification.use_cases import SendManualTradeNotification
from trader.core.shared.domain import OperateType
from trader.core.shared.messages import new_stat_msg
from trader.core.strategy.domain.node import build_strategy_kwargs
from trader.core.task.config import TaskConfig
from trader.core.task.domain import TaskState, TaskStateType, task_state_name
from trader.core.task.interfaces import FundReservationStore, TaskEventPublisher, TaskRepository
from trader.core.task.stats import TraderStat
from trader.live.auto_execution import (
    MANUAL_NOTIFY_MODE,
    AutoExecutionRouter,
    execution_outcome_event,
    normalize_live_execution_mode,
)
from trader.live.dashboard import (
    build_risk_overlay_events,
    build_signal_marker_event,
    kline_update_event,
    notification_event,
    runtime_status_event,
    strategy_execution_event,
)
from trader.live.market_data import BackfillRequestKind, plan_initial_backfill
from trader.strategy.trader_result import TraderResult

REALTIME_STREAM_QUEUE_TIMEOUT_SECONDS = 1.0


async def _maybe_await(value):
    if asyncio.iscoroutine(value):
        return await value
    return value


async def _run_blocking(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)


async def _add_repository_klines(kline_store: KlineRepository, collection_name: str, klines: list):
    try:
        return await _maybe_await(kline_store.add_klines(collection_name, klines, source="exchange"))
    except TypeError as exc:
        if "source" not in str(exc):
            raise
        ret = kline_store.add_klines(collection_name, klines)
        if asyncio.iscoroutine(ret):
            return await ret
        return ret


class LiveTraderTaskRunner:
    """TaskRunner adapter executing live trading tasks through domain ports."""

    def __init__(
        self,
        *,
        cfg: Any,
        log: Any,
        exchange_client: ExchangeClient,
        execution_gateway: ExecutionGateway | None = None,
        execution_state_store: ExecutionStateStore | None = None,
        task_repository: TaskRepository | None = None,
        kline_repository: KlineRepository | None = None,
        fund_reservation_store: FundReservationStore | None = None,
        market_stream: MarketStreamPort | None = None,
        event_publisher: TaskEventPublisher | None = None,
        notification_sender: NotificationSender | None = None,
        live_runner_factory: Callable[..., Any] = BacktraderLiveRunner,
        strategy_parser: Callable[[list[str]], Any] = parse_strategies,
        backfill_planner: Callable[..., Any] = plan_initial_backfill,
    ):
        self.cfg = cfg
        self.log = log
        self.exchange_client = exchange_client
        self.execution_gateway = execution_gateway
        self.execution_state_store = execution_state_store
        self.task_repository = task_repository
        self.kline_repository = kline_repository
        self.fund_reservation_store = fund_reservation_store
        self.market_stream = market_stream
        self.event_publisher = event_publisher
        self.notification_sender = notification_sender
        self.live_runner_factory = live_runner_factory
        self.strategy_parser = strategy_parser
        self.backfill_planner = backfill_planner

    async def run(self, tcfg: TaskConfig, **kwargs: Any) -> TaskState:
        queue = kwargs.get("queue") or asyncio.Queue()
        quit_event = kwargs.get("quit_event") or asyncio.Event()
        ts = kwargs.get("task_state")
        if ts is None:
            ts = TaskState(
                tcfg.id,
                task_state_name(tcfg),
                datetime.now(),
                commission=float(getattr(self.cfg, "commission", 0.0) or 0.0),
                strategy_start_time=tcfg.start_time,
                strategy_end_time=tcfg.end_time,
                initial_cash=float(getattr(self.cfg, "cash", 0.0) or 0.0) if tcfg.free < 0 else float(tcfg.free),
                user_id=tcfg.user_id,
            )
            ts.auto_execution_outcomes = []
            ts.execution_reconcile = []

        session = _LiveTraderSession(self, tcfg, ts)
        await session.run(queue, quit_event)
        return ts

    def build_session(self, tcfg: TaskConfig, ts: TaskState) -> "_LiveTraderSession":
        return _LiveTraderSession(self, tcfg, ts)


class _LiveTraderSession:
    def __init__(self, runner: LiveTraderTaskRunner, tcfg: TaskConfig, ts: TaskState):
        self.runner = runner
        self.tcfg = tcfg
        self.ts = ts
        self.cfg = runner.cfg
        self.log = runner.log
        self.exchange = runner.exchange_client
        self._manual_cash = float(tcfg.free) if getattr(tcfg, "free", -1) >= 0 else float(getattr(self.cfg, "cash", 0.0) or 0.0)
        self._manual_position = float(getattr(tcfg, "manual_start_position", 0.0) or 0.0)
        self._auto_execution_router = AutoExecutionRouter(
            tcfg,
            exchange=self.exchange,
            cfg=self.cfg,
            log=self.log,
            gateway=runner.execution_gateway,
        )

    def is_manual_notify_mode(self) -> bool:
        return normalize_live_execution_mode(getattr(self.tcfg, "live_execution_mode", None)) == MANUAL_NOTIFY_MODE

    async def run(self, queue: asyncio.Queue, quit_event: asyncio.Event) -> None:
        if not self.tcfg.strategies or self.exchange is None or self.runner.kline_repository is None:
            return
        ts = self.ts
        ts.state = TaskStateType.RUNNING
        if self.runner.task_repository is not None:
            await _maybe_await(self.runner.task_repository.add_tasks([ts]))

        strategy = self.runner.strategy_parser(self.tcfg.strategies)
        if strategy is None:
            self.log.error(f"Not support strategy:{self.tcfg.strategy_name()}")
            return

        if not self.is_manual_notify_mode():
            commission = await _run_blocking(self.exchange.get_account_commission, self.tcfg.symbol_interval.symbol())
            if commission:
                self.cfg.commission = commission
                ts.commission = commission

        await self.run_realtime(queue, quit_event, strategy)

    async def run_realtime(self, queue: asyncio.Queue, quit_event: asyncio.Event, strategy) -> None:
        kline_repo = self.runner.kline_repository
        task_repo = self.runner.task_repository
        market_stream = self.runner.market_stream
        if kline_repo is None or market_stream is None:
            raise RuntimeError("LiveTraderTaskRunner requires kline_repository and market_stream")

        async def publish_event(event):
            if self.runner.event_publisher is not None:
                await _maybe_await(self.runner.event_publisher.publish(event))

        collection_name = self.tcfg.symbol_interval.name()
        key = MarketStreamKey(self.exchange.name(), self.tcfg.symbol_interval.symbol(), self.tcfg.symbol_interval.interval.value)
        latest = await _maybe_await(kline_repo.get_latest_kline(collection_name))
        plan = self.runner.backfill_planner(latest, now=int(datetime.now().timestamp()), interval=self.tcfg.symbol_interval.interval)
        self.log.info(
            f"Realtime startup backfill started: task_id={self.tcfg.id} collection={collection_name} "
            f"stream={key.stream_name()} kind={plan.kind.value} limit={plan.limit} missing_count={plan.missing_count}"
        )
        fetched = []
        if plan.kind == BackfillRequestKind.LATEST:
            fetched = await _run_blocking(self.exchange.get_latest_klines, self.tcfg.symbol_interval, plan.limit) or []
        elif plan.kind == BackfillRequestKind.RANGE:
            fetched = (
                await _run_blocking(
                    self.exchange.get_klines,
                    self.tcfg.symbol_interval,
                    start_time=plan.start_time,
                    end_time=plan.end_time,
                    limit=plan.limit,
                )
                or []
            )
        if fetched:
            await _add_repository_klines(kline_repo, collection_name, fetched)
        self.log.info(
            f"Realtime startup backfill completed: task_id={self.tcfg.id} collection={collection_name} "
            f"stream={key.stream_name()} fetched={len(fetched)}"
        )

        warmup_cap = max(1, int(getattr(self.cfg, "warmup_candles", 500) or 500))
        warmup_limit = min(int(self.cfg.window), warmup_cap)
        self.log.info(f"Realtime live warmup started: task_id={self.tcfg.id} collection={collection_name} target={warmup_limit}")
        warmup = await _maybe_await(kline_repo.get_latest_klines(collection_name, warmup_limit)) or []
        if len(warmup) < warmup_limit:
            fetched_warmup = await _run_blocking(self.exchange.get_latest_klines, self.tcfg.symbol_interval, warmup_limit) or []
            if fetched_warmup:
                await _add_repository_klines(kline_repo, collection_name, fetched_warmup)
                warmup = await _maybe_await(kline_repo.get_latest_klines(collection_name, warmup_limit)) or []
        self.log.info(f"Realtime live warmup ready: collection={collection_name} candles={len(warmup)}/{warmup_limit}")
        await self.reconcile_execution_state()

        loop = asyncio.get_running_loop()
        live_operation_context = contextvars.copy_context()
        live_operation_tasks: set[asyncio.Task] = set()
        live_tick_operations: dict[int, list[str]] = {}
        auto_execution_lock = asyncio.Lock()

        def operation_name(op) -> str:
            otype = getattr(op, "otype", None)
            return getattr(otype, "name", str(otype or "UNKNOWN"))

        async def handle_live_operation(op):
            ret = self.trader_result_for_live_operation(op)
            feed_phase = str(getattr(op, "feed_phase", "") or "").lower()
            if feed_phase != "warmup":
                await self.process_result(ret)
            notifications = []
            auto_execution_outcomes = []
            if self.is_manual_notify_mode():
                notifications = [] if feed_phase == "warmup" else self.handle_manual_trade_notifications(ret)
                if notifications and self.runner.notification_sender is not None:
                    notifier = SendManualTradeNotification([self.runner.notification_sender])
                    for item in notifications:
                        notifier.execute(item)
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
                    await self.persist_auto_execution_state(outcome)
                    self.ts.auto_execution_outcomes = list(getattr(self.ts, "auto_execution_outcomes", []) or []) + auto_execution_outcomes
                    if task_repo is not None:
                        await _maybe_await(task_repo.add_tasks([self.ts]))

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
            self._manual_position,
            True,
            getattr(self.tcfg, "strategy_params", None),
        )
        bt_runner = self.runner.live_runner_factory(
            strategy,
            cash=self._manual_cash,
            commission=self.cfg.commission,
            strategy_kwargs=strategy_kwargs,
            operation_handler=handle_operation,
            inject_operation_sink=True,
        )
        await _run_blocking(bt_runner.start, warmup=warmup)
        await asyncio.sleep(0)

        connector = getattr(market_stream, "connector", None)
        set_exchange = getattr(connector, "set_exchange", None)
        if set_exchange is not None:
            set_exchange(self.exchange)

        def runtime_status() -> dict:
            status = bt_runner.status() if hasattr(bt_runner, "status") else {}
            execution_reconcile = list(getattr(self.ts, "execution_reconcile", []) or [])
            status["execution_reconcile_open_count"] = len(execution_reconcile)
            status["execution_reconcile"] = execution_reconcile
            stream_status = market_stream.status(key) if hasattr(market_stream, "status") else None
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
            await self.reconcile_execution_state()
            latest_kline = await _maybe_await(kline_repo.get_latest_kline(collection_name))
            catchup_plan = self.runner.backfill_planner(
                latest_kline, now=int(datetime.now().timestamp()), interval=self.tcfg.symbol_interval.interval
            )
            catchup_fetched = []
            if catchup_plan.kind == BackfillRequestKind.LATEST:
                catchup_fetched = await _run_blocking(self.exchange.get_latest_klines, self.tcfg.symbol_interval, catchup_plan.limit) or []
            elif catchup_plan.kind == BackfillRequestKind.RANGE:
                catchup_fetched = (
                    await _run_blocking(
                        self.exchange.get_klines,
                        self.tcfg.symbol_interval,
                        start_time=catchup_plan.start_time,
                        end_time=catchup_plan.end_time,
                        limit=catchup_plan.limit,
                    )
                    or []
                )
            if not catchup_fetched:
                await publish_runtime_status()
                return
            sorted_fetched = sorted(catchup_fetched, key=lambda item: int(item.open_time))
            for kline in sorted_fetched:
                await _add_repository_klines(kline_repo, collection_name, [kline])
                await _run_blocking(bt_runner.put_kline, kline)
                self.log.debug(
                    f"Realtime catch-up kline processed: task_id={self.tcfg.id} collection={collection_name} "
                    f"stream={key.stream_name()} open_time={int(kline.open_time)} close={kline.close} volume={kline.volume}"
                )
            await publish_runtime_status(int(sorted_fetched[-1].open_time))

        subscription = await market_stream.subscribe(key, reconnect_callback=catch_up_missing_closed_klines)
        self.log.info(f"Realtime stream subscribed: task_id={self.tcfg.id} stream={key.stream_name()}")
        self.log.info(f"Realtime waiting for next closed kline: task_id={self.tcfg.id} stream={key.stream_name()}")
        await publish_runtime_status()
        try:
            while not quit_event.is_set():
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
                await _add_repository_klines(kline_repo, collection_name, [kline])
                self.log.debug(
                    f"Realtime kline persisted: task_id={self.tcfg.id} collection={collection_name} "
                    f"stream={key.stream_name()} open_time={update.open_time}"
                )
                await _run_blocking(bt_runner.put_kline, kline)
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
            bt_runner.stop()
            if live_operation_tasks:
                await asyncio.gather(*live_operation_tasks, return_exceptions=True)
            await subscription.unsubscribe()

    async def reconcile_execution_state(self) -> list[dict]:
        if self.is_manual_notify_mode() or self.runner.execution_state_store is None:
            self.ts.execution_reconcile = []
            return []
        store = self.runner.execution_state_store
        if hasattr(store, "list_open_by_task"):
            records = await _maybe_await(store.list_open_by_task(self.tcfg.id))
        else:
            records = await _maybe_await(store.list_open_by_symbol(self.tcfg.symbol_interval.symbol()))
        payload = self._auto_execution_router.reconcile(records)
        self.ts.execution_reconcile = payload
        return payload

    async def persist_auto_execution_state(self, outcome) -> None:
        await self._auto_execution_router.persist_outcome(
            outcome,
            state_store=self.runner.execution_state_store,
            reservation_store=self.runner.fund_reservation_store,
        )


    @staticmethod
    def trader_result_for_live_operation(op) -> TraderResult:
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

    async def process_result(self, ret: TraderResult) -> None:
        task_repo = self.runner.task_repository
        if task_repo is None:
            self.ts.tret = ret
            return
        last_task = await _maybe_await(task_repo.get_task(self.tcfg.id))
        if last_task and last_task.tret:
            current_opts = list(ret.opts or [])
            previous_opts = list(last_task.tret.opts or [])
            ret.opts = previous_opts + current_opts
        self.ts.tret = ret
        await _maybe_await(task_repo.add_tasks([self.ts]))

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
        return getattr(op, name, None)

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
        position_after = position_before - quantity if op.otype == OperateType.SHORT else position_before + quantity
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
