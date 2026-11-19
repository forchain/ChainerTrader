"""Compatibility shim: the runtime supervisor now lives in ``trader.core.task.use_cases.runtime``."""

from __future__ import annotations

from trader.common import path
from trader.core.shared.config import Config, default
from trader.core.task.use_cases.runtime import RECOVERY_TASK_CONCURRENCY, AppRuntime


class App(AppRuntime):
    def __init__(self, cfg: Config = default(), event_publisher=None, *, container=None):
        if container is None:
            from trader.main import compose_application
            from trader.task.task_config import parse_task_config

            container = compose_application(cfg, event_publisher=event_publisher, task_parser=parse_task_config)
        super().__init__(container=container)


def version():
    with open(path.GetTraderDir() + "/VERSION", "r", encoding="utf-8") as file:
        return file.read()


__all__ = ["App", "AppRuntime", "RECOVERY_TASK_CONCURRENCY", "version"]
