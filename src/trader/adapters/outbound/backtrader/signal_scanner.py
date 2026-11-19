"""Backtrader-backed signal scan runner."""

from __future__ import annotations

from typing import Any

from trader.adapters.outbound.backtrader.catalog import parse_strategy
from trader.adapters.outbound.backtrader.node import run_signal_scan_cerebro
from trader.core.optimization.domain import extract_entry_signals


def run_strategy_triggered_signals(
    strategy_name: str,
    symbol: str,
    interval: Any,
    klines: list[Any],
    cash: float = 100000.0,
    commission: float = 0.001,
    signal_start_time: int | None = None,
    signal_end_time: int | None = None,
) -> list[dict[str, Any]]:
    strategy_cls = parse_strategy(strategy_name)
    if strategy_cls is None:
        raise ValueError(f"Unsupported strategy: {strategy_name}")

    events = run_signal_scan_cerebro(strategy_cls, klines, cash=cash, commission=commission)
    return extract_entry_signals(
        events,
        symbol=symbol,
        interval=interval.value,
        strategy_name=strategy_name,
        start_time=signal_start_time,
        end_time=signal_end_time,
    )


class BacktraderSignalScanRunner:
    """Adapter implementing :class:`trader.core.optimization.interfaces.SignalScanRunner`."""

    def scan(self, strategy_name, symbol, interval, klines, *, cash=100000.0, commission=0.001, signal_start_time=None, signal_end_time=None):
        return run_strategy_triggered_signals(
            strategy_name,
            symbol,
            interval,
            klines,
            cash=cash,
            commission=commission,
            signal_start_time=signal_start_time,
            signal_end_time=signal_end_time,
        )
