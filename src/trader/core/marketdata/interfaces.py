"""Application ports for the market-data bounded context.

Persistence adapters implement :class:`KlineRepository` and
:class:`AvailabilityStore`; exchange adapters implement
:class:`MarketDataClient`; the market stream adapter implementation implements
:class:`MarketStreamPort`; file adapters implement :class:`DatasetFileStore`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Awaitable, Callable, Protocol, runtime_checkable

from trader.core.marketdata.domain import AvailabilityState
from trader.core.marketdata.stream import MarketStreamKey
from trader.core.marketdata.warmup import KlineUpdate
from trader.core.shared.domain import Kline, SymbolInterval

UpdateCallback = Callable[[KlineUpdate], Awaitable[None]]
DisconnectCallback = Callable[[], Awaitable[None]]


@runtime_checkable
class KlineRepository(Protocol):
    async def get_latest_kline(self, name: str) -> Kline | None: ...

    async def get_latest_klines(self, name: str, limit: int) -> list[Kline] | None: ...

    async def add_klines(
        self,
        name: str,
        klines: list[Kline],
        raw_payloads: list | None = None,
        source: str = "unknown",
    ) -> int: ...

    async def get_first_kline(self, name: str) -> Kline | None: ...

    async def get_kline(self, name: str, open_time: int) -> Kline | None: ...

    async def get_all_klines(self, name: str) -> list[Kline] | None: ...

    async def get_klines(self, name: str, start_time: int = 0, end_time: int = 0) -> list[Kline] | None: ...

    async def delete_klines_in_range(self, name: str, start_time: int, end_time: int) -> int: ...


@runtime_checkable
class AvailabilityStore(Protocol):
    async def get_state(self, exchange: str, symbol: str, interval: str) -> AvailabilityState | None: ...

    async def get_earliest_known_open_time(self, exchange: str, symbol: str, interval: str) -> int | None: ...

    async def get_cached_open_time_range(self, exchange: str, symbol: str, interval: str) -> tuple[int, int] | None: ...

    async def update_earliest_known_open_time(
        self,
        exchange: str,
        symbol: str,
        interval: str,
        earliest_known_open_time: int,
        source: str = "backward_fill",
    ) -> bool: ...

    async def update_cached_open_time_range(
        self,
        exchange: str,
        symbol: str,
        interval: str,
        cached_start_open_time: int,
        cached_end_open_time: int,
        source: str = "dataset_resolver",
    ) -> bool: ...


@runtime_checkable
class MarketDataClient(Protocol):
    def name(self) -> str: ...

    def get_klines(
        self,
        symbol_interval: SymbolInterval,
        start_time: int | None = None,
        end_time: int | None = None,
        limit: int = 500,
    ) -> list[Kline] | None: ...

    def get_latest_klines(self, symbol_interval: SymbolInterval, limit: int = 500) -> list[Kline] | None: ...

    def get_klines_by_end(self, symbol_interval: SymbolInterval, end_time: int, limit: int = 500) -> list[Kline] | None: ...

    def get_earliest_daily_archive_open_time(self, symbol_interval: SymbolInterval) -> int | None: ...


@runtime_checkable
class MarketStreamPort(Protocol):
    async def start(self, key: MarketStreamKey, on_update: UpdateCallback, on_disconnect: DisconnectCallback | None = None) -> None: ...

    async def stop(self, key: MarketStreamKey, reason: str = "") -> None: ...


@runtime_checkable
class DatasetFileStore(Protocol):
    def write_klines(self, path: Path, klines: list[Kline]) -> None: ...

    def count_klines(self, path: Path) -> int: ...

    def read_rows(self, path: Path) -> list[list[str]]: ...
