from __future__ import annotations

from trader.core.execution import (
    ExecutionResult,
    GatewayCapabilities,
    GatewayCapability,
    GatewayMode,
    OrderIntent,
    ReconcileRequest,
    ReconcileResult,
    RiskIntent,
)
from trader.core.execution.interfaces import ExecutionGateway


class NotificationOnlyExecutionGateway(ExecutionGateway):
    """`manual_notify` gateway: every order operation reports unsupported and never reaches an exchange."""

    def __init__(self, *, staged_execution_mode: str = "manual_notify"):
        self.staged_execution_mode = staged_execution_mode

    @property
    def capabilities(self) -> GatewayCapabilities:
        return GatewayCapabilities(gateway=GatewayMode.NOTIFICATION_ONLY, supported=set())

    def open_position(self, intent: OrderIntent) -> ExecutionResult:
        return self._unsupported(intent, GatewayCapability.MARKET_ENTRY)

    def place_protection(self, intent: RiskIntent) -> ExecutionResult:
        return self._unsupported(intent, GatewayCapability.PROTECTIVE_STOP)

    def replace_protection(self, intent: RiskIntent) -> ExecutionResult:
        return self._unsupported(intent, GatewayCapability.BREAKEVEN_REPLACEMENT)

    def close_position(self, intent: OrderIntent) -> ExecutionResult:
        return self._unsupported(intent, GatewayCapability.MARKET_CLOSE)

    def cancel_order(self, intent: OrderIntent) -> ExecutionResult:
        return self._unsupported(intent, GatewayCapability.CANCEL_ORDER)

    def reconcile(self, request: ReconcileRequest) -> ReconcileResult:
        return ReconcileResult(request=request)

    @staticmethod
    def _unsupported(intent: OrderIntent | RiskIntent, capability: GatewayCapability) -> ExecutionResult:
        return ExecutionResult.unsupported(
            intent_id=intent.intent_id,
            operation_id=intent.operation_id,
            capability=capability,
            gateway=GatewayMode.NOTIFICATION_ONLY,
        )
