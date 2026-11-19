"""Compatibility re-exports; the value lives in ``trader.core.strategy.domain.trader_result``."""

from trader.core.strategy.domain.trader_result import TraderResult, parse_trader_result

__all__ = ["TraderResult", "parse_trader_result"]
