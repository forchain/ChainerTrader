"""Ports for strategy discovery and parameter defaults."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class StrategyLoader(Protocol):
    def load(self, strategy_names: list[str]) -> list[Any] | None: ...
    def load_one(self, strategy_name: str) -> Any | None: ...


@runtime_checkable
class StrategyCatalog(Protocol):
    def list_options(self) -> list[str]: ...
    def param_defaults(self, strategy_name: str) -> dict[str, Any]: ...
