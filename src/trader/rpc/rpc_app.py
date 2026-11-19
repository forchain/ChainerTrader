"""Compatibility shim: the API server lifecycle now lives in ``trader.adapters.inbound.http.lifecycle``."""

from __future__ import annotations

from trader.adapters.inbound.http.lifecycle import ApiServerLifecycle
from trader.core.shared.config import Config


class RpcApp(ApiServerLifecycle):
    def __init__(self, cfg: Config, *, container=None):
        if container is None:
            from trader.main import compose_application
            from trader.task.task_config import parse_task_config

            container = compose_application(cfg, task_parser=parse_task_config)
        super().__init__(container=container)


__all__ = ["RpcApp"]
