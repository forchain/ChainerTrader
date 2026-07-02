from __future__ import annotations

from trader.task.persisted_live_config_migration import (
    PERSISTED_LEGACY_LIVE_EXECUTION_MODE,
    PERSISTED_LIVE_DATA_MODE,
    sanitize_public_task_config_json,
)


def public_task_state_dict(ts) -> dict:
    item = ts.to_dict()
    config_json = item.get("config_json")
    if config_json:
        item["config_json"] = sanitize_public_task_config_json(config_json)
    return item


def strip_recovery_only_task_config_fields(cfg: dict) -> dict:
    sanitized = dict(cfg)
    sanitized.pop(PERSISTED_LEGACY_LIVE_EXECUTION_MODE, None)
    sanitized.pop(PERSISTED_LIVE_DATA_MODE, None)
    return sanitized
