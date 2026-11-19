"""Compatibility re-exports; the migration rules live in ``trader.core.task.persisted_config_migration``."""

from __future__ import annotations

from trader.core.task.persisted_config_migration import (
    PERSISTED_LEGACY_LIVE_EXECUTION_MODE,
    PERSISTED_LIVE_DATA_MODE,
    SUPPORTED_MODE_REWRITES,
    SUPPORTED_MODES,
    UNSUPPORTED_MODES,
    PersistedLiveConfigMigrationReport,
    assert_persisted_task_config_json_is_migrated,
    canonicalize_persisted_task_config_dict,
    migrate_persisted_live_task_configs,
    migrate_persisted_task_config_json,
    sanitize_public_task_config_json,
)

__all__ = [
    "PERSISTED_LEGACY_LIVE_EXECUTION_MODE",
    "PERSISTED_LIVE_DATA_MODE",
    "SUPPORTED_MODE_REWRITES",
    "SUPPORTED_MODES",
    "UNSUPPORTED_MODES",
    "PersistedLiveConfigMigrationReport",
    "assert_persisted_task_config_json_is_migrated",
    "canonicalize_persisted_task_config_dict",
    "migrate_persisted_live_task_configs",
    "migrate_persisted_task_config_json",
    "sanitize_public_task_config_json",
]
