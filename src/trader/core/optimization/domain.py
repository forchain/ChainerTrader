from __future__ import annotations

import calendar
import copy
import hashlib
import itertools
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo
from statistics import mean, median
from typing import Any

from trader.core.optimization.audit import (
    build_behavior_clusters,
    build_local_best,
    build_parameter_coverage_audit,
    build_shortlist,
    build_trade_fingerprints,
)
from trader.core.optimization.exceptions import OptimizationConfigError, RankingError
from trader.core.optimization.workbench import build_workbench_payload
from trader.core.shared.domain import Interval, get_time_duration

DEFAULT_RANK_FIELD = "avg_total_return_pct"
TASK_SYMBOL_PATTERN = re.compile(r"^[A-Z0-9]+-USDT$")
RELATIVE_DURATION_PATTERN = re.compile(r"^(?P<amount>\d+)(?P<unit>h|d|w|m|y)$", re.IGNORECASE)
ALL_HISTORY_START = "2000-01-01 00:00:00"
BINANCE_EXCHANGE_INFO_URL = "https://data-api.binance.vision/api/v3/exchangeInfo"
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

REPORT_VERSION = "2.0"
SCORE_VERSION = "score_v2_active_drawdown"
TERMINAL_STAGES = {"finished", "aborted"}

DEFAULT_SIGNAL_WHITELIST = (
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
LOCAL_TIMEZONE: tzinfo = datetime.now().astimezone().tzinfo or UTC


def normalize_task_symbol(value: str) -> str:
    text = str(value).strip().upper()
    if not text:
        raise OptimizationConfigError("symbol cannot be empty")
    if "-" in text:
        base, quote = text.split("-", 1)
        return f"{base}-{quote}"
    if text.endswith("USDT"):
        return f"{text[:-4]}-USDT"
    raise OptimizationConfigError(f"cannot normalize symbol: {value}")


def normalize_exchange_symbol(value: str) -> str:
    return normalize_task_symbol(value).replace("-", "")


def is_task_symbol_compatible(value: str) -> bool:
    return bool(TASK_SYMBOL_PATTERN.fullmatch(normalize_task_symbol(value)))


def normalize_scanner_symbol(symbol: str) -> str:
    if "-" in symbol:
        return symbol
    if symbol.endswith("USDT") and len(symbol) > len("USDT"):
        return f"{symbol[:-4]}-USDT"
    return symbol


def has_parameter_search(task_definition: dict) -> bool:
    return bool(task_definition.get("param_grid") or task_definition.get("param_combinations"))


def expand_parameter_space(task_definition: dict) -> list[dict]:
    combinations = task_definition.get("param_combinations")
    if combinations is not None:
        expanded_combinations = []
        for item in combinations:
            keys = list(item.keys())
            values = [value if isinstance(value, list) else [value] for value in item.values()]
            for combo in itertools.product(*values):
                expanded_combinations.append(dict(zip(keys, combo)))
        return expanded_combinations

    grid = task_definition.get("param_grid")
    if not grid:
        return [{}]

    keys = list(grid.keys())
    values = [grid[key] for key in keys]
    expanded: list[dict] = []
    for combo in itertools.product(*values):
        params: dict = {}
        for key, value in zip(keys, combo):
            if isinstance(value, dict):
                overlap = params.keys() & value.keys()
                if overlap:
                    raise OptimizationConfigError(
                        f"param_grid fragment for '{key}' overlaps existing keys: {sorted(overlap)}"
                    )
                params.update(value)
            else:
                params[key] = value
        expanded.append(params)
    return expanded


def make_param_id(params: dict) -> str:
    payload = json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def make_optimization_run_id() -> str:
    return datetime.now(UTC).replace(tzinfo=None).strftime("%Y%m%dT%H%M%S%fZ")


@dataclass(frozen=True)
class CandidateSymbolSet:
    """候选币种集合 (Candidate Symbol Set)."""

    symbols: list[str]
    market_index: str = "CUSTOM"
    pairs: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_universe_payload(cls, payload: dict[str, Any]) -> CandidateSymbolSet:
        pairs = list(payload.get("pairs", []) or [])
        if pairs:
            symbols = [
                symbol
                for symbol in (
                    normalize_task_symbol(item.get("symbol") or item.get("exchange_symbol"))
                    for item in pairs
                )
                if is_task_symbol_compatible(symbol)
            ]
        else:
            raw_symbols = payload.get("symbols", "")
            if isinstance(raw_symbols, str):
                normalized = [normalize_task_symbol(item) for item in raw_symbols.split(",") if item.strip()]
            else:
                normalized = [normalize_task_symbol(item) for item in raw_symbols]
            symbols = [symbol for symbol in normalized if is_task_symbol_compatible(symbol)]
        return cls(
            symbols=symbols,
            market_index=str(payload.get("market_index") or "CUSTOM"),
            pairs=pairs,
            metadata={k: v for k, v in payload.items() if k not in {"pairs", "symbols"}},
        )

    def comma_separated(self) -> str:
        return ",".join(self.symbols)


@dataclass(frozen=True)
class TaskTemplate:
    """任务模板 (Task Template) used to render backtest optimization or selection configs."""

    task: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {"task": copy.deepcopy(self.task)}

    def has_parameter_search(self) -> bool:
        return has_parameter_search(self.task)

    def expand_parameter_space(self) -> list[dict]:
        return expand_parameter_space(self.task)

    def render_all_symbol_tasks(self, candidate_set: CandidateSymbolSet | list[str]) -> list[dict[str, Any]]:
        symbols = candidate_set.symbols if isinstance(candidate_set, CandidateSymbolSet) else list(candidate_set)
        return render_all_symbol_tasks(self.as_dict(), symbols)

    def render_optimization_tasks(
        self,
        candidate_set: CandidateSymbolSet | list[str],
        profiles: dict[str, str],
        *,
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        symbols = candidate_set.symbols if isinstance(candidate_set, CandidateSymbolSet) else list(candidate_set)
        return render_optimization_tasks(self.as_dict(), symbols, profiles, now=now)


@dataclass(frozen=True)
class SelectionResultTaskConfig:
    """选币结果任务配置 (Selection Result Task Config)."""

    task: dict[str, Any]
    symbol: str
    interval: str | None
    rank: int
    rank_field: str
    metric_value: float
    param_id: str | None = None

    @classmethod
    def from_ranking_item(
        cls,
        template: TaskTemplate | dict[str, Any],
        item: dict[str, Any],
        *,
        rank: int,
        rank_field: str = DEFAULT_RANK_FIELD,
    ) -> SelectionResultTaskConfig:
        raw_template = template.task if isinstance(template, TaskTemplate) else template["task"]
        task = copy.deepcopy(raw_template)
        task.pop("symbols", None)
        task.pop("param_grid", None)
        task.pop("param_combinations", None)
        task.pop("start_time", None)
        task.pop("end_time", None)
        symbol = normalize_task_symbol(item["symbol"])
        interval = item.get("interval") or task.get("interval")
        metric_value = _rank_value(item, rank_field)
        param_id = item.get("param_id")

        task["symbol"] = symbol
        task["interval"] = interval
        task["strategy_params"] = copy.deepcopy(item.get("params") or task.get("strategy_params") or {})
        task["selection_rank"] = rank
        task["selection_metric"] = rank_field
        task["selection_metric_value"] = metric_value
        if param_id:
            task["selection_param_id"] = param_id
        return cls(
            task=task,
            symbol=symbol,
            interval=interval,
            rank=rank,
            rank_field=rank_field,
            metric_value=metric_value,
            param_id=param_id,
        )

    def to_task_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.task)


def build_binance_usdt_pairs(
    payload: dict[str, Any],
    generated_at: datetime,
    *,
    source_url: str = BINANCE_EXCHANGE_INFO_URL,
) -> dict[str, Any]:
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
        "source_url": source_url,
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
        raise OptimizationConfigError(f"{index} response does not contain an index object")
    if isinstance(data.get("constituents"), list):
        return data
    for value in data.values():
        if isinstance(value, dict) and isinstance(value.get("constituents"), list):
            return value
    raise OptimizationConfigError(f"{index} response does not contain constituents")


def build_cmc_constituents(payload: dict[str, Any], generated_at: datetime, index: str) -> dict[str, Any]:
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


def _parse_datetime(value: str, field_name: str = "end_time") -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as error:
        raise OptimizationConfigError(f"invalid {field_name}: {value}") from error


def shift_months(value: datetime, months: int) -> datetime:
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
        return shift_months(value, amount * 12)
    if unit == "m":
        return shift_months(value, amount)
    if unit == "w":
        return value + timedelta(weeks=amount)
    if unit == "d":
        return value + timedelta(days=amount)
    return value + timedelta(hours=amount)


def resolve_task_time_range(task: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
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


def resolve_template_time_range(template: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    resolved = copy.deepcopy(template)
    resolved["task"] = resolve_task_time_range(resolved["task"], now=now)
    return resolved


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
    raise RankingError("ranking file must be a ranking list or an object with items/rankings")


def _rank_value(item: dict, field_name: str) -> float:
    value = item.get(field_name)
    if value is None:
        summary = item.get("summary") or {}
        value = summary.get(field_name)
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("-inf")


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


def render_top_symbol_tasks(
    template: dict,
    ranking_payload: Any,
    top: int = 10,
    rank_field: str = DEFAULT_RANK_FIELD,
    min_return_pct: float = float("-inf"),
) -> list[dict]:
    return [
        SelectionResultTaskConfig.from_ranking_item(
            template,
            item,
            rank=rank,
            rank_field=rank_field,
        ).to_task_dict()
        for rank, item in enumerate(
            select_top_symbols(ranking_payload, top=top, rank_field=rank_field, min_return_pct=min_return_pct),
            start=1,
        )
    ]


def parse_auto_selection_task(task: dict[str, Any]) -> dict[str, Any]:
    if task.get("task_type") != "AUTO_SELECTION":
        raise OptimizationConfigError("auto-selection config must use task_type AUTO_SELECTION")

    market_data = task["market_data"]
    optimization = task["optimization"]
    selection = task["selection"]
    index = str(market_data["index"]).upper()
    if index not in CMC_INDEXES:
        raise OptimizationConfigError(f"unsupported market index: {index}")
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


def merge_auto_selection_config(config: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(config)
    merged.update({key: value for key, value in overrides.items() if value is not None})
    return merged


def normalize_report_params(params: dict) -> dict:
    normalized = dict(params or {})
    enter_key = "chainer_enter_need_confirm"
    exit_key = "chainer_exit_need_confirm"
    merged_key = "chainer_need_confirm"

    if enter_key in normalized or exit_key in normalized:
        enter_value = normalized.get(enter_key)
        exit_value = normalized.get(exit_key)
        if enter_value == exit_value:
            normalized[merged_key] = enter_value
            normalized.pop(enter_key, None)
            normalized.pop(exit_key, None)

    normalized.pop("chainer_auto_signal", None)
    normalized.pop("chainer_signal_interfaces", None)
    return normalized


def display_param_name(name: str) -> str:
    if name.startswith("chainer_"):
        return name.removeprefix("chainer_")
    return name


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _score_item(item: dict) -> float:
    excess_component = _clamp(item["avg_excess_return_pct"] / 20.0, -1.0, 1.0) * 35.0
    beat_component = item["beat_hold_ratio"] * 25.0
    sharpe_component = _clamp((item["avg_sharpe"] or 0.0) / 2.0, 0.0, 1.0) * 10.0
    profit_component = _clamp(((item["avg_profit_factor"] or 0.0) - 1.0) / 1.5, 0.0, 1.0) * 10.0
    drawdown_penalty = _clamp(item["avg_max_dd_pct"] / 40.0, 0.0, 1.0) * 20.0
    no_trade_penalty = item["no_trade_ratio"] * 30.0
    return round(50.0 + excess_component + beat_component + sharpe_component + profit_component - drawdown_penalty - no_trade_penalty, 4)


def classify_failure_counts(failures: list[dict]) -> dict:
    skipped_reasons = {
        "coverage_incomplete",
        "dataset_failed",
        "dataset_timeout",
        "db_unavailable",
        "download_budget_exceeded",
        "download_failed",
        "no_data",
    }
    counts = {
        "failed_samples": 0,
        "timed_out_samples": 0,
        "skipped_samples": 0,
        "aborted": False,
    }
    for failure in failures:
        reason = failure.get("reason")
        if reason == "run_aborted":
            counts["aborted"] = True
        elif reason == "sample_timeout":
            counts["timed_out_samples"] += 1
        elif reason in skipped_reasons:
            counts["skipped_samples"] += 1
        else:
            counts["failed_samples"] += 1
    return counts


def build_optimization_artifacts(optimization_run_id: str, sample_reports: list[dict], failures: list[dict]) -> dict:
    grouped: dict[tuple[str, str, str, str], list[dict]] = {}
    for sample in sample_reports:
        sample["params"] = normalize_report_params(sample.get("params", {}))
        key = (
            sample.get("strategy", "unknown"),
            sample.get("symbol", "unknown"),
            sample.get("interval", "unknown"),
            sample.get("param_id", "unknown"),
        )
        grouped.setdefault(key, []).append(sample)

    aggregate_items = []
    for (_, symbol, interval, param_id), items in grouped.items():
        first = items[0]
        total_returns = [item["summary"]["total_return_pct"] for item in items]
        hold_returns = [item["summary"]["hold_return_pct"] for item in items]
        excess_returns = [total - hold for total, hold in zip(total_returns, hold_returns)]
        sharpe_values = [item["summary"].get("sharpe") for item in items if item["summary"].get("sharpe") is not None]
        profit_factors = [item["summary"].get("profit_factor") for item in items if item["summary"].get("profit_factor") is not None]
        full_max_dd_values = [item["summary"].get("max_dd_pct", 0.0) for item in items]
        active_max_dd_values = [
            item["summary"].get("active_max_dd_pct", item["summary"].get("max_dd_pct", 0.0))
            for item in items
        ]
        total_trades = sum(item["summary"].get("total_trades", 0) for item in items)
        no_trade_samples = sum(1 for item in items if item["summary"].get("total_trades", 0) == 0)
        samples = len(items)
        beat_hold_ratio = round(sum(1 for value in excess_returns if value > 0) / samples, 4)
        no_trade_ratio = round(no_trade_samples / samples, 4)

        aggregate_items.append(
            {
                "strategy": first["strategy"],
                "symbol": symbol,
                "interval": interval,
                "param_id": param_id,
                "params": first["params"],
                "sample_details": [
                    {
                        "dataset_ref": item.get("dataset_ref"),
                        "report_path": item.get("report_path"),
                        "summary": item.get("summary", {}),
                        "trades": item.get("trades", []),
                        "open_trades": item.get("open_trades", []),
                        "signals": item.get("signals", []),
                    }
                    for item in items
                ],
                "samples": samples,
                "total_trades": total_trades,
                "no_trade_samples": no_trade_samples,
                "no_trade_ratio": no_trade_ratio,
                "avg_total_return_pct": round(sum(total_returns) / samples, 4),
                "avg_hold_return_pct": round(sum(hold_returns) / samples, 4),
                "avg_excess_return_pct": round(sum(excess_returns) / samples, 4),
                "median_excess_return_pct": round(median(excess_returns), 4),
                "beat_hold_ratio": beat_hold_ratio,
                "avg_sharpe": round(sum(sharpe_values) / len(sharpe_values), 4) if sharpe_values else None,
                "avg_profit_factor": round(sum(profit_factors) / len(profit_factors), 4) if profit_factors else None,
                "avg_max_dd_pct": round(sum(active_max_dd_values) / samples, 4),
                "avg_active_max_dd_pct": round(sum(active_max_dd_values) / samples, 4),
                "avg_full_max_dd_pct": round(sum(full_max_dd_values) / samples, 4),
            }
        )

    for item in aggregate_items:
        item["score_version"] = SCORE_VERSION
        item["score"] = _score_item(item)

    by_score = sorted(aggregate_items, key=lambda item: (item["score"], item["avg_excess_return_pct"]), reverse=True)
    by_excess_return = sorted(aggregate_items, key=lambda item: (item["avg_excess_return_pct"], item["beat_hold_ratio"]), reverse=True)
    datasets = sorted({sample["dataset_ref"] for sample in sample_reports if sample.get("dataset_ref")})
    failure_counts = classify_failure_counts(failures)
    fingerprints = build_trade_fingerprints(aggregate_items)
    audit = build_parameter_coverage_audit(optimization_run_id, aggregate_items, fingerprints)
    clusters = build_behavior_clusters(aggregate_items, fingerprints, audit)
    local_best = build_local_best(aggregate_items, audit, clusters)
    shortlist = build_shortlist(local_best, audit, clusters)
    workbench = build_workbench_payload(
        optimization_run_id,
        {
            "optimization_run_id": optimization_run_id,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "completed_samples": len(sample_reports),
            "failed_samples": failure_counts["failed_samples"],
            "timed_out_samples": failure_counts["timed_out_samples"],
            "skipped_samples": failure_counts["skipped_samples"],
        },
        by_score,
        audit,
        clusters,
        local_best,
        shortlist,
    )

    return {
        "manifest": {
            "optimization_run_id": optimization_run_id,
            "report_version": REPORT_VERSION,
            "score_version": SCORE_VERSION,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "completed_samples": len(sample_reports),
            "failed_samples": failure_counts["failed_samples"],
            "timed_out_samples": failure_counts["timed_out_samples"],
            "skipped_samples": failure_counts["skipped_samples"],
            "failure_records": len(failures),
            "aborted": failure_counts["aborted"],
            "datasets": datasets,
            "run_reports": [sample.get("report_path") for sample in sample_reports if sample.get("report_path")],
        },
        "aggregate": {
            "optimization_run_id": optimization_run_id,
            "report_version": REPORT_VERSION,
            "score_version": SCORE_VERSION,
            "items": aggregate_items,
        },
        "rankings": {
            "by_score": by_score,
            "by_excess_return": by_excess_return,
        },
        "fingerprints": fingerprints,
        "audit": audit,
        "clusters": clusters,
        "local_best": local_best,
        "shortlist": shortlist,
        "workbench": workbench,
        "failures": failures,
    }


def evaluate_abort_reason(
    status: dict[str, Any],
    *,
    max_failure_rate: float = 0.9,
    min_completed_samples: int = 50,
    no_progress_timeout_seconds: float = 180.0,
    min_runnable_ratio: float = 0.1,
    parallelism_collapse_ratio: float = 0.25,
    worker_cpu_efficiency_threshold: float = 0.1,
) -> str | None:
    completed = int(status.get("samples_completed") if status.get("samples_completed") is not None else status.get("completed_samples") or 0)
    succeeded = int(status.get("samples_succeeded") if status.get("samples_succeeded") is not None else status.get("succeeded_samples") or 0)
    failed = int(status.get("samples_failed") if status.get("samples_failed") is not None else status.get("failed_samples") or 0) + int(
        status.get("samples_timed_out") if status.get("samples_timed_out") is not None else status.get("timed_out_samples") or 0
    )
    executed = succeeded + failed if (succeeded + failed) > 0 else completed
    failure_rate = failed / executed if executed else 0.0
    total = int(status.get("samples_total") or 0)
    runnable = int(status.get("samples_runnable") or 0)
    time_since_progress = float(status.get("time_since_last_progress_seconds") or 0)
    parallelism_ratio = float(status.get("parallelism_ratio") or 0.0)
    worker_cpu_efficiency = float(status.get("worker_cpu_efficiency") or 0.0)

    if completed >= min_completed_samples and failure_rate > max_failure_rate:
        return "high_failure_rate" if status.get("samples_completed") is not None else "failure_rate_exceeded"

    if (
        runnable > completed
        and time_since_progress > no_progress_timeout_seconds
        and parallelism_ratio < parallelism_collapse_ratio
        and worker_cpu_efficiency < worker_cpu_efficiency_threshold
    ):
        return "parallelism_collapse"

    if runnable > completed and time_since_progress > no_progress_timeout_seconds:
        return "no_progress"

    if total > 0 and runnable / total < min_runnable_ratio:
        return "insufficient_runnable_samples"

    return None


@dataclass(frozen=True)
class MonthWindow:
    month: str
    selection_start: str
    selection_end: str
    hold_start: str
    hold_end: str


@dataclass
class SymbolRunResult:
    symbol: str
    ok: bool
    selection_return_pct: float | None = None
    hold_return_pct: float | None = None
    error: str | None = None
    report_path: str | None = None
    param_id: str | None = None
    params: dict[str, Any] = field(default_factory=dict)


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def monthly_windows(year: int) -> list[MonthWindow]:
    windows: list[MonthWindow] = []
    for month in range(1, 13):
        hold_start_dt = datetime(year, month, 1, 0, 0, 0)
        next_month_start = shift_months(hold_start_dt, 1)
        hold_end_dt = next_month_start
        selection_start_dt = shift_months(hold_start_dt, -12)
        selection_end_dt = hold_start_dt
        windows.append(
            MonthWindow(
                month=f"{year}-{month:02d}",
                selection_start=_fmt_dt(selection_start_dt),
                selection_end=_fmt_dt(selection_end_dt),
                hold_start=_fmt_dt(hold_start_dt),
                hold_end=_fmt_dt(hold_end_dt),
            )
        )
    return windows


def build_selection_payload(run_results: list[SymbolRunResult]) -> list[dict[str, Any]]:
    payload = []
    for result in run_results:
        if not result.ok or result.selection_return_pct is None:
            continue
        payload.append(
            {
                "symbol": result.symbol,
                "interval": "1h",
                "avg_total_return_pct": result.selection_return_pct,
                "score": result.selection_return_pct,
                "avg_excess_return_pct": result.selection_return_pct,
                "param_id": result.param_id,
                "params": result.params,
            }
        )
    return payload


def summary_return_pct(run_results: list[SymbolRunResult]) -> float | None:
    values = [item.hold_return_pct for item in run_results if item.ok and item.hold_return_pct is not None]
    if not values:
        return None
    return float(mean(values))


def compounded_return_pct(monthly_returns: list[float]) -> float:
    equity = 1.0
    for pct in monthly_returns:
        equity *= 1.0 + pct / 100.0
    return round((equity - 1.0) * 100.0, 4)


def _exchange_info_symbols(exchange_info: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(exchange_info, dict):
        return list(exchange_info.get("symbols", []))
    return list(exchange_info)


def select_whitelist_usdt_symbols(
    exchange_info: dict[str, Any] | list[dict[str, Any]],
    whitelist_bases: tuple[str, ...] | list[str] = DEFAULT_SIGNAL_WHITELIST,
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


def local_timezone_label() -> str:
    local_now = datetime.now().astimezone()
    tzname = local_now.tzname() or "local"
    offset = local_now.strftime("%z")
    if len(offset) == 5:
        offset = f"{offset[:3]}:{offset[3:]}"
    return f"{tzname} ({offset})"


def timestamp_to_local_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=LOCAL_TIMEZONE).isoformat()


def timestamp_to_utc_iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=UTC).isoformat()


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
                "signal_timezone": local_timezone_label(),
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
            "signal_window_start_local": timestamp_to_local_iso(start_time),
            "signal_window_end_local": timestamp_to_local_iso(end_time),
            "signal_window_start_utc": timestamp_to_utc_iso(start_time),
            "signal_window_end_utc": timestamp_to_utc_iso(end_time),
        }
    return {
        "report": {
            "strategy": strategy_name,
            "requested_top": top_n,
            "selected_symbols": selected_symbols,
            "signals_count": len(signals),
            "generated_at_local": timestamp_to_local_iso(generated_ts),
            "generated_at_utc": timestamp_to_utc_iso(generated_ts),
            "signal_time_basis": "Signal timestamps are interpreted in the runtime local timezone and also exported in UTC.",
            "runtime_local_timezone": local_timezone_label(),
            "scan_windows": report_windows,
        },
        "signals": signals,
    }
