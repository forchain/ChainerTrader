from __future__ import annotations

import argparse
import calendar
import copy
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import requests

DEFAULT_RANK_FIELD = "avg_total_return_pct"
TASK_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]+-USDT$")
RELATIVE_DURATION_PATTERN = re.compile(
    r"^(?P<amount>\d+)(?P<unit>h|d|w|m|y)$",
    re.IGNORECASE,
)
DEFAULT_CONFIG_PATH = "configs/tasks/auto_selection/cmc20_binance_usdt_mixed_auto_selection.json"
BINANCE_EXCHANGE_INFO_URL = "https://data-api.binance.vision/api/v3/exchangeInfo"
ALL_HISTORY_START = "2000-01-01 00:00:00"
CMC_INDEXES = {
    "CMC20": {
        "api_url": "https://pro-api.coinmarketcap.com/public-api/v3/index/cmc20-latest",
        "source_url": "https://coinmarketcap.com/charts/cmc20/",
    },
    "CMC100": {
        "api_url": "https://pro-api.coinmarketcap.com/public-api/v3/index/cmc100-latest",
        "source_url": "https://coinmarketcap.com/charts/cmc100/",
    },
}


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def merge_auto_selection_config(config: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """Apply explicitly supplied CLI values over the tool configuration."""
    merged = copy.deepcopy(config)
    merged.update({key: value for key, value in overrides.items() if value is not None})
    return merged


def load_auto_selection_task(path: str | Path) -> dict[str, Any]:
    """Load the AUTO_SELECTION task into the generator's runtime shape."""
    task = load_json(path)
    if task.get("task_type") != "AUTO_SELECTION":
        raise ValueError("auto-selection config must use task_type AUTO_SELECTION")

    market_data = task["market_data"]
    optimization = task["optimization"]
    selection = task["selection"]
    index = str(market_data["index"]).upper()
    if index not in CMC_INDEXES:
        raise ValueError(f"unsupported market index: {index}")
    return {
        "index": index,
        "binance_pairs": market_data["binance_pairs"],
        "constituents": market_data["constituents"],
        "refresh_market_data": market_data.get("refresh_market_data", False),
        "universe": task["universe"],
        "template": {"task": task["task_template"]},
        "output": optimization["output"],
        "optimization_run_id": optimization.get("run_id"),
        "profiles": optimization["profiles"],
        "top_output": selection["live_output"],
        "top": selection.get("top", 10),
        "rank_field": selection.get("rank_field", DEFAULT_RANK_FIELD),
        "min_return_pct": selection.get("min_return_pct", 0),
    }


def _fetch_json(url: str) -> dict[str, Any]:
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object from {url}")
    return payload


def _build_binance_usdt_pairs(payload: dict[str, Any], generated_at: datetime) -> dict[str, Any]:
    pairs = []
    for item in payload.get("symbols", []):
        if (
            item.get("quoteAsset") != "USDT"
            or item.get("status") != "TRADING"
            or not item.get("isSpotTradingAllowed", True)
        ):
            continue
        pairs.append(
            {
                "symbol": item["symbol"],
                "base_asset": item["baseAsset"],
                "quote_asset": item["quoteAsset"],
                "status": item["status"],
                "spot_trading_allowed": bool(item.get("isSpotTradingAllowed", True)),
                "margin_trading_allowed": bool(item.get("isMarginTradingAllowed", False)),
                "task_symbol_compatible": is_task_symbol_compatible(f"{item['baseAsset']}-{item['quoteAsset']}"),
            }
        )
    pairs.sort(key=lambda item: item["symbol"])
    return {
        "schema_version": 1,
        "generated_at": generated_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source_url": BINANCE_EXCHANGE_INFO_URL,
        "quote_asset": "USDT",
        "status": "TRADING",
        "filters": {"spot_trading_allowed": True},
        "count": len(pairs),
        "task_compatible_count": sum(1 for item in pairs if item["task_symbol_compatible"]),
        "pairs": pairs,
    }


def _find_cmc_index(payload: dict[str, Any], index: str) -> dict[str, Any]:
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise ValueError(f"{index} response does not contain an index object")
    if isinstance(data.get("constituents"), list):
        return data
    for value in data.values():
        if isinstance(value, dict) and isinstance(value.get("constituents"), list):
            return value
    raise ValueError(f"{index} response does not contain constituents")


def _build_cmc_constituents(payload: dict[str, Any], generated_at: datetime, index: str) -> dict[str, Any]:
    index_payload = _find_cmc_index(payload, index)
    constituents = []
    for item in index_payload["constituents"]:
        symbol = item.get("symbol")
        if not symbol:
            continue
        constituents.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "symbol": str(symbol).upper(),
                "url": item.get("url"),
                "weight": item.get("weight", item.get("weight_percentage")),
            }
        )
    return {
        "schema_version": 1,
        "market_index": index,
        "generated_at": generated_at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source_url": CMC_INDEXES[index]["source_url"],
        "source_api_url": CMC_INDEXES[index]["api_url"],
        "last_update": index_payload.get("last_update"),
        "next_update": index_payload.get("next_update"),
        "value": index_payload.get("value"),
        "value_24h_percentage_change": index_payload.get("value_24h_percentage_change"),
        "count": len(constituents),
        "constituents": constituents,
    }


def ensure_market_data(
    *,
    binance_path: str | Path,
    constituents_path: str | Path,
    index: str,
    refresh: bool,
    fetch_json: Callable[[str], dict[str, Any]] = _fetch_json,
    now: datetime | None = None,
) -> None:
    """Download market snapshots only when missing, unless explicitly refreshed."""
    generated_at = now or datetime.now().astimezone()
    index = index.upper()
    if index not in CMC_INDEXES:
        raise ValueError(f"unsupported market index: {index}")
    destinations = (
        (Path(binance_path), BINANCE_EXCHANGE_INFO_URL, _build_binance_usdt_pairs),
        (
            Path(constituents_path),
            CMC_INDEXES[index]["api_url"],
            lambda payload, timestamp: _build_cmc_constituents(payload, timestamp, index),
        ),
    )
    for path, source_url, transform in destinations:
        if path.exists() and not refresh:
            continue
        write_json(path, transform(fetch_json(source_url), generated_at))


def _parse_datetime(value: str, field: str = "end_time") -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"invalid {field}: {value}") from error


def _shift_months(value: datetime, months: int) -> datetime:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _parse_relative_duration(value: str) -> tuple[int, str] | None:
    match = RELATIVE_DURATION_PATTERN.fullmatch(value.strip())
    if not match:
        return None
    return int(match.group("amount")), match.group("unit").lower()


def _offset_time(value: datetime, amount: int, unit: str) -> datetime:
    if unit == "y":
        return _shift_months(value, amount * 12)
    if unit == "m":
        return _shift_months(value, amount)
    if unit == "w":
        return value + timedelta(weeks=amount)
    if unit == "d":
        return value + timedelta(days=amount)
    return value + timedelta(hours=amount)


def resolve_task_time_range(
    task: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Resolve relative start and end times backward from now."""
    resolved = copy.deepcopy(task)
    end_value = resolved.get("end_time")
    current_time = (now or datetime.now().astimezone()).replace(tzinfo=None)
    end_duration = _parse_relative_duration(str(end_value)) if isinstance(end_value, str) else None
    if end_duration:
        end_time = _offset_time(current_time, -end_duration[0], end_duration[1])
    elif end_value:
        end_time = _parse_datetime(str(end_value))
    else:
        end_time = current_time

    start_value = resolved.get("start_time")
    if isinstance(start_value, str):
        start_duration = _parse_relative_duration(start_value)
        if start_duration:
            start_time = _offset_time(current_time, -start_duration[0], start_duration[1])
            resolved["start_time"] = start_time.strftime("%Y-%m-%d %H:%M:%S")
        else:
            _parse_datetime(start_value, "start_time")
    resolved["end_time"] = end_time.strftime("%Y-%m-%d %H:%M:%S")
    return resolved


def resolve_template_time_range(
    template: dict[str, Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    resolved = copy.deepcopy(template)
    resolved["task"] = resolve_task_time_range(resolved["task"], now=now)
    return resolved


def normalize_task_symbol(value: str) -> str:
    text = str(value).strip().upper()
    if not text:
        raise ValueError("symbol cannot be empty")
    if "-" in text:
        base, quote = text.split("-", 1)
        return f"{base}-{quote}"
    if text.endswith("USDT"):
        return f"{text[:-4]}-USDT"
    raise ValueError(f"cannot normalize symbol: {value}")


def normalize_exchange_symbol(value: str) -> str:
    return normalize_task_symbol(value).replace("-", "")


def is_task_symbol_compatible(value: str) -> bool:
    return bool(TASK_SYMBOL_PATTERN.fullmatch(normalize_task_symbol(value)))


def load_universe_symbols(path: str | Path) -> list[str]:
    payload = load_json(path)
    pairs = payload.get("pairs", [])
    if pairs:
        return [
            symbol
            for symbol in (normalize_task_symbol(item.get("symbol") or item.get("exchange_symbol")) for item in pairs)
            if is_task_symbol_compatible(symbol)
        ]
    symbols = payload.get("symbols", "")
    if isinstance(symbols, str):
        normalized = [normalize_task_symbol(item) for item in symbols.split(",") if item.strip()]
    else:
        normalized = [normalize_task_symbol(item) for item in symbols]
    return [symbol for symbol in normalized if is_task_symbol_compatible(symbol)]


def build_cmc_binance_universe(
    cmc: dict,
    binance: dict,
    *,
    index: str,
    constituents_path: str,
) -> dict:
    binance_by_base = {
        item["base_asset"]: item
        for item in binance.get("pairs", [])
        if item.get("quote_asset") == "USDT" and item.get("status") == "TRADING"
    }
    pairs = []
    for coin in cmc.get("constituents", []):
        listing = binance_by_base.get(coin.get("symbol"))
        if not listing:
            continue
        pairs.append(
            {
                "symbol": f"{listing['base_asset']}-{listing['quote_asset']}",
                "exchange_symbol": listing["symbol"],
                "base_asset": listing["base_asset"],
                "quote_asset": listing["quote_asset"],
                "cmc_id": coin.get("id"),
                "cmc_name": coin.get("name"),
                "cmc_weight": coin.get("weight"),
                "margin_trading_allowed": bool(listing.get("margin_trading_allowed")),
                "task_symbol_compatible": is_task_symbol_compatible(f"{listing['base_asset']}-{listing['quote_asset']}"),
            }
        )

    return {
        "schema_version": 1,
        "market_index": index,
        "source_files": [
            constituents_path,
            "data/market_universes/binance_usdt_pairs.json",
        ],
        "quote_asset": "USDT",
        "count": len(pairs),
        "task_compatible_count": sum(1 for item in pairs if item["task_symbol_compatible"]),
        "symbols": ",".join(item["symbol"] for item in pairs if item["task_symbol_compatible"]),
        "pairs": pairs,
    }


def render_all_symbol_tasks(template: dict, symbols: list[str]) -> list[dict]:
    task = copy.deepcopy(template["task"])
    # Selection is always evaluated via backtests, even if final output is a live task.
    task["task_type"] = "BACK_TRADER"
    task["symbols"] = ",".join(symbols)
    return [task]


def render_optimization_tasks(
    template: dict,
    symbols: list[str],
    profiles: dict[str, str],
    *,
    now: datetime | None = None,
) -> list[dict]:
    """Render one all-symbol backtest task for each configured interval profile."""
    tasks = []
    for interval, duration in profiles.items():
        task = copy.deepcopy(template["task"])
        task["task_type"] = "BACK_TRADER"
        task["symbols"] = ",".join(symbols)
        task["interval"] = interval
        if duration == "*":
            task["start_time"] = ALL_HISTORY_START
            task["end_time"] = (now or datetime.now().astimezone()).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
        else:
            task.update(resolve_task_time_range({"start_time": duration}, now=now))
        tasks.append(task)
    return tasks


def _ranking_items(payload: Any) -> list[dict]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        if isinstance(payload.get("items"), list):
            return payload["items"]
        if isinstance(payload.get("rankings"), dict):
            for key in ("by_total_return", "by_excess_return", "by_score"):
                if isinstance(payload["rankings"].get(key), list):
                    return payload["rankings"][key]
    raise ValueError("ranking file must be a ranking list or an object with items/rankings")


def select_top_symbols(
    ranking_payload: Any,
    top: int = 10,
    rank_field: str = DEFAULT_RANK_FIELD,
    min_return_pct: float = float("-inf"),
) -> list[dict]:
    best_by_candidate: dict[tuple[str, str], dict] = {}
    for item in _ranking_items(ranking_payload):
        symbol = normalize_task_symbol(item.get("symbol"))
        interval = str(item.get("interval") or "")
        candidate_key = (symbol, interval)
        current = best_by_candidate.get(candidate_key)
        if current is None or _rank_value(item, rank_field) > _rank_value(current, rank_field):
            best_by_candidate[candidate_key] = item

    ranked = sorted(
        (
            item
            for item in best_by_candidate.values()
            if _rank_value(item, "avg_total_return_pct") > float(min_return_pct)
        ),
        key=lambda item: (
            _rank_value(item, rank_field),
            _rank_value(item, "score"),
            _rank_value(item, "avg_excess_return_pct"),
        ),
        reverse=True,
    )
    return ranked[:top]


def _rank_value(item: dict, field: str) -> float:
    value = item.get(field)
    if value is None:
        summary = item.get("summary") or {}
        value = summary.get(field)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("-inf")


def render_top_symbol_tasks(
    template: dict,
    ranking_payload: Any,
    top: int = 10,
    rank_field: str = DEFAULT_RANK_FIELD,
    min_return_pct: float = float("-inf"),
) -> list[dict]:
    task_template = template["task"]
    tasks = []
    for rank, item in enumerate(
        select_top_symbols(ranking_payload, top=top, rank_field=rank_field, min_return_pct=min_return_pct), start=1
    ):
        task = copy.deepcopy(task_template)
        task.pop("symbols", None)
        task.pop("param_grid", None)
        task.pop("param_combinations", None)
        task.pop("start_time", None)
        task.pop("end_time", None)
        task["symbol"] = normalize_task_symbol(item["symbol"])
        task["interval"] = item.get("interval") or task.get("interval")
        task["strategy_params"] = copy.deepcopy(item.get("params") or task.get("strategy_params") or {})
        task["selection_rank"] = rank
        task["selection_metric"] = rank_field
        task["selection_metric_value"] = _rank_value(item, rank_field)
        if item.get("param_id"):
            task["selection_param_id"] = item["param_id"]
        tasks.append(task)
    return tasks


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate auto coin-selection task configs.")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Tool configuration JSON file.")
    parser.add_argument("--binance-pairs", help="Cached Binance USDT-pairs JSON file.")
    parser.add_argument("--constituents", help="Cached CMC index constituents JSON file.")
    parser.add_argument("--cmc100-constituents", dest="constituents", help=argparse.SUPPRESS)
    parser.add_argument("--universe", help="Universe JSON file used to render the all-symbol task config.")
    parser.add_argument("--ranking", help="Optimization ranking JSON used to render the top task config.")
    parser.add_argument("--top", type=int, help="Number of unique symbols to keep from the ranking.")
    parser.add_argument("--rank-field", help="Ranking metric field.")
    parser.add_argument(
        "--refresh-market-data",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Refresh Binance and CMC100 snapshots even when cached files already exist.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = merge_auto_selection_config(load_auto_selection_task(args.config), vars(args))
    ensure_market_data(
        binance_path=config["binance_pairs"],
        constituents_path=config["constituents"],
        index=config["index"],
        refresh=bool(config.get("refresh_market_data", False)),
    )
    universe = build_cmc_binance_universe(
        load_json(config["constituents"]),
        load_json(config["binance_pairs"]),
        index=config["index"],
        constituents_path=config["constituents"],
    )
    write_json(config["universe"], universe)
    template = config["template"]

    if config.get("output"):
        all_tasks = render_optimization_tasks(template, load_universe_symbols(config["universe"]), config["profiles"])
        if config.get("optimization_run_id"):
            for task in all_tasks:
                task["optimization_run_id"] = config["optimization_run_id"]
        write_json(config["output"], all_tasks)

    if config.get("ranking"):
        if not config.get("top_output"):
            raise SystemExit("--ranking and --top-output must be provided together")
        write_json(
            config["top_output"],
            render_top_symbol_tasks(
                template,
                load_json(config["ranking"]),
                top=int(config.get("top", 10)),
                rank_field=config.get("rank_field", DEFAULT_RANK_FIELD),
                min_return_pct=float(config.get("min_return_pct", 0)),
            ),
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
