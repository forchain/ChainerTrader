from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from trader.utils.task_state import TaskState, parse_task_state_type

PERSISTED_LEGACY_LIVE_EXECUTION_MODE = "persisted_legacy_live_execution_mode"
PERSISTED_LIVE_DATA_MODE = "persisted_live_data_mode"
SUPPORTED_MODE_REWRITES = {
    "small_live_auto": "auto_trade",
    "full_live_auto": "auto_trade",
}
SUPPORTED_MODES = {"auto_trade", "manual_notify"}
UNSUPPORTED_MODES = {"staged_auto_trade", "paper_auto", "manual", "notify"}


def migrate_persisted_task_config_json(config_json: str) -> str:
    payload, _ = _migrate_payload(config_json)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def sanitize_public_task_config_json(config_json: str) -> str:
    try:
        payload = json.loads(config_json or "[]")
    except (TypeError, json.JSONDecodeError):
        return config_json
    if not isinstance(payload, list):
        return config_json

    changed = False
    sanitized_payload: list[Any] = []
    for item in payload:
        if not isinstance(item, dict):
            sanitized_payload.append(item)
            continue
        sanitized_item = dict(item)
        changed |= sanitized_item.pop(PERSISTED_LEGACY_LIVE_EXECUTION_MODE, None) is not None
        changed |= sanitized_item.pop(PERSISTED_LIVE_DATA_MODE, None) is not None
        sanitized_payload.append(sanitized_item)
    if not changed:
        return config_json
    return json.dumps(sanitized_payload, ensure_ascii=False, separators=(",", ":"))


def assert_persisted_task_config_json_is_migrated(config_json: str) -> None:
    _, changed = _migrate_payload(config_json)
    if changed:
        raise ValueError(
            "persisted task config uses legacy live-mode fields; run "
            "`python scripts/migrate_persisted_live_task_configs.py` before recovery"
        )


@dataclass(slots=True)
class PersistedLiveConfigMigrationReport:
    scanned: int = 0
    updated: int = 0
    skipped: int = 0


async def migrate_persisted_live_task_configs(task_repo) -> PersistedLiveConfigMigrationReport:
    states = await task_repo.get_all_tasks()
    report = PersistedLiveConfigMigrationReport()
    updates: list[TaskState] = []

    for state in states:
        config_json = getattr(state, "config_json", None)
        if not config_json:
            report.skipped += 1
            continue
        report.scanned += 1
        try:
            payload, changed = _migrate_payload(config_json)
        except ValueError:
            if _state_name(state) == "RUNNING":
                raise
            report.skipped += 1
            continue
        if not changed:
            report.skipped += 1
            continue
        migrated_json = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        updates.append(_clone_state_with_config_json(state, migrated_json))
        report.updated += 1

    if updates:
        saved = await task_repo.add_tasks(updates)
        if saved != len(updates):
            raise RuntimeError(f"saved {saved} of {len(updates)} intended task updates")

    return report


def _state_name(state: Any) -> str:
    return str(getattr(getattr(state, "state", None), "name", getattr(state, "state", "")))


def _migrate_payload(config_json: str) -> tuple[list[Any], bool]:
    payload = json.loads(config_json)
    if not isinstance(payload, list):
        raise ValueError("persisted task config must be a JSON array")

    changed = False
    migrated_payload: list[Any] = []
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            migrated_payload.append(item)
            continue
        try:
            migrated_item = canonicalize_persisted_task_config_dict(item)
        except ValueError as exc:
            raise ValueError(f"{exc} at index {index}") from exc
        changed |= migrated_item != item
        migrated_payload.append(migrated_item)

    return migrated_payload, changed


def canonicalize_persisted_task_config_dict(item: dict[str, Any]) -> dict[str, Any]:
    migrated_item = dict(item)
    explicit_mode = "live_execution_mode" in migrated_item and migrated_item.get("live_execution_mode") not in (None, "")
    mode = _normalize_mode(migrated_item.get("live_execution_mode"))
    legacy_mode = migrated_item.get(PERSISTED_LEGACY_LIVE_EXECUTION_MODE)
    if legacy_mode is not None:
        legacy_mode = str(legacy_mode).strip().lower()
        if legacy_mode not in SUPPORTED_MODE_REWRITES:
            raise ValueError(f"unsupported persisted legacy live_execution_mode: {legacy_mode}")
    if mode in SUPPORTED_MODE_REWRITES:
        legacy_mode = mode
        mode = SUPPORTED_MODE_REWRITES[mode]
        explicit_mode = True
    if explicit_mode or legacy_mode is not None:
        migrated_item["live_execution_mode"] = mode
    else:
        migrated_item.pop("live_execution_mode", None)
    if legacy_mode is not None:
        migrated_item[PERSISTED_LEGACY_LIVE_EXECUTION_MODE] = legacy_mode
    else:
        migrated_item.pop(PERSISTED_LEGACY_LIVE_EXECUTION_MODE, None)

    live_data_mode = migrated_item.pop("live_data_mode", None)
    if live_data_mode is None:
        live_data_mode = migrated_item.pop(PERSISTED_LIVE_DATA_MODE, None)
    default_live_data_mode = "realtime" if mode == "manual_notify" else "polling"
    if live_data_mode is None:
        return migrated_item

    normalized_live_data_mode = str(live_data_mode).strip().lower()
    if normalized_live_data_mode not in {"polling", "realtime"}:
        raise ValueError(f"unsupported persisted live_data_mode: {live_data_mode}")
    if mode == "manual_notify" and normalized_live_data_mode != "realtime":
        raise ValueError("manual_notify with live_data_mode=polling cannot be migrated safely")
    if normalized_live_data_mode != default_live_data_mode:
        migrated_item[PERSISTED_LIVE_DATA_MODE] = normalized_live_data_mode
    return migrated_item


def _normalize_mode(value: Any) -> str:
    mode = str(value or "auto_trade").strip().lower()
    if mode in UNSUPPORTED_MODES:
        raise ValueError(f"unsupported persisted live_execution_mode: {mode}")
    if mode not in {*SUPPORTED_MODE_REWRITES.keys(), *SUPPORTED_MODES}:
        raise ValueError(f"unsupported persisted live_execution_mode: {mode}")
    return mode


def _clone_state_with_config_json(state: Any, config_json: str) -> TaskState:
    start_time = getattr(state, "start_time", None)
    if not isinstance(start_time, datetime):
        start_time = datetime.now()

    cloned = TaskState(
        int(getattr(state, "id")),
        getattr(state, "name", None),
        start_time,
        tret=getattr(state, "tret", None),
        commission=float(getattr(state, "commission", 0) or 0),
        strategy_start_time=int(getattr(state, "strategy_start_time", 0) or 0),
        strategy_end_time=int(getattr(state, "strategy_end_time", 0) or 0),
        initial_cash=float(getattr(state, "initial_cash", 0) or 0),
        config_json=config_json,
        user_id=getattr(state, "user_id", None),
        error_message=getattr(state, "error_message", None),
    )
    state_name = getattr(getattr(state, "state", None), "name", getattr(state, "state", None))
    cloned.state = parse_task_state_type(state_name)
    return cloned
