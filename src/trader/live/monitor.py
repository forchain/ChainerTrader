from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from dataclasses import asdict
from typing import Any

from trader.live.dashboard import (
    DashboardEvent,
    build_macd_divergence_event,
    build_risk_overlay_events,
    build_signal_marker_event,
    event_time_text,
    kline_to_chart_candle,
)
from trader.task.task_type import TaskType

DEFAULT_OVERLAYS = ["signals", "risk", "strategy_events"]


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


def _strategy_params(tcfg) -> dict[str, Any]:
    return dict(getattr(tcfg, "strategy_params", {}) or {})


def parameter_fingerprint(params: dict[str, Any]) -> str:
    if not params:
        return "default"
    payload = json.dumps(params, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:8]


def parameter_summary(params: dict[str, Any], max_items: int = 4) -> str:
    if not params:
        return "default"
    items = [f"{key}={value}" for key, value in sorted(params.items())]
    summary = ", ".join(items[:max_items])
    if len(items) > max_items:
        summary = f"{summary}, +{len(items) - max_items}"
    return summary


def _strategy_identity_fields(tcfg) -> dict[str, Any]:
    params = _strategy_params(tcfg)
    return {
        "task_id": tcfg.id,
        "param_id": getattr(tcfg, "param_id", None),
        "strategy_params": params,
        "parameter_fingerprint": parameter_fingerprint(params),
        "parameter_summary": parameter_summary(params),
    }


def build_live_strategy_summary(task) -> dict:
    tcfg = task.tcfg
    state = getattr(getattr(task, "ts", None), "state", None)
    return {
        "strategy_id": tcfg.id,
        "symbol": tcfg.symbol_interval.symbol(),
        "interval": tcfg.symbol_interval.interval.value,
        "strategy_name": tcfg.strategy_name(),
        "execution_mode": getattr(tcfg, "live_execution_mode", "auto_trade"),
        "live_trade_max_notional": getattr(tcfg, "live_trade_max_notional", 0.0),
        "requires_short_capability": getattr(tcfg, "requires_short_capability", False),
        "status": state.name if state is not None else "UNKNOWN",
        "task_name": task.name() if hasattr(task, "name") else f"{tcfg.id}.TRADER.{tcfg.symbol_interval.name()}",
        **_strategy_identity_fields(tcfg),
    }


def list_live_strategy_summaries(task_manager) -> list[dict]:
    tasks = getattr(task_manager, "tasks", {}) or {}
    summaries = []
    for task in tasks.values():
        if getattr(getattr(task, "tcfg", None), "ttype", None) != TaskType.TRADER:
            continue
        summaries.append(build_live_strategy_summary(task))
    return sorted(summaries, key=lambda item: item["strategy_id"])


async def build_initial_snapshot(task, db_manager, runtime_status: dict | None = None, limit: int = 500) -> dict:
    tcfg = task.tcfg
    state = getattr(getattr(task, "ts", None), "state", None)
    candles = []
    if db_manager is not None and getattr(db_manager, "kline", None) is not None:
        candles = await _maybe_await(db_manager.kline.get_latest_klines(tcfg.symbol_interval.name(), limit)) or []

    overlays = await build_snapshot_overlays(task, db_manager, candles)
    return {
        "strategy_id": tcfg.id,
        "market": tcfg.symbol_interval.symbol(),
        "interval": tcfg.symbol_interval.interval.value,
        "strategy_name": tcfg.strategy_name(),
        "execution_mode": getattr(tcfg, "live_execution_mode", "auto_trade"),
        "live_trade_max_notional": getattr(tcfg, "live_trade_max_notional", 0.0),
        "requires_short_capability": getattr(tcfg, "requires_short_capability", False),
        "candles": [kline_to_chart_candle(kline) for kline in candles],
        "runtime_status": runtime_status or {"state": state.name if state is not None else "UNKNOWN"},
        "enabled_overlays": list(DEFAULT_OVERLAYS),
        "overlays": overlays,
        "auto_execution_outcomes": await _task_auto_execution_outcomes(task, db_manager, candles),
        "history_window": {
            "limit": limit,
            "loaded": len(candles),
            "insufficient": len(candles) < limit,
        },
        **_strategy_identity_fields(tcfg),
    }


def _serialize_auto_execution_outcome(outcome) -> dict[str, Any]:
    if hasattr(outcome, "to_dict"):
        return outcome.to_dict()
    return dict(outcome)


async def _task_auto_execution_outcomes(task, db_manager, candles: list) -> list[dict[str, Any]]:
    ts = getattr(task, "ts", None)
    outcomes = list(getattr(ts, "auto_execution_outcomes", []) or [])
    if not outcomes:
        task_store = getattr(db_manager, "task", None) if db_manager is not None else None
        if task_store is not None:
            saved_task = await _maybe_await(task_store.get_task(task.tcfg.id))
            outcomes = list(getattr(saved_task, "auto_execution_outcomes", []) or []) if saved_task is not None else []

    serialized = []
    for outcome in outcomes:
        item = _serialize_auto_execution_outcome(outcome)
        signal_time = int(item.get("signal_time", 0) or 0)
        if candles and not (int(candles[0].open_time) <= signal_time <= int(candles[-1].open_time)):
            continue
        serialized.append(item)
    return serialized


async def _task_result_operations(task, db_manager) -> list:
    ts = getattr(task, "ts", None)
    tret = getattr(ts, "tret", None)
    if tret is not None:
        return list(getattr(tret, "opts", []) or [])

    task_store = getattr(db_manager, "task", None) if db_manager is not None else None
    if task_store is None:
        return []
    saved_task = await _maybe_await(task_store.get_task(task.tcfg.id))
    saved_result = getattr(saved_task, "tret", None) if saved_task is not None else None
    return list(getattr(saved_result, "opts", []) or [])


def _within_loaded_window(op, candles: list) -> bool:
    if not candles:
        return False
    start_time = int(candles[0].open_time)
    end_time = int(candles[-1].open_time)
    op_time = int(getattr(op, "dtime", 0) or 0)
    return start_time <= op_time <= end_time


async def build_snapshot_overlays(task, db_manager, candles: list) -> dict[str, list[dict[str, Any]]]:
    signals = []
    risk = []
    strategy_events = []
    mode = getattr(task.tcfg, "live_execution_mode", "auto_trade")
    signal_number = 0
    for op in await _task_result_operations(task, db_manager):
        if not _within_loaded_window(op, candles):
            continue
        signal_number += 1
        signals.append(build_signal_marker_event(task.tcfg.id, op, mode, signal_number).payload)
        risk.extend(event.payload for event in build_risk_overlay_events(task.tcfg.id, op))
        metadata = getattr(op, "divergence_metadata", None) or getattr(op, "signal_metadata", None)
        if isinstance(metadata, dict):
            event = build_macd_divergence_event(task.tcfg.id, int(getattr(op, "dtime", 0) or 0), metadata)
            strategy_events.append({"event_type": event.event_type, "event_time": event.event_time, **event.payload})
    return {
        "signals": signals,
        "risk": risk,
        "strategy_events": strategy_events,
    }


def serialize_dashboard_event(event: DashboardEvent) -> dict:
    payload = asdict(event)
    payload["event_time_text"] = event_time_text(event.event_time)
    return payload


class LiveEventSubscription:
    def __init__(self, bus: "LiveEventBus", strategy_id: int, queue: asyncio.Queue):
        self.bus = bus
        self.strategy_id = strategy_id
        self.queue = queue
        self._closed = False

    async def get(self) -> DashboardEvent:
        return await self.queue.get()

    async def unsubscribe(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self.bus.unsubscribe(self.strategy_id, self.queue)


class LiveEventBus:
    def __init__(self):
        self._subscribers: dict[int, set[asyncio.Queue]] = {}
        self._lock = asyncio.Lock()

    async def subscribe(self, strategy_id: int) -> LiveEventSubscription:
        queue: asyncio.Queue[DashboardEvent] = asyncio.Queue()
        async with self._lock:
            self._subscribers.setdefault(int(strategy_id), set()).add(queue)
        return LiveEventSubscription(self, int(strategy_id), queue)

    async def unsubscribe(self, strategy_id: int, queue: asyncio.Queue) -> None:
        async with self._lock:
            subscribers = self._subscribers.get(int(strategy_id))
            if not subscribers:
                return
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(int(strategy_id), None)

    async def publish(self, event: DashboardEvent) -> None:
        async with self._lock:
            subscribers = list(self._subscribers.get(int(event.strategy_id), set()))
        for queue in subscribers:
            await queue.put(event)


GLOBAL_LIVE_EVENT_BUS = LiveEventBus()
