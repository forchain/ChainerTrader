from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from trader.adapters.outbound.binance.symbol_source import HttpCandidateSymbolSource, default_fetch_json
from trader.adapters.outbound.files.optimization_store import FileTaskConfigFileStore
from trader.core.optimization.domain import (
    ALL_HISTORY_START,
    BINANCE_EXCHANGE_INFO_URL,
    CMC_INDEXES,
    DEFAULT_RANK_FIELD,
    RELATIVE_DURATION_PATTERN,
    TASK_SYMBOL_PATTERN,
    CandidateSymbolSet,
    build_cmc_binance_universe,
    is_task_symbol_compatible,
    merge_auto_selection_config,
    normalize_exchange_symbol,
    normalize_task_symbol,
    parse_auto_selection_task,
    render_all_symbol_tasks,
    render_optimization_tasks,
    render_top_symbol_tasks,
    resolve_task_time_range,
    resolve_template_time_range,
    select_top_symbols,
)
from trader.core.optimization.domain import (
    build_binance_usdt_pairs as _build_binance_usdt_pairs,
)
from trader.core.optimization.domain import (
    build_cmc_constituents as _build_cmc_constituents,
)
from trader.core.optimization.use_cases.selection import AutoCoinSelectionUseCase

DEFAULT_CONFIG_PATH = "configs/tasks/auto_selection/cmc20_binance_usdt_mixed_auto_selection.json"
_FILE_STORE = FileTaskConfigFileStore()


def load_json(path: str | Path) -> Any:
    return _FILE_STORE.load_json(path)


def write_json(path: str | Path, payload: Any) -> None:
    _FILE_STORE.write_json(path, payload)


def load_auto_selection_task(path: str | Path) -> dict[str, Any]:
    """Load the AUTO_SELECTION task into the generator's runtime shape."""
    return parse_auto_selection_task(load_json(path))


def ensure_market_data(
    *,
    binance_path: str | Path,
    constituents_path: str | Path,
    index: str,
    refresh: bool,
    fetch_json: Callable[[str], dict[str, Any]] = default_fetch_json,
    now: datetime | None = None,
) -> None:
    """Download market snapshots only when missing, unless explicitly refreshed."""
    generated_at = now or datetime.now().astimezone()
    normalized = index.upper()
    if normalized not in CMC_INDEXES:
        raise ValueError(f"unsupported market index: {index}")
    destinations = (
        (Path(binance_path), BINANCE_EXCHANGE_INFO_URL, _build_binance_usdt_pairs),
        (
            Path(constituents_path),
            CMC_INDEXES[normalized]["api_url"],
            lambda payload, timestamp: _build_cmc_constituents(payload, timestamp, normalized),
        ),
    )
    for path, source_url, transform in destinations:
        if path.exists() and not refresh:
            continue
        write_json(path, transform(fetch_json(source_url), generated_at))


def load_universe_symbols(path: str | Path) -> list[str]:
    return CandidateSymbolSet.from_universe_payload(load_json(path)).symbols


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
    use_case = AutoCoinSelectionUseCase(
        config_store=_FILE_STORE,
        symbol_source=HttpCandidateSymbolSource(),
    )
    try:
        use_case.execute(config_path=args.config, overrides=vars(args))
    except ValueError as exc:
        if "--ranking and --top-output" in str(exc):
            raise SystemExit(str(exc)) from exc
        raise
    return 0


__all__ = [
    "ALL_HISTORY_START",
    "BINANCE_EXCHANGE_INFO_URL",
    "CMC_INDEXES",
    "DEFAULT_CONFIG_PATH",
    "DEFAULT_RANK_FIELD",
    "RELATIVE_DURATION_PATTERN",
    "TASK_SYMBOL_PATTERN",
    "_build_binance_usdt_pairs",
    "_build_cmc_constituents",
    "build_arg_parser",
    "build_cmc_binance_universe",
    "ensure_market_data",
    "is_task_symbol_compatible",
    "load_auto_selection_task",
    "load_json",
    "load_universe_symbols",
    "main",
    "merge_auto_selection_config",
    "normalize_exchange_symbol",
    "normalize_task_symbol",
    "render_all_symbol_tasks",
    "render_optimization_tasks",
    "render_top_symbol_tasks",
    "resolve_task_time_range",
    "resolve_template_time_range",
    "select_top_symbols",
    "write_json",
]

if __name__ == "__main__":
    raise SystemExit(main())
