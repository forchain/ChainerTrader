"""Application ports for the exchange bounded context.

Outbound adapters (ccxt and native Binance) implement :class:`ExchangeClient`;
persistence adapters implement :class:`ExchangeCredentialRepository`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from trader.core.exchange.domain import Balance, ExchangeConfig, PositionView, ProtectionOrderView
from trader.core.shared.domain import Kline, OperateType, Symbol, SymbolInterval


@runtime_checkable
class ExchangeClient(Protocol):
    def name(self) -> str: ...

    def driver_name(self) -> str: ...

    def start(self) -> Any: ...

    def stop(self) -> Any: ...

    def bind_order_context(self, task_id: int | None = None, strategy_name: str | None = None) -> None: ...

    def ping(self) -> bool: ...

    def time(self) -> datetime | None: ...

    def server_datetime(self) -> datetime | None: ...

    def server_time_offset(self) -> float | None: ...

    def exchange_info(self, symbol: str | None = None) -> Any: ...

    def get_klines(
        self,
        si: SymbolInterval,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 500,
    ) -> list[Kline] | None: ...

    def get_latest_klines(self, si: SymbolInterval, limit: int = 500) -> list[Kline] | None: ...

    def get_klines_by_end(self, si: SymbolInterval, end_time: int, limit: int = 500) -> list[Kline] | None: ...

    def get_klines_by_start(self, si: SymbolInterval, start_time: int | None = None, limit: int = 500) -> list[Kline] | None: ...

    def get_account(self) -> Any: ...

    def get_account_balance(self, asset: str) -> float: ...

    def get_account_balances(self) -> list[Balance]: ...

    def get_position_view(self, symbol: Symbol) -> list[PositionView]: ...

    def account_commission(self, symbol: str | None = None) -> Any: ...

    def get_account_commission(self, symbol: str) -> float | None: ...

    def new_order(self, symbol: Symbol, op: OperateType, quantity: float = 0) -> Any: ...

    def new_margin_order(self, symbol: Symbol, op: OperateType, quantity: float = 0) -> Any: ...

    def new_stop_order(self, symbol: Symbol, op: OperateType, quantity: float, stop_price: float) -> Any: ...

    def new_take_profit_order(self, symbol: Symbol, op: OperateType, quantity: float, limit_price: float) -> Any: ...

    def new_oco_order(self, symbol: Symbol, op: OperateType, quantity: float, stop_price: float, take_profit_price: float) -> Any: ...

    def replace_stop_order(self, symbol: Symbol, op: OperateType, order_id: str, quantity: float, stop_price: float) -> Any: ...

    def cancel_order(self, symbol: Symbol, order_id: str) -> Any: ...

    def delete_order(self, symbol: str) -> Any: ...

    def cancel_all_open_orders(self, symbol: Symbol) -> Any: ...

    def get_open_orders(self, symbol: Symbol) -> list[Any]: ...

    def get_all_open_orders(self) -> list[Any]: ...

    def get_open_protection_orders(self, symbol: Symbol) -> list[ProtectionOrderView]: ...

    def verify_order_ids(self, symbol: Symbol, order_ids: list[str]) -> bool: ...

    def get_max_borrowable(self, asset: str, symbol: str | None = None) -> dict[str, Any]: ...

    def is_cross_margin_ready(self) -> bool: ...

    def get_earliest_daily_archive_open_time(self, symbol_interval: SymbolInterval) -> int | None: ...


@dataclass(frozen=True)
class ExchangeCredential:
    id: int | None
    user_id: int
    exchange: str
    label: str
    encrypted_api_key: str
    encrypted_api_secret: str
    masked_api_key: str = ""


@runtime_checkable
class ExchangeCredentialRepository(Protocol):
    async def upsert_default(
        self,
        user_id: int,
        *,
        exchange: str,
        encrypted_api_key: str,
        encrypted_api_secret: str,
        masked_api_key: str,
    ) -> ExchangeCredential: ...

    async def get_default(self, user_id: int, exchange: str) -> ExchangeCredential | None: ...

    async def list_by_user(self, user_id: int) -> list[ExchangeCredential]: ...

    async def delete_for_user(self, credential_id: int, user_id: int) -> bool: ...


@runtime_checkable
class ExchangeFactory(Protocol):
    """Port for constructing an exchange client from an exchange config."""

    def __call__(self, exchange_cfg: ExchangeConfig, log: Any = None) -> ExchangeClient: ...


@runtime_checkable
class CredentialConnectivityValidator(Protocol):
    """Port for validating user-supplied exchange credential connectivity."""

    def __call__(
        self,
        base_cfg: ExchangeConfig | None,
        exchange_name: str,
        api_key: str,
        api_secret: str,
    ) -> str | None: ...
