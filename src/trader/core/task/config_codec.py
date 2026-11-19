"""Single in-process codec for task configuration snapshots and task state round-trips."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from trader.core.task.config import TaskConfig, apply_persisted_task_runtime_metadata
from trader.core.task.config_parsing import parse_task_config_payload
from trader.core.task.domain import TaskState
from trader.core.task.persisted_config_migration import (
    assert_persisted_task_config_json_is_migrated,
    canonicalize_persisted_task_config_dict,
    sanitize_public_task_config_json,
)


def _task_config_symbol(symbol_interval) -> str:
    symbol = getattr(symbol_interval, "sy", None)
    base = getattr(symbol, "base", "")
    quote = getattr(symbol, "quote", "")
    if base and quote:
        return f"{base}-{quote}"
    return symbol_interval.symbol()


class TaskConfigCodec:
    """Canonical task configuration/state seam.

    All task snapshot serialization, persisted-state recovery, and public views
    cross this interface so no caller needs throwaway task objects or raw JSON
    patching.
    """

    @staticmethod
    def from_input(raw: str, last_task_id: int = 0, *, min_live_trade_notional: float = 11.0) -> list[TaskConfig]:
        """Parse an inline JSON task-config document into 任务 configurations."""
        return parse_task_config_payload(json.loads(raw), last_task_id, min_live_trade_notional=min_live_trade_notional)

    @staticmethod
    def from_persisted_state(state: TaskState) -> TaskConfig | None:
        """Rebuild the single 任务 that a persisted 任务 state describes.

        Preserves the persisted ``task_id``/``user_id``/``run_id`` and applies
        legacy live-mode runtime metadata instead of minting new identifiers.
        """
        config_json = str(getattr(state, "config_json", "") or "").strip()
        task_id = int(getattr(state, "id", 0) or 0)
        if not config_json:
            raise RuntimeError(f"persisted running task({task_id}) is missing config_json")

        try:
            payload = json.loads(config_json)
        except (TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"persisted running task({task_id}) recovery failed: {exc}") from exc
        if not isinstance(payload, list):
            raise RuntimeError(f"persisted running task({task_id}) recovery failed: persisted task config must be a JSON array")

        saved_config = payload[0] if payload and isinstance(payload[0], dict) else {}
        task_kind = "live task" if str(saved_config.get("task_type") or "").strip().upper() == "TRADER" else "running task"
        try:
            assert_persisted_task_config_json_is_migrated(config_json)
            taskcs = parse_task_config_payload(payload, last_task_id=task_id)
        except Exception as exc:
            raise RuntimeError(f"persisted {task_kind}({task_id}) recovery failed: {exc}") from exc
        if not taskcs:
            raise RuntimeError(f"persisted {task_kind}({task_id}) recovery failed: no recoverable task config")

        state_user_id = getattr(state, "user_id", None)
        taskc = taskcs[0]
        taskc.id = task_id
        if state_user_id is not None:
            taskc.user_id = state_user_id
        # Restore the persisted run_id verbatim; parse mints one when absent, but recovery must not.
        taskc.run_id = saved_config.get("run_id")
        apply_persisted_task_runtime_metadata(taskc, saved_config)
        return taskc

    @classmethod
    def to_task_state(
        cls,
        cfg: TaskConfig,
        *,
        name: str | None = None,
        start_time: datetime | None = None,
        commission: float = 0,
        initial_cash: float | None = None,
    ) -> TaskState:
        """Serialize a 任务 config into its lossless persisted state snapshot."""
        cash = initial_cash
        if cash is None:
            cash = float(cfg.free) if cfg.free >= 0 else 0.0
        return TaskState(
            cfg.id,
            name or cls.state_name(cfg),
            start_time or datetime.now(),
            None,
            commission,
            strategy_start_time=cfg.start_time,
            strategy_end_time=cfg.end_time,
            initial_cash=cash,
            config_json=cls.to_config_json(cfg),
            user_id=getattr(cfg, "user_id", None),
        )

    @staticmethod
    def to_config_json(cfg: TaskConfig) -> str:
        """Serialize a 任务 config to the canonical persisted JSON schema."""
        config_dict: dict[str, Any] = {"task_type": cfg.ttype.name}
        if cfg.symbol_interval:
            config_dict["symbol"] = _task_config_symbol(cfg.symbol_interval)
            config_dict["interval"] = cfg.symbol_interval.interval.value

        if cfg.csv:
            config_dict["csv"] = cfg.csv
        if cfg.start_time > 0:
            config_dict["start_time"] = datetime.fromtimestamp(cfg.start_time).strftime("%Y-%m-%d %H:%M:%S")
        if cfg.end_time > 0:
            config_dict["end_time"] = datetime.fromtimestamp(cfg.end_time).strftime("%Y-%m-%d %H:%M:%S")

        if cfg.strategies:
            if len(cfg.strategies) == 1:
                config_dict["strategy"] = cfg.strategies[0]
            else:
                config_dict["strategies"] = ",".join(cfg.strategies)

        if cfg.auto_download:
            config_dict["auto_download"] = True
        if cfg.free >= 0:
            config_dict["free"] = cfg.free
        if cfg.limit > 0:
            config_dict["limit"] = cfg.limit
        if getattr(cfg, "force_update", False):
            config_dict["force_update"] = True
        if getattr(cfg, "param_id", None):
            config_dict["param_id"] = cfg.param_id
        if getattr(cfg, "optimization_run_id", None):
            config_dict["optimization_run_id"] = cfg.optimization_run_id
        if getattr(cfg, "live_execution_mode", "auto_trade") != "auto_trade":
            config_dict["live_execution_mode"] = cfg.live_execution_mode
        if getattr(cfg, "manual_start_position", 0.0):
            config_dict["manual_start_position"] = cfg.manual_start_position
        if getattr(cfg, "live_trade_max_notional", 0.0):
            config_dict["live_trade_max_notional"] = cfg.live_trade_max_notional
        if getattr(cfg, "live_margin_borrow_block_policy", "skip_continue") != "skip_continue":
            config_dict["live_margin_borrow_block_policy"] = cfg.live_margin_borrow_block_policy
        if getattr(cfg, "live_margin_borrow_precheck", True) is not True:
            config_dict["live_margin_borrow_precheck"] = cfg.live_margin_borrow_precheck
        if getattr(cfg, "live_margin_auto_repay_max_total", 100.0) != 100.0:
            config_dict["live_margin_auto_repay_max_total"] = cfg.live_margin_auto_repay_max_total
        if getattr(cfg, "live_margin_auto_repay_max_per_asset", 50.0) != 50.0:
            config_dict["live_margin_auto_repay_max_per_asset"] = cfg.live_margin_auto_repay_max_per_asset
        if getattr(cfg, "live_margin_auto_repay_min_amount", 0.000001) != 0.000001:
            config_dict["live_margin_auto_repay_min_amount"] = cfg.live_margin_auto_repay_min_amount
        if getattr(cfg, "live_margin_auto_repay_excluded_assets", None):
            config_dict["live_margin_auto_repay_excluded_assets"] = list(cfg.live_margin_auto_repay_excluded_assets)
        if getattr(cfg, "strategy_params", None):
            config_dict["strategy_params"] = cfg.strategy_params
        if getattr(cfg, "requires_short_capability", False):
            config_dict["requires_short_capability"] = True
        if getattr(cfg, "user_id", None) is not None:
            config_dict["user_id"] = cfg.user_id
        if getattr(cfg, "run_id", None):
            config_dict["run_id"] = cfg.run_id
        if getattr(cfg, "fund_reservation_asset", None):
            config_dict["fund_reservation_asset"] = cfg.fund_reservation_asset
        if getattr(cfg, "fund_reservation_amount", None) is not None:
            config_dict["fund_reservation_amount"] = cfg.fund_reservation_amount
        if getattr(cfg, "fund_reservation_remaining", None) is not None:
            config_dict["fund_reservation_remaining"] = cfg.fund_reservation_remaining

        config_dict = canonicalize_persisted_task_config_dict(config_dict)
        return json.dumps([config_dict], indent=2, ensure_ascii=False)

    @staticmethod
    def to_public_view(state: TaskState, *, include_display_fields: bool = True) -> dict[str, Any]:
        """Return the public 任务 state view with secrets stripped and display fields derived."""
        item = state.to_dict()
        payload: Any = []
        if item.get("config_json"):
            item["config_json"] = sanitize_public_task_config_json(item["config_json"])
            try:
                payload = json.loads(item["config_json"] or "[]")
            except (TypeError, json.JSONDecodeError):
                payload = []
        if not include_display_fields:
            return item
        cfg = payload[0] if isinstance(payload, list) and payload and isinstance(payload[0], dict) else {}
        item["run_id"] = str(cfg.get("run_id") or "").strip() or str(cfg.get("task_batch_id") or "").strip() or None
        item["symbol"] = str(cfg.get("symbol") or "").strip()
        item["interval"] = str(cfg.get("interval") or "").strip()
        item["strategy"] = str(cfg.get("strategy") or cfg.get("strategies") or "").strip()
        return item

    @staticmethod
    def state_name(cfg: TaskConfig) -> str:
        symbol_interval = getattr(cfg, "symbol_interval", None)
        symbol_name = symbol_interval.name() if symbol_interval is not None else ""
        return f"{cfg.id}.{cfg.ttype.name}.{symbol_name}"
