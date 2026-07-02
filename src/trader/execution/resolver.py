from __future__ import annotations

from dataclasses import dataclass

from trader.execution.models import GatewayMode


class GatewayResolutionError(ValueError):
    pass


@dataclass(frozen=True)
class ResolvedExecutionGateway:
    staged_execution_mode: str
    gateway_mode: GatewayMode
    can_submit_orders: bool
    requested_gateway: GatewayMode | None = None
    max_notional: float | None = None
    requires_live_order_cap: bool = False


MANUAL_NOTIFY = "manual_notify"
AUTO_TRADE = "auto_trade"
SUPPORTED_STAGED_EXECUTION_MODES = {MANUAL_NOTIFY, AUTO_TRADE}


def _normalize_requested_gateway(value: GatewayMode | str | None) -> GatewayMode | None:
    if value is None:
        return None
    if isinstance(value, GatewayMode):
        return value
    return GatewayMode(str(value).strip().lower())


def resolve_execution_gateway(
    *,
    live_execution_mode: str | object | None,
    requested_gateway: GatewayMode | str | None = None,
    live_trade_max_notional: float | None = None,
) -> ResolvedExecutionGateway:
    mode = _normalize_live_execution_mode(live_execution_mode)
    requested = _normalize_requested_gateway(requested_gateway)

    if mode == MANUAL_NOTIFY:
        return _resolve_expected(mode, GatewayMode.NOTIFICATION_ONLY, requested, can_submit_orders=False)

    if mode == AUTO_TRADE:
        max_notional = float(live_trade_max_notional or 0.0)
        return _resolve_expected(
            mode,
            GatewayMode.BINANCE_LIVE,
            requested,
            can_submit_orders=True,
            max_notional=max_notional if max_notional > 0 else None,
            requires_live_order_cap=max_notional > 0,
        )

    raise GatewayResolutionError(f"unsupported live_execution_mode={mode}")


def _normalize_live_execution_mode(value: str | object | None) -> str:
    raw = getattr(value, "value", value)
    mode = str(raw or AUTO_TRADE).strip().lower()
    if mode not in SUPPORTED_STAGED_EXECUTION_MODES:
        raise GatewayResolutionError(f"unsupported live_execution_mode={raw}")
    return mode


def _resolve_expected(
    mode: str,
    expected: GatewayMode,
    requested: GatewayMode | None,
    *,
    can_submit_orders: bool,
    max_notional: float | None = None,
    requires_live_order_cap: bool = False,
) -> ResolvedExecutionGateway:
    if requested is not None and requested != expected:
        raise GatewayResolutionError(f"requested gateway {requested.value} conflicts with live_execution_mode={mode}")
    return ResolvedExecutionGateway(
        staged_execution_mode=mode,
        gateway_mode=expected,
        requested_gateway=requested,
        can_submit_orders=can_submit_orders,
        max_notional=max_notional,
        requires_live_order_cap=requires_live_order_cap,
    )
