"""Signal-scan orchestration over injected symbol, kline, and strategy-runner ports."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

from trader.core.optimization.domain import (
    DEFAULT_STRATEGY_WARMUP_BARS,
    build_scan_report,
    compute_scan_windows,
    extend_window_for_warmup,
)
from trader.core.shared.domain import Interval

SymbolSelector = Callable[[int], list[str]]
WindowPreparer = Callable[[str, Interval, int, int], Awaitable[None]]
KlineLoader = Callable[[str, Interval, int, int], Awaitable[list[Any]]]
SignalRunner = Callable[..., list[dict[str, Any]]]


async def scan_market(
    *,
    select_symbols: SymbolSelector,
    prepare_window: WindowPreparer,
    load_klines: KlineLoader,
    run_signals: SignalRunner,
    cash: float,
    commission: float,
    top_n: int = 10,
    strategy_name: str = "macd_triple_divergence",
    now_ts: int | None = None,
    strategy_warmup_bars: int = DEFAULT_STRATEGY_WARMUP_BARS,
) -> list[dict[str, Any]]:
    windows = compute_scan_windows(now_ts)
    symbols = select_symbols(top_n)
    results: list[dict[str, Any]] = []

    for symbol in symbols:
        for interval, (signal_start_time, signal_end_time) in windows.items():
            load_start_time, load_end_time = extend_window_for_warmup(
                interval,
                signal_start_time,
                signal_end_time,
                warmup_bars=strategy_warmup_bars,
            )
            await prepare_window(symbol, interval, load_start_time, load_end_time)
            klines = await load_klines(symbol, interval, load_start_time, load_end_time)
            if not klines:
                continue
            results.extend(
                run_signals(
                    strategy_name,
                    symbol,
                    interval,
                    klines,
                    cash=cash,
                    commission=commission,
                    signal_start_time=signal_start_time,
                    signal_end_time=signal_end_time,
                )
            )

    results.sort(key=lambda item: item["signal_time"])
    return results


async def scan_market_report(
    *,
    scan: Callable[..., Awaitable[list[dict[str, Any]]]],
    select_symbols: SymbolSelector,
    top_n: int = 10,
    strategy_name: str = "macd_triple_divergence",
    now_ts: int | None = None,
    strategy_warmup_bars: int = DEFAULT_STRATEGY_WARMUP_BARS,
) -> dict[str, Any]:
    windows = compute_scan_windows(now_ts)
    symbols = select_symbols(top_n)
    signals = await scan(
        top_n=top_n,
        strategy_name=strategy_name,
        now_ts=now_ts,
        strategy_warmup_bars=strategy_warmup_bars,
    )
    return build_scan_report(
        signals=signals,
        strategy_name=strategy_name,
        top_n=top_n,
        selected_symbols=symbols,
        windows=windows,
        generated_at_ts=now_ts,
    )
