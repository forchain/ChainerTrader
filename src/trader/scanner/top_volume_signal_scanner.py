from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import backtrader as bt
import requests
from prettytable import PrettyTable

from trader.common.config import Config, new_and_env
from trader.common.logger import Logger
from trader.database.manager import DatabaseManager
from trader.exchange.binance.data import BinanceData
from trader.exchange.binance.exchange import BinanceExchange
from trader.exchange.exchange_config import parse_exchange_config
from trader.strategy.strategy import parse_strategy
from trader.task.task_config import TaskConfig, create_task_id
from trader.task.task_type import TaskType
from trader.task.update_klines_task import UpdateKlinesTask
from trader.utils.kline import Kline
from trader.utils.symbol_interval import Interval, SymbolInterval, get_time_duration

BINANCE_SPOT_API_BASE = "https://api.binance.com"
DEFAULT_SYMBOL_WHITELIST = (
    "BTC",
    "ETH",
    "BNB",
    "XRP",
    "SOL",
    "TRX",
    "DOGE",
    "ADA",
    "BCH",
    "XLM",
)
STABLECOIN_BASE_ASSETS = frozenset(
    {
        "USDT",
        "USDC",
        "BUSD",
        "FDUSD",
        "TUSD",
        "USDP",
        "DAI",
        "USD1",
        "USDE",
        "USDS",
        "PYUSD",
    }
)
SCAN_INTERVALS = (Interval.INTERVAL_1d, Interval.INTERVAL_1h)
DEFAULT_STRATEGY_WARMUP_BARS = 200
LOCAL_TIMEZONE = datetime.now().astimezone().tzinfo or UTC


def normalize_symbol(symbol: str) -> str:
    if "-" in symbol:
        return symbol
    if symbol.endswith("USDT") and len(symbol) > len("USDT"):
        return f"{symbol[:-4]}-USDT"
    return symbol


def _exchange_info_symbols(exchange_info: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(exchange_info, dict):
        return list(exchange_info.get("symbols", []))
    return list(exchange_info)


def select_whitelist_usdt_symbols(
    exchange_info: dict[str, Any] | list[dict[str, Any]],
    whitelist_bases: tuple[str, ...] | list[str] = DEFAULT_SYMBOL_WHITELIST,
    top_n: int = 10,
    stablecoin_bases: set[str] | frozenset[str] = STABLECOIN_BASE_ASSETS,
) -> list[str]:
    symbols_by_base: dict[str, str] = {}
    for item in _exchange_info_symbols(exchange_info):
        symbol = item.get("symbol")
        base_asset = item.get("baseAsset")
        if not symbol or not base_asset:
            continue
        if item.get("status") != "TRADING":
            continue
        if not item.get("isSpotTradingAllowed", True):
            continue
        if item.get("quoteAsset") != "USDT":
            continue
        if base_asset in stablecoin_bases:
            continue
        symbols_by_base[base_asset] = symbol

    selected: list[str] = []
    for base in whitelist_bases:
        symbol = symbols_by_base.get(base)
        if symbol is not None:
            selected.append(symbol)
        if len(selected) >= top_n:
            break
    return selected


def select_top_usdt_symbols(
    exchange_info: dict[str, Any] | list[dict[str, Any]],
    tickers_24h: list[dict[str, Any]],
    top_n: int = 10,
    stablecoin_bases: set[str] | frozenset[str] = STABLECOIN_BASE_ASSETS,
) -> list[str]:
    symbols = {}
    for item in _exchange_info_symbols(exchange_info):
        symbol = item.get("symbol")
        if not symbol:
            continue
        if item.get("status") != "TRADING":
            continue
        if not item.get("isSpotTradingAllowed", True):
            continue
        if item.get("quoteAsset") != "USDT":
            continue
        if item.get("baseAsset") in stablecoin_bases:
            continue
        symbols[symbol] = item

    ranked: list[tuple[float, str]] = []
    for ticker in tickers_24h:
        symbol = ticker.get("symbol")
        if symbol not in symbols:
            continue
        try:
            quote_volume = float(ticker.get("quoteVolume", 0.0))
        except (TypeError, ValueError):
            quote_volume = 0.0
        ranked.append((quote_volume, symbol))

    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [symbol for _, symbol in ranked[:top_n]]


def fetch_top_usdt_symbols(
    top_n: int = 10,
    base_url: str = BINANCE_SPOT_API_BASE,
    timeout: float = 10.0,
) -> list[str]:
    exchange_info = requests.get(f"{base_url}/api/v3/exchangeInfo", timeout=timeout).json()
    return select_whitelist_usdt_symbols(exchange_info, top_n=top_n)


def compute_scan_windows(now_ts: int | None = None) -> dict[Interval, tuple[int, int]]:
    end_time = int(now_ts if now_ts is not None else datetime.now().timestamp())
    return {
        Interval.INTERVAL_1d: (end_time - 30 * 24 * 60 * 60, end_time),
        Interval.INTERVAL_1h: (end_time - 7 * 24 * 60 * 60, end_time),
    }


def extend_window_for_warmup(
    interval: Interval,
    start_time: int,
    end_time: int,
    warmup_bars: int = DEFAULT_STRATEGY_WARMUP_BARS,
) -> tuple[int, int]:
    return (start_time - get_time_duration(interval) * warmup_bars, end_time)


def _local_timezone_label() -> str:
    local_now = datetime.now().astimezone()
    tzname = local_now.tzname() or "local"
    offset = local_now.strftime("%z")
    if len(offset) == 5:
        offset = f"{offset[:3]}:{offset[3:]}"
    return f"{tzname} ({offset})"


def _naive_local_to_utc_iso(value: str) -> str:
    naive = datetime.fromisoformat(value)
    localized = naive.replace(tzinfo=LOCAL_TIMEZONE)
    return localized.astimezone(UTC).isoformat()


def _timestamp_to_local_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=LOCAL_TIMEZONE).isoformat()


def _timestamp_to_utc_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()


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


def load_window_klines(
    db_manager: DatabaseManager,
    symbol: str,
    interval: Interval,
    start_time: int,
    end_time: int,
) -> list[Kline]:
    return db_manager.kline.get_klines(SymbolInterval(normalize_symbol(symbol), interval).name(), start_time, end_time) or []


def extract_entry_signals(
    events: list[dict[str, Any]],
    symbol: str,
    interval: str,
    strategy_name: str,
    start_time: int | None = None,
    end_time: int | None = None,
) -> list[dict[str, Any]]:
    extracted = []
    for event in events:
        side = event.get("side")
        signal_type = event.get("signal_type")
        if side is None:
            if signal_type == "bottom_divergence":
                side = "LONG"
            elif signal_type == "top_divergence":
                side = "SHORT"
        if side not in ("LONG", "SHORT"):
            continue
        signal_time = event.get("signal_time")
        if not signal_time:
            continue
        signal_dt = datetime.fromisoformat(signal_time)
        signal_ts = int(signal_dt.timestamp())
        if start_time is not None and signal_ts < start_time:
            continue
        if end_time is not None and signal_ts > end_time:
            continue
        signal_bar = event.get("signal_bar", {})
        localized_signal = signal_dt.replace(tzinfo=LOCAL_TIMEZONE)
        extracted.append(
            {
                "signal_time": signal_time,
                "signal_time_local": localized_signal.isoformat(),
                "signal_time_utc": localized_signal.astimezone(UTC).isoformat(),
                "signal_timezone": _local_timezone_label(),
                "symbol": symbol,
                "interval": interval,
                "strategy": strategy_name,
                "side": side,
                "price": signal_bar.get("close"),
                "signal_type": signal_type,
                "signal_bar": signal_bar,
                "legs": event.get("legs", []),
                "conditions": event.get("conditions", {}),
                "trade_outcome": event.get("trade_outcome", {}),
            }
        )
    return extracted


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

    class SilentStrategy(strategy_cls):
        def log_info(self, msg):
            pass

        def log_debug(self, msg):
            pass

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.addstrategy(SilentStrategy)
    cerebro.adddata(BinanceData(klines))
    cerebro.broker.setcash(cash)
    cerebro.broker.setcommission(commission=commission)
    strategies = cerebro.run()
    events = getattr(strategies[0], "_signal_events", [])
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
            klines = load_window_klines(db_manager, symbol, interval, load_start_time, load_end_time)
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


def build_scan_report(
    *,
    signals: list[dict[str, Any]],
    strategy_name: str,
    top_n: int,
    selected_symbols: list[str],
    windows: dict[Interval, tuple[int, int]],
    generated_at_ts: int | None = None,
) -> dict[str, Any]:
    generated_ts = int(generated_at_ts if generated_at_ts is not None else datetime.now().timestamp())
    report_windows: dict[str, dict[str, Any]] = {}
    for interval, (start_time, end_time) in windows.items():
        report_windows[interval.value] = {
            "signal_window_start_local": _timestamp_to_local_iso(start_time),
            "signal_window_end_local": _timestamp_to_local_iso(end_time),
            "signal_window_start_utc": _timestamp_to_utc_iso(start_time),
            "signal_window_end_utc": _timestamp_to_utc_iso(end_time),
        }
    return {
        "report": {
            "strategy": strategy_name,
            "requested_top": top_n,
            "selected_symbols": selected_symbols,
            "signals_count": len(signals),
            "generated_at_local": _timestamp_to_local_iso(generated_ts),
            "generated_at_utc": _timestamp_to_utc_iso(generated_ts),
            "signal_time_basis": "Signal timestamps are interpreted in the runtime local timezone and also exported in UTC.",
            "runtime_local_timezone": _local_timezone_label(),
            "scan_windows": report_windows,
        },
        "signals": signals,
    }


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


def render_signal_table(signals: list[dict[str, Any]]) -> str:
    table = PrettyTable()
    table.field_names = ["Signal Time (Local)", "Symbol", "Interval", "Strategy", "Side", "Price"]
    for signal in signals:
        table.add_row(
            [
                signal["signal_time"],
                signal["symbol"],
                signal["interval"],
                signal["strategy"],
                signal["side"],
                signal.get("price"),
            ]
        )
    return table.get_string()


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
