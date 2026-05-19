from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from trader.live.market_data import KlineUpdate
from trader.utils.kline import Kline


@dataclass(frozen=True)
class DashboardEvent:
    event_type: str
    strategy_id: int
    event_time: int
    payload: dict[str, Any] = field(default_factory=dict)


def event_time_text(event_time: int | float | None) -> str:
    if event_time is None:
        return ""
    return datetime.fromtimestamp(int(event_time)).strftime("%Y-%m-%d %H:%M:%S")


def _op_attr(op, name, default=None):
    if isinstance(op, dict):
        if name == "dtime":
            return op.get("dtime") or op.get("datetime") or default
        if name == "otype":
            val = op.get("otype") or op.get("type")
            if isinstance(val, str):
                from trader.utils.operate import OperateType
                try:
                    return OperateType[val]
                except KeyError:
                    return val
            return val
        return op.get(name, default)
    return getattr(op, name, default)


def kline_to_chart_candle(kline: Kline) -> dict[str, float | int]:
    return {
        "time": int(kline.open_time),
        "time_text": event_time_text(kline.open_time),
        "open": float(kline.open),
        "high": float(kline.high),
        "low": float(kline.low),
        "close": float(kline.close),
        "volume": float(kline.volume),
    }


def kline_update_event(strategy_id: int, update: KlineUpdate) -> DashboardEvent:
    return DashboardEvent(
        event_type="kline_update",
        strategy_id=strategy_id,
        event_time=update.event_time,
        payload={
            "market": update.symbol,
            "interval": update.interval,
            "closed": update.is_closed,
            "event_time_text": event_time_text(update.event_time),
            "candle": {
                **update.to_chart_candle(),
                "time_text": event_time_text(update.open_time),
                "close_time": update.close_time,
                "close_time_text": event_time_text(update.close_time),
            },
        },
    )


def _operation_payload(op) -> dict:
    payload = op.to_dict() if hasattr(op, "to_dict") else dict(op)
    if payload.get("datetime") is not None:
        payload["datetime_text"] = event_time_text(payload["datetime"])
    if payload.get("time") is not None:
        payload["time_text"] = event_time_text(payload["time"])
    if payload.get("event_time") is not None:
        payload["event_time_text"] = event_time_text(payload["event_time"])
    return payload


def strategy_execution_event(strategy_id: int, event_time: int, result, operations: list | None = None) -> DashboardEvent:
    opts = []
    for op in operations if operations is not None else getattr(result, "opts", []) or []:
        opts.append(_operation_payload(op))
    return DashboardEvent(
        event_type="strategy_execution",
        strategy_id=strategy_id,
        event_time=event_time,
        payload={
            "event_time_text": event_time_text(event_time),
            "has_signal": bool(opts),
            "operations": opts,
        },
    )


def notification_event(strategy_id: int, event_time: int, notifications: list[Any]) -> DashboardEvent:
    return DashboardEvent(
        event_type="notification",
        strategy_id=strategy_id,
        event_time=event_time,
        payload={
            "count": len(notifications),
            "events": [event.to_dict() if hasattr(event, "to_dict") else event for event in notifications],
        },
    )


def runtime_status_event(strategy_id: int, event_time: int, status: dict[str, Any]) -> DashboardEvent:
    return DashboardEvent(
        event_type="runtime_status",
        strategy_id=strategy_id,
        event_time=int(event_time),
        payload={
            **status,
            "event_time_text": event_time_text(event_time),
        },
    )


def ensure_signal_tracking(strategy_id: int, op, signal_number: int = 1) -> tuple[str, int]:
    otype = _op_attr(op, "otype")
    side = otype.name if hasattr(otype, "name") else str(otype or "UNKNOWN")
    existing_number = _op_attr(op, "signal_number")
    number = int(existing_number) if existing_number is not None else int(signal_number)
    signal_event_id = _op_attr(op, "signal_event_id")
    if not signal_event_id:
        metadata = _op_attr(op, "divergence_metadata") or _op_attr(op, "signal_metadata")
        if isinstance(metadata, dict):
            signal_event_id = metadata.get("signal_event_id") or metadata.get("event_id")
    if not signal_event_id:
        dtime = _op_attr(op, "dtime") or 0
        signal_event_id = f"live-{int(strategy_id)}-{int(dtime)}-{side}-{number}"
        if not isinstance(op, dict):
            setattr(op, "signal_event_id", signal_event_id)
    if not isinstance(op, dict):
        setattr(op, "signal_number", number)
    return signal_event_id, number


def build_signal_marker_event(strategy_id: int, op, mode: str, signal_number: int = 1) -> DashboardEvent:
    signal_event_id, number = ensure_signal_tracking(strategy_id, op, signal_number)
    dtime = _op_attr(op, "dtime") or 0
    otype = _op_attr(op, "otype")
    return DashboardEvent(
        event_type="signal_marker",
        strategy_id=strategy_id,
        event_time=int(dtime),
        payload={
            "time": int(dtime),
            "time_text": event_time_text(dtime),
            "price": float(_op_attr(op, "price") or 0.0),
            "side": otype.name if hasattr(otype, "name") else str(otype or "UNKNOWN"),
            "mode": mode,
            "trigger_reason": _op_attr(op, "trigger_reason", "signal"),
            "signal_event_id": signal_event_id,
            "signal_number": number,
        },
    )


def build_risk_overlay_events(strategy_id: int, op) -> list[DashboardEvent]:
    events: list[DashboardEvent] = []
    dtime = _op_attr(op, "dtime") or 0
    event_time = int(dtime)
    stop_loss = _op_attr(op, "stop_loss")
    take_profit = _op_attr(op, "take_profit")
    risk_reward_ratio = _op_attr(op, "risk_reward_ratio")
    stop_source = "local_strategy_reference"
    framework_trade = _op_attr(op, "framework_trade")
    if isinstance(framework_trade, dict):
        if stop_loss is None:
            stop_loss = framework_trade.get("stop_price") or framework_trade.get("initial_stop_price")
            stop_source = "framework_trade_context"
        if take_profit is None:
            take_profit = framework_trade.get("take_profit")
        if risk_reward_ratio is None:
            risk_reward_ratio = framework_trade.get("risk_reward_ratio")

    metadata = _op_attr(op, "divergence_metadata") or _op_attr(op, "signal_metadata")
    if stop_loss is None and isinstance(metadata, dict):
        stop_loss = metadata.get("suggested_stop_price")
        stop_source = "signal_metadata"

    if stop_loss is not None:
        events.append(
            DashboardEvent(
                event_type="risk_overlay",
                strategy_id=strategy_id,
                event_time=event_time,
                payload={
                    "time_text": event_time_text(event_time),
                    "overlay_type": "stop_loss",
                    "price": float(stop_loss),
                    "initial_price": float(framework_trade["initial_stop_price"])
                    if isinstance(framework_trade, dict) and framework_trade.get("initial_stop_price") is not None
                    else None,
                    "source": stop_source,
                },
            )
        )

    if take_profit is not None:
        events.append(
            DashboardEvent(
                event_type="risk_overlay",
                strategy_id=strategy_id,
                event_time=event_time,
                payload={
                    "time_text": event_time_text(event_time),
                    "overlay_type": "take_profit",
                    "price": float(take_profit),
                    "risk_reward_ratio": float(risk_reward_ratio) if risk_reward_ratio is not None else None,
                    "source": "local_strategy_reference",
                },
            )
        )

    old_stop = _op_attr(op, "breakeven_old_stop")
    new_stop = _op_attr(op, "breakeven_new_stop")
    if old_stop is not None and new_stop is not None:
        events.append(
            DashboardEvent(
                event_type="risk_overlay",
                strategy_id=strategy_id,
                event_time=event_time,
                payload={
                    "time_text": event_time_text(event_time),
                    "overlay_type": "breakeven_move",
                    "price": float(new_stop),
                    "old_stop": float(old_stop),
                    "new_stop": float(new_stop),
                    "step": _op_attr(op, "breakeven_step"),
                    "source": "local_strategy_reference",
                },
            )
        )

    return events


def build_macd_divergence_event(strategy_id: int, event_time: int, metadata: dict[str, Any]) -> DashboardEvent:
    return DashboardEvent(
        event_type="macd_divergence",
        strategy_id=strategy_id,
        event_time=int(event_time),
        payload={
            "time_text": event_time_text(event_time),
            "signal_event_id": metadata.get("signal_event_id") or metadata.get("event_id"),
            "direction": metadata.get("direction"),
            "legs": metadata.get("legs", []),
            "conditions": metadata.get("conditions", {}),
            "metadata": metadata,
        },
    )
