"""CLI glue for the top-volume signal scanner: HTTP symbol lookup, DB window reads, and output."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import requests

from trader.core.optimization.domain import (
    DEFAULT_SIGNAL_WHITELIST as DEFAULT_SYMBOL_WHITELIST,
)
from trader.core.optimization.domain import (
    DEFAULT_STRATEGY_WARMUP_BARS,
    LOCAL_TIMEZONE,
    SCAN_INTERVALS,
    STABLECOIN_BASE_ASSETS,
    build_scan_report,
    compute_scan_windows,
    extend_window_for_warmup,
    extract_entry_signals,
    select_top_usdt_symbols,
    select_whitelist_usdt_symbols,
)
from trader.core.optimization.domain import (
    normalize_scanner_symbol as normalize_symbol,
)
from trader.core.optimization.use_cases.signal_scanner import scan_market as _scan_market
from trader.core.optimization.use_cases.signal_scanner import scan_market_report as _scan_market_report
from trader.core.shared.domain import Interval, Kline, SymbolInterval
from trader.core.task.use_cases.data_tasks import UpdateKlinesTaskRunner
from trader.task.task_config import TaskConfig, create_task_id
from trader.task.task_type import TaskType

BINANCE_SPOT_API_BASE = "https://api.binance.com"


def fetch_top_usdt_symbols(
    top_n: int = 10,
    base_url: str = BINANCE_SPOT_API_BASE,
    timeout: float = 10.0,
) -> list[str]:
    exchange_info = requests.get(f"{base_url}/api/v3/exchangeInfo", timeout=timeout).json()
    return select_whitelist_usdt_symbols(exchange_info, top_n=top_n)


async def ensure_symbol_window(
    cfg: Any,
    log: Any,
    db_manager: Any,
    exchange: Any,
    symbol: str,
    interval: Interval,
    start_time: int,
    end_time: int,
) -> None:
    normalized_symbol = normalize_symbol(symbol)
    task_config = TaskConfig(
        id=create_task_id(0),
        ttype=TaskType.UPDATE_KLINES,
        symbol_interval=SymbolInterval(normalized_symbol, interval),
        start_time=start_time,
        end_time=end_time,
    )
    runner = UpdateKlinesTaskRunner(
        kline_repository=db_manager.kline,
        market_data_client=exchange,
        availability_store=getattr(db_manager, "availability", None),
        task_repository=getattr(db_manager, "task", None),
        log=log,
    )
    await runner.run(task_config, quit_event=asyncio.Event())


async def load_window_klines(
    db_manager: Any,
    symbol: str,
    interval: Interval,
    start_time: int,
    end_time: int,
) -> list[Kline]:
    return await db_manager.kline.get_klines(SymbolInterval(normalize_symbol(symbol), interval).name(), start_time, end_time) or []


async def scan_market(
    cfg: Any,
    log: Any,
    db_manager: Any,
    exchange: Any,
    *,
    run_signals: Any,
    top_n: int = 10,
    strategy_name: str = "macd_triple_divergence",
    now_ts: int | None = None,
    strategy_warmup_bars: int = DEFAULT_STRATEGY_WARMUP_BARS,
) -> list[dict[str, Any]]:
    return await _scan_market(
        select_symbols=lambda count: fetch_top_usdt_symbols(top_n=count),
        prepare_window=lambda symbol, interval, start, end: ensure_symbol_window(cfg, log, db_manager, exchange, symbol, interval, start, end),
        load_klines=lambda symbol, interval, start, end: load_window_klines(db_manager, symbol, interval, start, end),
        run_signals=run_signals,
        cash=cfg.cash,
        commission=cfg.commission,
        top_n=top_n,
        strategy_name=strategy_name,
        now_ts=now_ts,
        strategy_warmup_bars=strategy_warmup_bars,
    )


async def scan_market_report(
    cfg: Any,
    log: Any,
    db_manager: Any,
    exchange: Any,
    *,
    run_signals: Any,
    top_n: int = 10,
    strategy_name: str = "macd_triple_divergence",
    now_ts: int | None = None,
    strategy_warmup_bars: int = DEFAULT_STRATEGY_WARMUP_BARS,
) -> dict[str, Any]:
    return await _scan_market_report(
        scan=lambda **kwargs: scan_market(cfg, log, db_manager, exchange, run_signals=run_signals, **kwargs),
        select_symbols=lambda count: fetch_top_usdt_symbols(top_n=count),
        top_n=top_n,
        strategy_name=strategy_name,
        now_ts=now_ts,
        strategy_warmup_bars=strategy_warmup_bars,
    )


def dump_signals_json(path: str | Path, payload: Any) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return output


__all__ = [
    "BINANCE_SPOT_API_BASE",
    "DEFAULT_STRATEGY_WARMUP_BARS",
    "DEFAULT_SYMBOL_WHITELIST",
    "LOCAL_TIMEZONE",
    "SCAN_INTERVALS",
    "STABLECOIN_BASE_ASSETS",
    "build_scan_report",
    "compute_scan_windows",
    "dump_signals_json",
    "ensure_symbol_window",
    "extend_window_for_warmup",
    "extract_entry_signals",
    "fetch_top_usdt_symbols",
    "load_window_klines",
    "normalize_symbol",
    "scan_market",
    "scan_market_report",
    "select_top_usdt_symbols",
    "select_whitelist_usdt_symbols",
]
