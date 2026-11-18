from __future__ import annotations

from trader.task.persisted_live_config_migration import (
    PERSISTED_LEGACY_LIVE_EXECUTION_MODE,
    PERSISTED_LIVE_DATA_MODE,
)
from trader.task.task_config_codec import TaskConfigCodec


def public_task_state_dict(ts) -> dict:
    return TaskConfigCodec.to_public_view(ts, include_display_fields=False)


def strip_recovery_only_task_config_fields(cfg: dict) -> dict:
    sanitized = dict(cfg)
    sanitized.pop(PERSISTED_LEGACY_LIVE_EXECUTION_MODE, None)
    sanitized.pop(PERSISTED_LIVE_DATA_MODE, None)
    return sanitized
