from __future__ import annotations

from trader.core.task.config_codec import TaskConfigCodec
from trader.core.task.persisted_config_migration import PERSISTED_LEGACY_LIVE_EXECUTION_MODE, PERSISTED_LIVE_DATA_MODE


def public_task_state_dict(ts) -> dict:
    return TaskConfigCodec.to_public_view(ts, include_display_fields=False)


def strip_recovery_only_task_config_fields(cfg: dict) -> dict:
    sanitized = dict(cfg)
    sanitized.pop(PERSISTED_LEGACY_LIVE_EXECUTION_MODE, None)
    sanitized.pop(PERSISTED_LIVE_DATA_MODE, None)
    return sanitized
