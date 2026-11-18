"""Task configuration domain value and its normalization rules."""

import os
from datetime import datetime

from trader.common.config import TRADER_MIN_LIVE_TRADE_NOTIONAL
from trader.core.execution.modes import (
    normalize_live_execution_mode,
    normalize_margin_borrow_block_policy,
)
from trader.core.shared.domain import Interval, SymbolInterval
from trader.core.task.domain import TaskType
from trader.core.task.exceptions import TaskConfigError
from trader.task.persisted_live_config_migration import (
    PERSISTED_LEGACY_LIVE_EXECUTION_MODE,
)


def parse_bool(value, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    raise ValueError(f"invalid boolean value: {value}")


def parse_string_list(value) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, str):
        return [item.strip().upper() for item in value.split(",") if item.strip()]
    return [str(item).strip().upper() for item in value if str(item).strip()]


def normalize_strategy_params(params: dict) -> dict:
    normalized = dict(params)

    enter_key = "chainer_enter_need_confirm"
    exit_key = "chainer_exit_need_confirm"
    merged_key = "chainer_need_confirm"

    has_enter = enter_key in normalized
    has_exit = exit_key in normalized

    if has_enter or has_exit:
        enter_value = normalized.get(enter_key)
        exit_value = normalized.get(exit_key)
        if has_enter and has_exit and enter_value != exit_value:
            raise ValueError("chainer_enter_need_confirm and chainer_exit_need_confirm must match")
        merged_value = enter_value if has_enter else exit_value
        normalized[merged_key] = merged_value
        normalized.pop(enter_key, None)
        normalized.pop(exit_key, None)

    normalized.pop("chainer_auto_signal", None)
    normalized.pop("chainer_signal_interfaces", None)
    return normalized


def infer_strategy_requires_short(strategy_params: dict | None) -> bool:
    params = dict(strategy_params or {})
    mode = params.get("chainer_mode")
    if mode is not None:
        return str(mode).strip().upper() in {"SHORT_ONLY", "BOTH"}
    return False


def _global_min_live_trade_notional() -> float:
    return float(os.environ.get(TRADER_MIN_LIVE_TRADE_NOTIONAL, 11.0) or 11.0)


def apply_persisted_task_runtime_metadata(taskc, saved_config: dict | None) -> None:
    saved = dict(saved_config or {})
    legacy_mode = saved.get(PERSISTED_LEGACY_LIVE_EXECUTION_MODE)
    if legacy_mode:
        setattr(taskc, PERSISTED_LEGACY_LIVE_EXECUTION_MODE, str(legacy_mode).strip().lower())


class TaskConfig:
    def __init__(
        self,
        id: int,
        ttype: TaskType,
        symbol_interval=SymbolInterval("BTC-USDT", Interval("1d")),
        csv=None,
        start_time=0,
        end_time=0,
        limit=0,
        strategies: [str] = None,
        auto_download=False,
        free: float = -1,
        force_update: bool = False,
        strategy_params: dict | None = None,
        param_id: str | None = None,
        optimization_run_id: str | None = None,
        dataset_ref=None,
        live_execution_mode: str = "auto_trade",
        manual_start_position: float = 0.0,
        live_data_mode: str | None = None,
        live_trade_max_notional: float = 0.0,
        live_margin_borrow_block_policy: str = "skip_continue",
        live_margin_borrow_precheck: bool = True,
        live_margin_auto_repay_max_total: float = 100.0,
        live_margin_auto_repay_max_per_asset: float = 50.0,
        live_margin_auto_repay_min_amount: float = 0.000001,
        live_margin_auto_repay_excluded_assets: list[str] | None = None,
        user_id: int | None = None,
        run_id: str | None = None,
        fund_reservation_asset: str | None = None,
        fund_reservation_amount: float | None = None,
        fund_reservation_remaining: float | None = None,
    ):
        self.ttype = ttype
        self.csv = csv
        self.start_time = start_time
        self.end_time = end_time
        self.limit = limit
        self.strategies = strategies
        self.symbol_interval = symbol_interval
        self.auto_download = auto_download
        self.free = free
        self.force_update = force_update
        self.strategy_params = strategy_params or {}
        self.param_id = param_id
        self.optimization_run_id = optimization_run_id
        self.dataset_ref = dataset_ref
        self.live_execution_mode = normalize_live_execution_mode(live_execution_mode)
        self.manual_start_position = float(manual_start_position or 0.0)
        if live_data_mode is not None:
            raise TaskConfigError("live_data_mode is no longer supported; remove it from the task config")
        self.live_trade_max_notional = float(live_trade_max_notional or 0.0)
        self.live_margin_borrow_block_policy = normalize_margin_borrow_block_policy(live_margin_borrow_block_policy)
        self.live_margin_borrow_precheck = parse_bool(live_margin_borrow_precheck, default=True)
        self.live_margin_auto_repay_max_total = float(live_margin_auto_repay_max_total or 0.0)
        self.live_margin_auto_repay_max_per_asset = float(live_margin_auto_repay_max_per_asset or 0.0)
        self.live_margin_auto_repay_min_amount = float(live_margin_auto_repay_min_amount or 0.0)
        self.live_margin_auto_repay_excluded_assets = parse_string_list(live_margin_auto_repay_excluded_assets)
        self.user_id = int(user_id) if user_id is not None else None
        self.run_id = run_id
        self.fund_reservation_asset = str(fund_reservation_asset).upper() if fund_reservation_asset else None
        self.fund_reservation_amount = float(fund_reservation_amount) if fund_reservation_amount is not None else None
        self.fund_reservation_remaining = float(fund_reservation_remaining) if fund_reservation_remaining is not None else None
        if self.live_margin_borrow_block_policy == "repay_all" and (
            self.live_margin_auto_repay_max_total <= 0 or self.live_margin_auto_repay_max_per_asset <= 0
        ):
            raise TaskConfigError(
                "repay_all requires positive live_margin_auto_repay_max_total "
                "and live_margin_auto_repay_max_per_asset"
            )
        self.requires_short_capability = infer_strategy_requires_short(self.strategy_params)

        self.id = id

    @property
    def task_batch_id(self) -> str | None:
        # Backward compatibility for legacy code paths/tests.
        return self.run_id

    def to_dict(self):
        s_time = "not speicifed"
        if self.start_time > 0:
            s_time = f"{datetime.fromtimestamp(self.start_time)}({self.start_time})"

        e_time = "not speicifed"
        if self.end_time > 0:
            e_time = f"{datetime.fromtimestamp(self.end_time)}({self.end_time})"

        limit_str = "not speicifed"
        if self.limit > 0:
            limit_str = f"{self.limit}"

        if self.ttype == TaskType.DEBUG:
            return {
                "id": self.id,
                "type": self.ttype,
                "limit": self.limit,
                "user_id": self.user_id,
                "run_id": self.run_id,
            }
        return {
            "id": self.id,
            "type": self.ttype,
            "symbol_interval": self.symbol_interval.name(),
            "csv": self.csv,
            "start_time": f"{s_time}",
            "end_time": f"{e_time}",
            "limit": f"{limit_str}",
            "strategies": self.strategies,
            "auto_download": self.auto_download,
            "free": self.free,
            "force_update": self.force_update,
            "strategy_params": self.strategy_params,
            "param_id": self.param_id,
            "optimization_run_id": self.optimization_run_id,
            "live_execution_mode": self.live_execution_mode,
            "manual_start_position": self.manual_start_position,
            "live_trade_max_notional": self.live_trade_max_notional,
            "live_margin_borrow_block_policy": self.live_margin_borrow_block_policy,
            "live_margin_borrow_precheck": self.live_margin_borrow_precheck,
            "live_margin_auto_repay_max_total": self.live_margin_auto_repay_max_total,
            "live_margin_auto_repay_max_per_asset": self.live_margin_auto_repay_max_per_asset,
            "live_margin_auto_repay_min_amount": self.live_margin_auto_repay_min_amount,
            "live_margin_auto_repay_excluded_assets": list(self.live_margin_auto_repay_excluded_assets),
            "requires_short_capability": self.requires_short_capability,
            "user_id": self.user_id,
            "run_id": self.run_id,
            "fund_reservation_asset": self.fund_reservation_asset,
            "fund_reservation_amount": self.fund_reservation_amount,
            "fund_reservation_remaining": self.fund_reservation_remaining,
        }

    def strategy_name(self):
        if self.strategies is None:
            return None
        s = ""
        for st in self.strategies:
            if len(s) > 0:
                s += "+" + st
            else:
                s += st
        return s
