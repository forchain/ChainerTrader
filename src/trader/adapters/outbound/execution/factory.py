"""Select the concrete execution gateway for a live execution mode."""

from __future__ import annotations

from typing import Any

from trader.adapters.outbound.binance.execution_gateway import BinanceLiveExecutionGateway
from trader.adapters.outbound.notification.execution_gateway import NotificationOnlyExecutionGateway
from trader.core.execution import ExecutionGateway
from trader.core.execution.modes import LiveExecutionMode


def build_execution_gateway(mode: str, exchange: Any) -> ExecutionGateway:
    if mode == LiveExecutionMode.MANUAL_NOTIFY.value:
        return NotificationOnlyExecutionGateway(staged_execution_mode=mode)
    return BinanceLiveExecutionGateway(exchange, staged_execution_mode=mode)
