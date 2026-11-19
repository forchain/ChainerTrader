"""Parse task-config payloads into :class:`TaskConfig` values.

The parser is pure: file loading, environment lookups, and symbol-list file
expansion are supplied by the caller.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from trader.core.execution.modes import normalize_live_execution_mode, normalize_margin_borrow_block_policy
from trader.core.optimization.domain import (
    expand_parameter_space,
    has_parameter_search,
    make_optimization_run_id,
    make_param_id,
)
from trader.core.shared.domain import Interval, SymbolInterval, resolve_time_range
from trader.core.task.config import TaskConfig, normalize_strategy_params, parse_bool, parse_string_list
from trader.core.task.domain import TaskType, parse_task_type

SymbolExpander = Callable[[str, Interval], Sequence[SymbolInterval]]
OptimizationRunIdSource = Callable[[], str | None]


def create_task_id(last_task_id: int) -> int:
    current_timestamp = datetime.now().timestamp()
    task_id = int(current_timestamp * 1000)
    while True:
        if task_id > last_task_id:
            return task_id
        task_id += 1


def default_expand_symbols(symbols: str, interval: Interval) -> list[SymbolInterval]:
    """Split a comma-separated symbol list; file-based lists are a caller concern."""
    expanded: list[SymbolInterval] = []
    for raw in str(symbols or "").split(","):
        text = raw.strip()
        if not text:
            continue
        symbol_interval = SymbolInterval(text, interval)
        if not symbol_interval.is_empty():
            expanded.append(symbol_interval)
    return expanded


def parse_task_config_payload(
    parsed_list: Any,
    last_task_id: int = 0,
    *,
    expand_symbols: SymbolExpander = default_expand_symbols,
    optimization_run_id_source: OptimizationRunIdSource | None = None,
    min_live_trade_notional: float = 11.0,
) -> list[TaskConfig]:
    ret = []
    optimization_run_id = None
    run_id = None

    def next_task_id() -> int:
        nonlocal last_task_id, run_id
        task_id = create_task_id(last_task_id)
        if run_id is None:
            run_id = f"run-{task_id}"
        last_task_id = task_id
        return task_id

    for tcd in parsed_list:
        if "live_data_mode" in tcd:
            raise ValueError("live_data_mode is no longer supported; remove it from the task config")
        if tcd.get("run_id"):
            run_id = tcd["run_id"]
        task_type = parse_task_type(tcd["task_type"])

        limit = 0
        if "limit" in tcd:
            limit = tcd["limit"]

        if task_type == TaskType.DEBUG:
            task_id = next_task_id()
            tc = TaskConfig(task_id, task_type, None, user_id=tcd.get("user_id"), run_id=run_id)
            tc.limit = limit
            ret.append(tc)
            continue

        interval = Interval(tcd["interval"])
        if "symbols" in tcd:
            sis = expand_symbols(tcd["symbols"], interval)
        else:
            si = SymbolInterval(tcd["symbol"], interval)
            sis = [] if si.is_empty() else [si]
        if len(sis) <= 0:
            continue

        start_time, end_time = resolve_time_range(tcd.get("start_time"), tcd.get("end_time"))

        free = -1
        if "free" in tcd:
            free = float(tcd["free"])

        live_execution_mode = normalize_live_execution_mode(tcd.get("live_execution_mode", "auto_trade"))
        manual_start_position = float(tcd.get("manual_start_position", 0.0) or 0.0)
        configured_notional = "live_trade_max_notional" in tcd and tcd.get("live_trade_max_notional") not in (None, "")
        if configured_notional:
            live_trade_max_notional = float(tcd.get("live_trade_max_notional", 0.0) or 0.0)
            if live_trade_max_notional < min_live_trade_notional:
                raise ValueError(
                    f"live_trade_max_notional({live_trade_max_notional}) is below global minimum "
                    f"TRADER_MIN_LIVE_TRADE_NOTIONAL({min_live_trade_notional})"
                )
        else:
            live_trade_max_notional = 0.0
        live_margin_borrow_block_policy = normalize_margin_borrow_block_policy(tcd.get("live_margin_borrow_block_policy", "skip_continue"))
        live_margin_borrow_precheck = parse_bool(tcd.get("live_margin_borrow_precheck", True), default=True)
        live_margin_auto_repay_max_total = float(tcd.get("live_margin_auto_repay_max_total", 100.0) or 0.0)
        live_margin_auto_repay_max_per_asset = float(tcd.get("live_margin_auto_repay_max_per_asset", 50.0) or 0.0)
        live_margin_auto_repay_min_amount = float(tcd.get("live_margin_auto_repay_min_amount", 0.000001) or 0.0)
        live_margin_auto_repay_excluded_assets = parse_string_list(tcd.get("live_margin_auto_repay_excluded_assets"))
        user_id = tcd.get("user_id")
        fund_reservation_asset = tcd.get("fund_reservation_asset")
        fund_reservation_amount = tcd.get("fund_reservation_amount")
        fund_reservation_remaining = tcd.get("fund_reservation_remaining")

        csv = None
        if "csv" in tcd:
            csv = tcd["csv"]
        strategies = []
        strategies_bunch = []
        if "strategy" in tcd:
            strategy = tcd["strategy"]
            strategies.append(strategy)
        elif "strategies" in tcd:
            strategies_list = tcd["strategies"].split(",")
            for st in strategies_list:
                strategy = st
                strategies.append(strategy)
        elif "strategies_bunch" in tcd:
            strategies_list = tcd["strategies_bunch"].split(",")
            for st in strategies_list:
                strategy = st
                strategies_bunch.append(strategy)

        auto_download = False
        if "auto_download" in tcd:
            auto_download = tcd["auto_download"]

        force_update = False
        if "force_update" in tcd:
            force_update = tcd["force_update"]

        parameter_search_enabled = has_parameter_search(tcd)
        if parameter_search_enabled:
            strategy_count = len(strategies) + len(strategies_bunch)
            if strategy_count != 1:
                raise ValueError("parameter search requires a single strategy entry")
            if optimization_run_id is None:
                optimization_run_id = (
                    tcd.get("optimization_run_id")
                    or (optimization_run_id_source() if optimization_run_id_source is not None else None)
                    or make_optimization_run_id()
                )
            auto_download = tcd.get("auto_download", True)
            parameter_sets = expand_parameter_space(tcd)
        else:
            parameter_sets = [dict(tcd.get("strategy_params", {}) or {})]

        for si in sis:
            if (
                task_type == TaskType.IMPORT_CSV
                or task_type == TaskType.CHECK_KLINES
                or task_type == TaskType.CHECK_KLINES_NUM
                or task_type == TaskType.UPDATE_KLINES
            ):
                tc = TaskConfig(
                    next_task_id(),
                    task_type,
                    si,
                    csv,
                    start_time,
                    end_time,
                    limit,
                    None,
                    auto_download,
                    free,
                    force_update,
                    strategy_params={},
                    live_execution_mode=live_execution_mode,
                    manual_start_position=manual_start_position,
                    live_trade_max_notional=live_trade_max_notional,
                    live_margin_borrow_block_policy=live_margin_borrow_block_policy,
                    live_margin_borrow_precheck=live_margin_borrow_precheck,
                    live_margin_auto_repay_max_total=live_margin_auto_repay_max_total,
                    live_margin_auto_repay_max_per_asset=live_margin_auto_repay_max_per_asset,
                    live_margin_auto_repay_min_amount=live_margin_auto_repay_min_amount,
                    live_margin_auto_repay_excluded_assets=live_margin_auto_repay_excluded_assets,
                    user_id=user_id,
                    run_id=run_id,
                    fund_reservation_asset=fund_reservation_asset,
                    fund_reservation_amount=fund_reservation_amount,
                    fund_reservation_remaining=fund_reservation_remaining,
                )
                ret.append(tc)
            else:
                for strategy in strategies:
                    for strategy_params in parameter_sets:
                        normalized_params = normalize_strategy_params(strategy_params)
                        tc = TaskConfig(
                            next_task_id(),
                            task_type,
                            si,
                            csv,
                            start_time,
                            end_time,
                            limit,
                            [strategy],
                            auto_download,
                            free,
                            force_update,
                            strategy_params=normalized_params,
                            param_id=make_param_id(normalized_params) if parameter_search_enabled else tcd.get("param_id"),
                            optimization_run_id=optimization_run_id if parameter_search_enabled else tcd.get("optimization_run_id"),
                            live_execution_mode=live_execution_mode,
                            manual_start_position=manual_start_position,
                            live_trade_max_notional=live_trade_max_notional,
                            live_margin_borrow_block_policy=live_margin_borrow_block_policy,
                            live_margin_borrow_precheck=live_margin_borrow_precheck,
                            live_margin_auto_repay_max_total=live_margin_auto_repay_max_total,
                            live_margin_auto_repay_max_per_asset=live_margin_auto_repay_max_per_asset,
                            live_margin_auto_repay_min_amount=live_margin_auto_repay_min_amount,
                            live_margin_auto_repay_excluded_assets=live_margin_auto_repay_excluded_assets,
                            user_id=user_id,
                            run_id=run_id,
                            fund_reservation_asset=fund_reservation_asset,
                            fund_reservation_amount=fund_reservation_amount,
                            fund_reservation_remaining=fund_reservation_remaining,
                        )
                        ret.append(tc)

                if len(strategies_bunch) > 0:
                    tc = TaskConfig(
                        next_task_id(),
                        task_type,
                        si,
                        csv,
                        start_time,
                        end_time,
                        limit,
                        strategies_bunch,
                        auto_download,
                        free,
                        force_update,
                        strategy_params={},
                        param_id=tcd.get("param_id"),
                        optimization_run_id=tcd.get("optimization_run_id"),
                        live_execution_mode=live_execution_mode,
                        manual_start_position=manual_start_position,
                        live_trade_max_notional=live_trade_max_notional,
                        live_margin_borrow_block_policy=live_margin_borrow_block_policy,
                        live_margin_borrow_precheck=live_margin_borrow_precheck,
                        live_margin_auto_repay_max_total=live_margin_auto_repay_max_total,
                        live_margin_auto_repay_max_per_asset=live_margin_auto_repay_max_per_asset,
                        live_margin_auto_repay_min_amount=live_margin_auto_repay_min_amount,
                        live_margin_auto_repay_excluded_assets=live_margin_auto_repay_excluded_assets,
                        user_id=user_id,
                        run_id=run_id,
                        fund_reservation_asset=fund_reservation_asset,
                        fund_reservation_amount=fund_reservation_amount,
                        fund_reservation_remaining=fund_reservation_remaining,
                    )
                    ret.append(tc)

    return ret


def parse_task_config_json(raw: str, last_task_id: int = 0, **kwargs: Any) -> list[TaskConfig]:
    """Parse an inline JSON task-config document."""
    return parse_task_config_payload(json.loads(raw), last_task_id, **kwargs)
