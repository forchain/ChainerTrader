"""File-backed task-config loading and symbol-list expansion."""

import json
import os

from trader.adapters.outbound.files.symbols_interval import SymbolsInterval
from trader.core.shared import paths as path
from trader.core.shared.config import TRADER_MIN_LIVE_TRADE_NOTIONAL
from trader.core.shared.domain import Interval, SymbolInterval, parse_datetime  # noqa: F401
from trader.core.task.config import (
    TaskConfig,
    apply_persisted_task_runtime_metadata,
    infer_strategy_requires_short,
    normalize_strategy_params,
    parse_bool,
    parse_string_list,
)
from trader.core.task.config_parsing import create_task_id, get_symbols
from trader.core.task.config_parsing import parse_task_config_payload as _core_parse_payload

__all__ = [
    "FileTaskConfigSourceLoader",
    "TaskConfig",
    "apply_persisted_task_runtime_metadata",
    "create_task_id",
    "get_symbols",
    "get_symbols_from_cfg",
    "infer_strategy_requires_short",
    "normalize_strategy_params",
    "parse_bool",
    "parse_string_list",
    "parse_task_config",
    "read_task_config_source",
]


def _global_min_live_trade_notional() -> float:
    return float(os.environ.get(TRADER_MIN_LIVE_TRADE_NOTIONAL, 11.0) or 11.0)


def parse_task_config_payload(parsed_list, last_task_id: int = 0) -> list[TaskConfig]:
    """Parse a payload with file-based symbol lists and env-derived live-trade defaults."""
    return _core_parse_payload(
        parsed_list,
        last_task_id,
        expand_symbols=lambda symbols, interval: _expand_symbols(symbols, interval),
        optimization_run_id_source=lambda: os.environ.get("TRADER_OPTIMIZATION_RUN_ID"),
        min_live_trade_notional=_global_min_live_trade_notional(),
    )


def _expand_symbols(symbols: str, interval: Interval) -> list[SymbolInterval]:
    return SymbolsInterval(symbols, interval).symbol_intervals


def _read_config_file(cfg: str) -> str | None:
    file_path = path.get_file_path(cfg)
    if os.path.isfile(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                return file.read()
        except FileNotFoundError:
            return ""
    if path.is_like_file(cfg):
        raise ValueError(f"task config file does not exist: {cfg}")
    return None


def read_task_config_source(cfg: str) -> str:
    """Return the task-config JSON text for an inline document or a file path."""
    text = _read_config_file(cfg)
    return cfg if text is None else text


# '[{"task_type": "CHECK_KLINES", "start_time": "2023-09-24 14:30:00","end_time":"0","limit":1000,"symbol":"BTC-USDT","interval":"1d",
# "csv":"ETHUSDT-1h-202301-202401.csv","strategy":"ShihunRSI2","free":100}]'
def parse_task_config(cfg: str, last_task_id: int = 0) -> list[TaskConfig]:
    text = _read_config_file(cfg)
    if text is None:
        parsed_list = json.loads(cfg)
    else:
        try:
            parsed_list = json.loads(text)
        except json.JSONDecodeError:
            return []
    return parse_task_config_payload(parsed_list, last_task_id)


def get_symbols_from_cfg(cfg):
    return get_symbols(parse_task_config(cfg))


class FileTaskConfigSourceLoader:
    """File adapter implementing :class:`trader.core.task.interfaces.TaskConfigSourceLoader`."""

    def load_configs(
        self,
        source: str,
        *,
        last_task_id: int = 0,
        min_live_trade_notional: float = 11.0,
    ) -> list[TaskConfig]:
        return parse_task_config(source, last_task_id)

    def read_source_text(self, source: str) -> str:
        return read_task_config_source(source)

    def source_exists(self, source: str) -> bool:
        try:
            json.loads(source)
            return True
        except json.JSONDecodeError:
            return os.path.isfile(path.get_file_path(source))
