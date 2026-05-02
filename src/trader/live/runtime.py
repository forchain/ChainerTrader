from __future__ import annotations

import inspect
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from trader.common.config import Config
from trader.common.logger import Logger, default
from trader.database.manager import DatabaseManager
from trader.exchange.binance.data import BinanceData
from trader.exchange.binance.exchange import BinanceExchange
from trader.live.dashboard import (
    DashboardEvent,
    build_macd_divergence_event,
    build_risk_overlay_events,
    build_signal_marker_event,
    ensure_signal_tracking,
    kline_update_event,
    notification_event,
    strategy_execution_event,
)
from trader.live.market_data import BackfillPlan, BackfillRequestKind, KlineUpdate, KlineUpdateBuffer, plan_initial_backfill
from trader.strategy.node import Node
from trader.strategy.strategy import parse_strategies
from trader.task.task_config import TaskConfig
from trader.utils.operate import Operate, OperateType

StrategyRunner = Callable[[list], Any]
NotificationHandler = Callable[[Any], list[Any]]
EventPublisher = Callable[[DashboardEvent], Any]


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def _add_klines(kline_store, collection_name: str, klines: list):
    try:
        return await _maybe_await(kline_store.add_klines(collection_name, klines, source="exchange"))
    except TypeError as exc:
        if "source" not in str(exc):
            raise
        return await _maybe_await(kline_store.add_klines(collection_name, klines))


@dataclass
class RuntimeStepResult:
    accepted: bool = True
    kline_update: KlineUpdate | None = None
    backfill_plan: BackfillPlan | None = None
    strategy_result: Any = None
    manual_notifications: list[Any] = field(default_factory=list)


@dataclass
class ManualRiskState:
    side: str
    stop_loss: float | None = None
    take_profit: float | None = None
    risk_reward_ratio: float | None = None
    signal_event_id: str | None = None
    signal_number: int | None = None


class RealtimeLiveStrategyRuntime:
    def __init__(
        self,
        tcfg: TaskConfig,
        cfg: Config,
        db_manager: DatabaseManager,
        exchange: BinanceExchange,
        log: Logger | None = None,
        strategy_runner: StrategyRunner | None = None,
        notification_handler: NotificationHandler | None = None,
        event_publisher: EventPublisher | None = None,
        now_fn: Callable[[], int | float] | None = None,
    ):
        self.tcfg = tcfg
        self.cfg = cfg
        self.db_manager = db_manager
        self.exchange = exchange
        self.log = log or default()
        self.strategy_runner = strategy_runner
        self.notification_handler = notification_handler
        self.event_publisher = event_publisher
        self.now_fn = now_fn or time.time
        self.buffer = KlineUpdateBuffer()
        self.diagnostics: dict[str, Any] = {}
        self._signal_counter = 0
        self._seen_operation_keys: set[tuple] = set()
        self._saved_operations = self._load_saved_operations()
        self._seed_seen_operations(self._saved_operations)
        self._manual_risk_state = self._manual_risk_state_from_operations(self._saved_operations)

    @property
    def collection_name(self) -> str:
        return self.tcfg.symbol_interval.name()

    async def startup(self) -> RuntimeStepResult:
        latest = await _maybe_await(self.db_manager.kline.get_latest_kline(self.collection_name))
        plan = plan_initial_backfill(latest, now=int(self.now_fn()), interval=self.tcfg.symbol_interval.interval)
        fetched = self._fetch_backfill(plan)
        inserted = 0
        if fetched:
            inserted = await _add_klines(self.db_manager.kline, self.collection_name, fetched)

        self.diagnostics.update(
            {
                "startup_backfill_kind": plan.kind.value,
                "startup_backfill_missing_count": plan.missing_count,
                "startup_backfill_inserted": inserted,
                "startup_backfill_truncated": plan.truncated,
                "startup_backfill_diagnostic": plan.diagnostic,
            }
        )
        strategy_result = await self._run_strategy_on_latest_window()
        current_operations = self._filter_new_operations(strategy_result)
        self._assign_signal_tracking(current_operations)
        notifications = self._notify(strategy_result)
        self._apply_manual_risk_operations(current_operations)
        if strategy_result is not None:
            for event in self._strategy_dashboard_events(strategy_result, int(self.now_fn()), current_operations):
                await self._publish(event)
        if notifications:
            await self._publish(notification_event(self.tcfg.id, int(self.now_fn()), notifications))
        return RuntimeStepResult(backfill_plan=plan, strategy_result=strategy_result, manual_notifications=notifications)

    async def handle_kline_update(self, update: KlineUpdate) -> RuntimeStepResult:
        if not self.buffer.accept(update):
            return RuntimeStepResult(accepted=False, kline_update=update)

        await self._publish(kline_update_event(self.tcfg.id, update))
        if not update.is_closed:
            return RuntimeStepResult(kline_update=update)

        await _add_klines(self.db_manager.kline, self.collection_name, [update.to_kline()])
        strategy_result = await self._run_strategy_on_latest_window()
        stop_operation = self._manual_stop_operation(update)
        if stop_operation is not None:
            if strategy_result is None:
                strategy_result = type("RealtimeManualRiskResult", (), {"opts": []})()
            strategy_result.opts = list(getattr(strategy_result, "opts", []) or []) + [stop_operation]
        current_operations = self._filter_new_operations(strategy_result)
        self._assign_signal_tracking(current_operations)
        notifications = self._notify(strategy_result)
        self._apply_manual_risk_operations(current_operations)
        if strategy_result is not None:
            for event in self._strategy_dashboard_events(strategy_result, update.event_time, current_operations):
                await self._publish(event)
        if notifications:
            await self._publish(notification_event(self.tcfg.id, update.event_time, notifications))
        return RuntimeStepResult(kline_update=update, strategy_result=strategy_result, manual_notifications=notifications)

    def _fetch_backfill(self, plan: BackfillPlan) -> list:
        if plan.kind == BackfillRequestKind.NONE:
            return []
        if plan.kind == BackfillRequestKind.LATEST:
            return self.exchange.get_latest_klines(self.tcfg.symbol_interval, plan.limit) or []
        return (
            self.exchange.get_klines(
                self.tcfg.symbol_interval,
                start_time=plan.start_time,
                end_time=plan.end_time,
                limit=plan.limit,
            )
            or []
        )

    async def _run_strategy_on_latest_window(self):
        candles = await _maybe_await(self.db_manager.kline.get_latest_klines(self.collection_name, min(int(self.cfg.window), 500))) or []
        if self.strategy_runner is not None:
            return self.strategy_runner(candles)

        strategy = parse_strategies(self.tcfg.strategies)
        if strategy is None:
            self.log.error(f"Not support strategy:{self.tcfg.strategy_name()}")
            return None

        position = 0.0
        free_cash = self.tcfg.free if getattr(self.tcfg, "free", -1) >= 0 else self.cfg.cash
        node = Node(
            self.tcfg.strategy_name(),
            strategy,
            self.tcfg.symbol_interval,
            self.cfg,
            self.log,
            BinanceData(candles),
            position,
            True,
            free_cash,
            strategy_params=getattr(self.tcfg, "strategy_params", None),
        )
        return node.start()

    def _notify(self, strategy_result) -> list[Any]:
        if strategy_result is None or self.notification_handler is None:
            return []
        return self.notification_handler(strategy_result) or []

    async def _publish(self, event: DashboardEvent) -> None:
        if self.event_publisher is None:
            return
        maybe_awaitable = self.event_publisher(event)
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable

    def _assign_signal_tracking(self, operations: list) -> None:
        for op in operations:
            if getattr(op, "signal_number", None) is None:
                self._signal_counter += 1
                ensure_signal_tracking(self.tcfg.id, op, self._signal_counter)
            else:
                ensure_signal_tracking(self.tcfg.id, op, getattr(op, "signal_number"))

    def _load_saved_operations(self) -> list:
        try:
            last_task = self.db_manager.task.get_task(self.tcfg.id)
        except AttributeError:
            return []
        if not last_task or not getattr(last_task, "tret", None):
            return []
        return list(getattr(last_task.tret, "opts", []) or [])

    def _seed_seen_operations(self, operations: list) -> None:
        for op in operations or []:
            self._seen_operation_keys.add(self._operation_key(op))

    def _operation_key(self, op) -> tuple:
        signal_event_id = getattr(op, "signal_event_id", None)
        if signal_event_id:
            return ("signal_event_id", str(signal_event_id))
        side = op.otype.name if getattr(op, "otype", None) else "UNKNOWN"
        price = float(getattr(op, "price", 0.0) or 0.0)
        return ("operation", side, int(getattr(op, "dtime", 0) or 0), f"{price:.12g}")

    def _filter_new_operations(self, strategy_result) -> list:
        if strategy_result is None:
            return []
        new_operations = []
        for op in list(getattr(strategy_result, "opts", []) or []):
            key = self._operation_key(op)
            if key in self._seen_operation_keys:
                continue
            self._seen_operation_keys.add(key)
            new_operations.append(op)
        strategy_result.opts = new_operations
        return new_operations

    def _manual_risk_state_from_operations(self, operations: list) -> ManualRiskState | None:
        state: ManualRiskState | None = None
        for op in operations or []:
            state = self._next_manual_risk_state(state, op)
        return state

    def _next_manual_risk_state(self, state: ManualRiskState | None, op) -> ManualRiskState | None:
        otype = getattr(op, "otype", None)
        if otype in (OperateType.BUY, OperateType.LONG):
            return self._risk_state_from_entry(op, "LONG")
        if otype == OperateType.SHORT:
            return self._risk_state_from_entry(op, "SHORT")
        if otype in (OperateType.SELL, OperateType.CLOSE):
            return None
        return state

    def _risk_state_from_entry(self, op, side: str) -> ManualRiskState:
        framework_trade = getattr(op, "framework_trade", None)
        metadata = getattr(op, "divergence_metadata", None) or getattr(op, "signal_metadata", None)
        stop_loss = getattr(op, "stop_loss", None)
        take_profit = getattr(op, "take_profit", None)
        risk_reward_ratio = getattr(op, "risk_reward_ratio", None)
        if isinstance(framework_trade, dict):
            if stop_loss is None:
                stop_loss = framework_trade.get("stop_price") or framework_trade.get("initial_stop_price")
            if take_profit is None:
                take_profit = framework_trade.get("take_profit")
            if risk_reward_ratio is None:
                risk_reward_ratio = framework_trade.get("risk_reward_ratio")
        if stop_loss is None and isinstance(metadata, dict):
            stop_loss = metadata.get("suggested_stop_price")
        return ManualRiskState(
            side=side,
            stop_loss=float(stop_loss) if stop_loss is not None else None,
            take_profit=float(take_profit) if take_profit is not None else None,
            risk_reward_ratio=float(risk_reward_ratio) if risk_reward_ratio is not None else None,
            signal_event_id=getattr(op, "signal_event_id", None) or (metadata.get("signal_event_id") if isinstance(metadata, dict) else None),
            signal_number=getattr(op, "signal_number", None),
        )

    def _manual_stop_operation(self, update: KlineUpdate) -> Operate | None:
        state = self._manual_risk_state
        if state is None or state.stop_loss is None:
            return None
        stop_loss = float(state.stop_loss)
        if state.side == "LONG":
            if float(update.low) > stop_loss:
                return None
            op = Operate(OperateType.SELL, int(update.open_time), stop_loss)
        elif state.side == "SHORT":
            if float(update.high) < stop_loss:
                return None
            op = Operate(OperateType.CLOSE, int(update.open_time), stop_loss)
        else:
            return None
        op.stop_loss = stop_loss
        if state.take_profit is not None:
            op.take_profit = float(state.take_profit)
        if state.risk_reward_ratio is not None:
            op.risk_reward_ratio = float(state.risk_reward_ratio)
        op.trigger_reason = "framework_stop"
        if state.signal_event_id:
            op.signal_event_id = f"{state.signal_event_id}-stop-{int(update.open_time)}"
        if state.signal_number is not None:
            op.signal_number = state.signal_number
        return op

    def _apply_manual_risk_operations(self, operations: list) -> None:
        for op in operations or []:
            self._manual_risk_state = self._next_manual_risk_state(self._manual_risk_state, op)

    def _strategy_dashboard_events(self, strategy_result, event_time: int, operations: list | None = None) -> list[DashboardEvent]:
        current_operations = list(operations if operations is not None else getattr(strategy_result, "opts", []) or [])
        events = [strategy_execution_event(self.tcfg.id, event_time, strategy_result, current_operations)]
        for op in current_operations:
            events.append(
                build_signal_marker_event(
                    self.tcfg.id,
                    op,
                    getattr(self.tcfg, "live_execution_mode", "auto_trade"),
                    getattr(op, "signal_number", 1),
                )
            )
            events.extend(build_risk_overlay_events(self.tcfg.id, op))
            metadata = getattr(op, "divergence_metadata", None) or getattr(op, "signal_metadata", None)
            if isinstance(metadata, dict):
                events.append(build_macd_divergence_event(self.tcfg.id, int(getattr(op, "dtime", event_time)), metadata))
        return events
