from __future__ import annotations

from abc import ABC, abstractmethod

from trader.execution.models import ExecutionResult, GatewayCapabilities, OrderIntent, ReconcileRequest, ReconcileResult, RiskIntent


class ExecutionGateway(ABC):
    @property
    def capabilities(self) -> GatewayCapabilities | None:
        return None

    @abstractmethod
    def open_position(self, intent: OrderIntent) -> ExecutionResult:
        raise NotImplementedError

    @abstractmethod
    def place_protection(self, intent: RiskIntent) -> ExecutionResult:
        raise NotImplementedError

    @abstractmethod
    def replace_protection(self, intent: RiskIntent) -> ExecutionResult:
        raise NotImplementedError

    @abstractmethod
    def close_position(self, intent: OrderIntent) -> ExecutionResult:
        raise NotImplementedError

    @abstractmethod
    def cancel_order(self, intent: OrderIntent) -> ExecutionResult:
        raise NotImplementedError

    @abstractmethod
    def reconcile(self, request: ReconcileRequest) -> ReconcileResult:
        raise NotImplementedError
