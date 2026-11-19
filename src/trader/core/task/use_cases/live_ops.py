"""Pure task-config reuse helpers for the live monitoring API.

Extracted from the HTTP router so config-reuse/rerun planning stays free of web or
persistence concerns; the router keeps only request/response shaping.
"""

from __future__ import annotations

import json
from typing import Any

from trader.core.shared.domain import Interval

QUOTE_ASSETS = ("USDT", "USDC", "BUSD", "FDUSD", "TUSD", "USDP", "DAI", "USD1", "USDE", "USDS", "PYUSD", "BTC", "ETH")


def task_config_dict(ts) -> dict[str, Any]:
    try:
        config = json.loads(getattr(ts, "config_json", "") or "[]")
        if isinstance(config, list) and config and isinstance(config[0], dict):
            return dict(config[0])
    except Exception:
        return {}
    return {}


def task_config_value(ts, key: str) -> Any:
    try:
        config = json.loads(getattr(ts, "config_json", "") or "[]")
        if isinstance(config, list) and config and isinstance(config[0], dict):
            return config[0].get(key)
    except Exception:
        return None
    return None


def normalize_task_config_symbol(symbol: Any) -> str:
    text = str(symbol or "").strip().upper().replace("/", "-")
    if not text or "-" in text:
        return text
    for quote in QUOTE_ASSETS:
        if text.endswith(quote) and len(text) > len(quote):
            return f"{text[:-len(quote)]}-{quote}"
    return text


def task_name_symbol_interval(ts) -> tuple[str | None, str | None]:
    name = str(getattr(ts, "name", "") or "")
    parts = name.split(".")
    if len(parts) < 3 or not parts[2]:
        return None, None
    symbol_interval = parts[2]
    for interval in sorted((item.value for item in Interval), key=len, reverse=True):
        suffix = f"-{interval}"
        if symbol_interval.endswith(suffix):
            symbol = symbol_interval[: -len(suffix)]
            return normalize_task_config_symbol(symbol), interval
    return None, None


def is_parseable_task_config_symbol(symbol: Any) -> bool:
    text = str(symbol or "").strip()
    if not text or "-" not in text:
        return False
    base, quote = text.split("-", 1)
    return bool(base and quote)


def reusable_task_config_dict(ts) -> dict[str, Any]:
    cfg = task_config_dict(ts)
    name_symbol, name_interval = task_name_symbol_interval(ts)
    if "symbol" in cfg:
        cfg["symbol"] = normalize_task_config_symbol(cfg.get("symbol"))
    if not is_parseable_task_config_symbol(cfg.get("symbol")) and name_symbol:
        cfg["symbol"] = name_symbol
    if not str(cfg.get("interval") or "").strip() and name_interval:
        cfg["interval"] = name_interval
    if "symbols" in cfg:
        raw_symbols = cfg.get("symbols") or []
        if isinstance(raw_symbols, str):
            symbol_items = raw_symbols.split(",")
        else:
            symbol_items = raw_symbols
        normalized_symbols = [normalize_task_config_symbol(item) for item in symbol_items if str(item).strip()]
        if normalized_symbols and not is_parseable_task_config_symbol(cfg.get("symbol")):
            cfg["symbols"] = ",".join(normalized_symbols)
        else:
            cfg.pop("symbols", None)
    cfg.pop("run_id", None)
    cfg.pop("task_batch_id", None)
    cfg.pop("id", None)
    return cfg


def rerun_config_json(config_json: str) -> str:
    parsed = json.loads(config_json)
    if not isinstance(parsed, list):
        return config_json
    sanitized = []
    for item in parsed:
        if not isinstance(item, dict):
            sanitized.append(item)
            continue
        cfg = dict(item)
        cfg.pop("run_id", None)
        cfg.pop("task_batch_id", None)
        cfg.pop("id", None)
        sanitized.append(cfg)
    return json.dumps(sanitized, ensure_ascii=False)


def run_id_from_state(ts) -> str | None:
    raw = task_config_value(ts, "run_id")
    if raw in (None, ""):
        raw = task_config_value(ts, "task_batch_id")
    text = str(raw or "").strip()
    return text or None
