from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import requests

from trader.adapters.inbound.cli.rendering import render_signal_table
from trader.adapters.outbound.backtrader.node import run_signal_scan_cerebro
from trader.adapters.outbound.binance.exchange import BinanceExchange
from trader.adapters.outbound.persistence.manager import DatabaseManager
from trader.common.config import Config, new_and_env
from trader.common.logger import Logger
from trader.core.exchange.domain import parse_exchange_config
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
from trader.core.shared.domain import Interval, Kline, SymbolInterval
from trader.strategy.strategy import parse_strategy
from trader.task.task_config import TaskConfig, create_task_id
from trader.task.task_type import TaskType
from trader.task.update_klines_task import UpdateKlinesTask

BINANCE_SPOT_API_BASE = "https://api.binance.com"


def fetch_top_usdt_symbols(
    top_n: int = 10,
    base_url: str = BINANCE_SPOT_API_BASE,
    timeout: float = 10.0,
) -> list[str]:
    exchange_info = requests.get(f"{base_url}/api/v3/exchangeInfo", timeout=timeout).json()
    return select_whitelist_usdt_symbols(exchange_info, top_n=top_n)


async def ensure_symbol_window(
    cfg: Config,
    log: Logger,
    db_manager: DatabaseManager,
    exchange: BinanceExchange,
    symbol: str,
    interval: Interval,
    start_time: int,
    end_time: int,
) -> None:
    normalized_symbol = normalize_symbol(symbol)
    task = UpdateKlinesTask(
        TaskConfig(
            id=create_task_id(0),
            ttype=TaskType.UPDATE_KLINES,
            symbol_interval=SymbolInterval(normalized_symbol, interval),
            start_time=start_time,
            end_time=end_time,
        ),
        cfg,
        log,
        db_manager,
        exchange,
    )
    await task.start(asyncio.Queue())


async def load_window_klines(
    db_manager: DatabaseManager,
    symbol: str,
    interval: Interval,
    start_time: int,
    end_time: int,
) -> list[Kline]:
    return await db_manager.kline.get_klines(SymbolInterval(normalize_symbol(symbol), interval).name(), start_time, end_time) or []


def run_strategy_triggered_signals(
    strategy_name: str,
    symbol: str,
    interval: Interval,
    klines: list[Kline],
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


async def scan_market(
    cfg: Config,
    log: Logger,
    db_manager: DatabaseManager,
    exchange: BinanceExchange,
    top_n: int = 10,
    strategy_name: str = "macd_triple_divergence",
    now_ts: int | None = None,
    strategy_warmup_bars: int = DEFAULT_STRATEGY_WARMUP_BARS,
) -> list[dict[str, Any]]:
    windows = compute_scan_windows(now_ts)
    symbols = fetch_top_usdt_symbols(top_n=top_n)
    results: list[dict[str, Any]] = []

    for symbol in symbols:
        for interval, (signal_start_time, signal_end_time) in windows.items():
            load_start_time, load_end_time = extend_window_for_warmup(
                interval,
                signal_start_time,
                signal_end_time,
                warmup_bars=strategy_warmup_bars,
            )
            await ensure_symbol_window(cfg, log, db_manager, exchange, symbol, interval, load_start_time, load_end_time)
            klines = await load_window_klines(db_manager, symbol, interval, load_start_time, load_end_time)
            if not klines:
                continue
            results.extend(
                run_strategy_triggered_signals(
                    strategy_name,
                    symbol,
                    interval,
                    klines,
                    cash=cfg.cash,
                    commission=cfg.commission,
                    signal_start_time=signal_start_time,
                    signal_end_time=signal_end_time,
                )
            )

    results.sort(key=lambda item: item["signal_time"])
    return results


async def scan_market_report(
    cfg: Config,
    log: Logger,
    db_manager: DatabaseManager,
    exchange: BinanceExchange,
    top_n: int = 10,
    strategy_name: str = "macd_triple_divergence",
    now_ts: int | None = None,
    strategy_warmup_bars: int = DEFAULT_STRATEGY_WARMUP_BARS,
) -> dict[str, Any]:
    windows = compute_scan_windows(now_ts)
    symbols = fetch_top_usdt_symbols(top_n=top_n)
    signals = await scan_market(
        cfg,
        log,
        db_manager,
        exchange,
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


def dump_signals_json(path: str | Path, payload: Any) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    return output


def build_runtime_config() -> tuple[Config, Logger, DatabaseManager, BinanceExchange]:
    cfg = new_and_env()
    if not cfg.exchange:
        raise ValueError("TRADER_EXCHANGE is required")
    if not cfg.db:
        raise ValueError("TRADER_DB is required")
    logger = Logger(cfg)
    db_manager = DatabaseManager(cfg, logger)
    db_manager.start()
    ex_cfg = parse_exchange_config(cfg.exchange)
    exchange = BinanceExchange(ex_cfg, logger.log())
    return cfg, logger, db_manager, exchange


__all__ = [
    "BINANCE_SPOT_API_BASE",
    "DEFAULT_STRATEGY_WARMUP_BARS",
    "DEFAULT_SYMBOL_WHITELIST",
    "LOCAL_TIMEZONE",
    "SCAN_INTERVALS",
    "STABLECOIN_BASE_ASSETS",
    "build_runtime_config",
    "build_scan_report",
    "compute_scan_windows",
    "dump_signals_json",
    "ensure_symbol_window",
    "extend_window_for_warmup",
    "extract_entry_signals",
    "fetch_top_usdt_symbols",
    "load_window_klines",
    "normalize_symbol",
    "render_signal_table",
    "run_strategy_triggered_signals",
    "scan_market",
    "scan_market_report",
    "select_top_usdt_symbols",
    "select_whitelist_usdt_symbols",
]
