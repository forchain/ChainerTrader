from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

from trader.execution.models import ExecutionSide, OrderIntent, RiskIntent
from trader.utils.operate import OperateType


class OrderSemanticsError(ValueError):
    pass


@dataclass(frozen=True)
class OrderSemanticSelection:
    order: OrderIntent | None = None
    risk: RiskIntent | None = None


def select_order_semantics(
    op: Any,
    *,
    symbol: str,
    side: ExecutionSide | str,
    quantity: float,
    notional: float | None = None,
    trade_id: str | int | None = None,
    allow_native_protection: bool = True,
) -> OrderSemanticSelection:
    resolved_side = side if isinstance(side, ExecutionSide) else ExecutionSide(str(side))
    resolved_trade_id = str(trade_id or _trade_id_from_operation(op) or _intent_id(op))
    otype = getattr(op, "otype", None)

    if otype == OperateType.RISK_UPDATE or getattr(op, "breakeven_new_stop", None) is not None:
        stop_price = _first_number(getattr(op, "breakeven_new_stop", None), getattr(op, "stop_loss", None), getattr(op, "price", None))
        if stop_price is None:
            raise OrderSemanticsError("breakeven replacement requires stop_price")
        if not allow_native_protection:
            raise OrderSemanticsError("stop replacement requires native protection")
        return OrderSemanticSelection(
            risk=RiskIntent.replace_stop(
                intent_id=f"risk:{_intent_id(op)}",
                operation_id=_operation_id(op),
                symbol=symbol,
                side=resolved_side,
                trade_id=resolved_trade_id,
                quantity=quantity,
                stop_price=stop_price,
                replacement_of_order_id=getattr(op, "protection_order_id", None),
                signal_event_id=getattr(op, "signal_event_id", None),
                metadata=_metadata_from_operation(op),
            )
        )

    order = _order_intent(op, symbol=symbol, side=resolved_side, quantity=quantity, notional=notional, trade_id=resolved_trade_id)
    stop_price = _stop_price_from_operation(op)
    take_profit_price = _take_profit_price_from_operation(op)
    if stop_price is None and take_profit_price is None:
        return OrderSemanticSelection(order=order)

    if not allow_native_protection:
        raise OrderSemanticsError("stop-loss/take-profit semantics requires native protection")

    validate_protection_prices(
        resolved_side,
        entry_price=_first_number(getattr(op, "price", None)),
        stop_price=stop_price,
        take_profit_price=take_profit_price,
    )
    return OrderSemanticSelection(
        order=order,
        risk=RiskIntent.place_protection(
            intent_id=f"risk:{_intent_id(op)}",
            operation_id=_operation_id(op),
            symbol=symbol,
            side=resolved_side,
            trade_id=resolved_trade_id,
            quantity=quantity,
            stop_price=stop_price,
            take_profit_price=take_profit_price,
            signal_event_id=getattr(op, "signal_event_id", None),
            metadata=_metadata_from_operation(op),
        ),
    )


def validate_protection_prices(
    side: ExecutionSide | str,
    *,
    entry_price: float | None,
    stop_price: float | None,
    take_profit_price: float | None,
) -> None:
    resolved_side = side if isinstance(side, ExecutionSide) else ExecutionSide(str(side))
    entry = _validated_positive(entry_price, "entry_price") if entry_price is not None else None
    stop = _validated_positive(stop_price, "stop_price") if stop_price is not None else None
    take_profit = _validated_positive(take_profit_price, "take_profit_price") if take_profit_price is not None else None
    if entry is None:
        return
    if resolved_side == ExecutionSide.LONG:
        if stop is not None and stop >= entry:
            raise OrderSemanticsError("long stop_price must be below entry_price")
        if take_profit is not None and take_profit <= entry:
            raise OrderSemanticsError("long take_profit_price must be above entry_price")
    else:
        if stop is not None and stop <= entry:
            raise OrderSemanticsError("short stop_price must be above entry_price")
        if take_profit is not None and take_profit >= entry:
            raise OrderSemanticsError("short take_profit_price must be below entry_price")


def _order_intent(
    op: Any,
    *,
    symbol: str,
    side: ExecutionSide,
    quantity: float,
    notional: float | None,
    trade_id: str,
) -> OrderIntent | None:
    otype = getattr(op, "otype", None)
    common = {
        "intent_id": _intent_id(op),
        "operation_id": _operation_id(op),
        "symbol": symbol,
        "side": side,
        "quantity": quantity,
        "notional": notional,
        "price": _first_number(getattr(op, "price", None)),
        "trade_id": trade_id,
        "signal_event_id": getattr(op, "signal_event_id", None),
        "metadata": _metadata_from_operation(op),
    }
    if otype in (OperateType.BUY, OperateType.LONG, OperateType.SHORT):
        return OrderIntent.entry(**common)
    if otype in (OperateType.SELL, OperateType.CLOSE):
        return OrderIntent.close(**common)
    return None


def _stop_price_from_operation(op: Any) -> float | None:
    metadata = _metadata_from_operation(op)
    framework_trade = metadata.get("framework_trade") if isinstance(metadata.get("framework_trade"), dict) else {}
    signal_metadata = metadata.get("signal_metadata") if isinstance(metadata.get("signal_metadata"), dict) else {}
    return _first_number(
        getattr(op, "stop_loss", None),
        framework_trade.get("stop_price"),
        framework_trade.get("initial_stop_price"),
        signal_metadata.get("suggested_stop_price"),
    )


def _take_profit_price_from_operation(op: Any) -> float | None:
    metadata = _metadata_from_operation(op)
    framework_trade = metadata.get("framework_trade") if isinstance(metadata.get("framework_trade"), dict) else {}
    return _first_number(getattr(op, "take_profit", None), framework_trade.get("take_profit"))


def _validated_positive(value: float | None, name: str) -> float:
    number = float(value)
    if number <= 0 or not isfinite(number):
        raise OrderSemanticsError(f"{name} must be positive and finite")
    return number


def _first_number(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        number = float(value)
        if number > 0 and isfinite(number):
            return number
    return None


def _intent_id(op: Any) -> str:
    signal_event_id = getattr(op, "signal_event_id", None)
    if signal_event_id:
        return f"intent:{signal_event_id}"
    return f"intent:{getattr(getattr(op, 'otype', None), 'name', 'UNKNOWN')}:{int(getattr(op, 'dtime', 0) or 0)}"


def _operation_id(op: Any) -> str:
    signal_event_id = getattr(op, "signal_event_id", None)
    if signal_event_id:
        return str(signal_event_id)
    side = getattr(getattr(op, "otype", None), "name", "UNKNOWN")
    dtime = int(getattr(op, "dtime", 0) or 0)
    price = float(getattr(op, "price", 0.0) or 0.0)
    return f"{side}:{dtime}:{price:.12g}"


def _trade_id_from_operation(op: Any) -> str | None:
    framework_trade = getattr(op, "framework_trade", None)
    if isinstance(framework_trade, dict) and framework_trade.get("trade_id") is not None:
        return str(framework_trade["trade_id"])
    return None


def _metadata_from_operation(op: Any) -> dict[str, Any]:
    payload = dict(op.to_dict()) if hasattr(op, "to_dict") else {}
    for name in ("signal_metadata", "divergence_metadata", "framework_trade"):
        if hasattr(op, name):
            payload[name] = getattr(op, name)
    return payload
