"""Compatibility shim: strategy discovery now lives in the Backtrader catalog adapter."""

from trader.adapters.outbound.backtrader.catalog import (  # noqa: F401
    BacktraderStrategyCatalog,
    get_strategy_class_name,
    parse_strategies,
    parse_strategy,
)
