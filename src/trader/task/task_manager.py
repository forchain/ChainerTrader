"""Compatibility shim: ``TaskManager`` now lives in ``trader.core.task.use_cases.task_manager``."""

from trader.core.task.use_cases.task_manager import TaskManager

__all__ = ["TaskManager"]
