"""Startup mode split and running-task recovery use cases (ADR-0002)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any, Callable

from trader.core.shared.domain import Interval, SymbolInterval, resolve_time_range
from trader.core.task.config import TaskConfig, apply_persisted_task_runtime_metadata
from trader.core.task.domain import parse_task_type
from trader.core.task.interfaces import TaskRepository


def _default_parse_persisted_config(config_json: str) -> list[TaskConfig]:
    payload = json.loads(config_json or "[]")
    if not isinstance(payload, list):
        raise ValueError("persisted task config_json must be a JSON array")
    parsed: list[TaskConfig] = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            continue
        ttype = parse_task_type(item["task_type"])
        symbol_interval = None
        if "symbol" in item and "interval" in item:
            symbol_interval = SymbolInterval(item["symbol"], Interval(item["interval"]))
        start_time, end_time = resolve_time_range(item.get("start_time"), item.get("end_time"))
        strategies_raw = item.get("strategies") or item.get("strategy")
        if isinstance(strategies_raw, str):
            strategies = [s.strip() for s in strategies_raw.split(",") if s.strip()]
        elif isinstance(strategies_raw, list):
            strategies = [str(s).strip() for s in strategies_raw if str(s).strip()]
        else:
            strategies = []
        cfg = TaskConfig(
            id=int(item.get("task_id") or index),
            ttype=ttype,
            symbol_interval=symbol_interval,
            csv=item.get("csv"),
            start_time=start_time,
            end_time=end_time,
            limit=int(item.get("limit", 0) or 0),
            strategies=strategies,
            auto_download=bool(item.get("auto_download", False)),
            free=float(item.get("free", -1)),
            strategy_params=item.get("strategy_params"),
            live_execution_mode=item.get("live_execution_mode", "auto_trade"),
            manual_start_position=float(item.get("manual_start_position", 0.0) or 0.0),
            live_trade_max_notional=float(item.get("live_trade_max_notional", 0.0) or 0.0),
            user_id=item.get("user_id"),
            run_id=item.get("run_id"),
        )
        parsed.append(cfg)
    return parsed


def _first_config_dict(config_json: str) -> dict[str, Any]:
    try:
        payload = json.loads(config_json or "[]")
    except (TypeError, json.JSONDecodeError):
        return {}
    if isinstance(payload, list) and payload and isinstance(payload[0], dict):
        return payload[0]
    return {}


@dataclass(frozen=True)
class StartupExecutionPlan:
    startup_tasks: list[TaskConfig] = field(default_factory=list)
    recover_tasks: list[TaskConfig] = field(default_factory=list)


class PlanStartupTasks:
    """Apply ADR-0002 mode split: API mode recovers only persisted RUNNING tasks; console runs startup once."""

    def __init__(
        self,
        task_repository: TaskRepository | None,
        *,
        config_parser: Callable[[str], list[TaskConfig]] | None = None,
        migration_validator: Callable[[str], None] | None = None,
        log: Any = None,
    ):
        self.task_repository = task_repository
        self.config_parser = config_parser or _default_parse_persisted_config
        self.migration_validator = migration_validator
        self.log = log

    async def load_running_task_configs(self) -> list[TaskConfig]:
        if self.task_repository is None or not hasattr(self.task_repository, "get_all_tasks"):
            return []

        states = await self.task_repository.get_all_tasks()
        taskcs: list[TaskConfig] = []
        recovery_errors: list[RuntimeError] = []

        for state in states:
            if getattr(getattr(state, "state", None), "name", None) != "RUNNING":
                continue
            saved_config = {}
            try:
                config_json = getattr(state, "config_json", None)
                if not config_json:
                    raise RuntimeError(f"persisted running task({getattr(state, 'id', 'unknown')}) is missing config_json")
                saved_config = _first_config_dict(config_json)
                if self.migration_validator is not None:
                    self.migration_validator(config_json)
                recovered = self.config_parser(config_json)
            except Exception as exc:
                is_live = str(saved_config.get("task_type") or "").strip().upper() == "TRADER"
                task_kind = "live task" if is_live else "running task"
                message = (
                    str(exc)
                    if str(exc).startswith("persisted running task(")
                    else f"persisted {task_kind}({getattr(state, 'id', 'unknown')}) recovery failed: {exc}"
                )
                recovery_errors.append(RuntimeError(message))
                if self.log is not None and hasattr(self.log, "error"):
                    self.log.error(message)
                continue

            for taskc in recovered:
                taskc.id = int(getattr(state, "id", taskc.id) or taskc.id)
                if getattr(state, "user_id", None) is not None:
                    taskc.user_id = state.user_id
                if saved_config.get("run_id"):
                    taskc.run_id = saved_config["run_id"]
                apply_persisted_task_runtime_metadata(taskc, saved_config)
            taskcs.extend(recovered)

        if taskcs and self.log is not None and hasattr(self.log, "info"):
            self.log.info(f"Recovered {len(taskcs)} running task config(s) from persisted state")
        elif recovery_errors:
            raise recovery_errors[0]
        return taskcs

    async def execute(self, *, is_server: bool, startup_tasks: list[TaskConfig] | None = None) -> StartupExecutionPlan:
        configured = list(startup_tasks or [])
        if not is_server:
            return StartupExecutionPlan(startup_tasks=configured, recover_tasks=[])
        recover_tasks = await self.load_running_task_configs()
        return StartupExecutionPlan(startup_tasks=[], recover_tasks=recover_tasks)


class RecoverRunningTasks:
    """Recover persisted RUNNING tasks concurrently without canceling live exchange orders."""

    def __init__(self, *, max_concurrency: int = 10):
        self.max_concurrency = max(1, int(max_concurrency))

    async def execute(self, taskcs: list[TaskConfig], recover_fn: Callable[[TaskConfig], Any]) -> None:
        if not taskcs:
            return
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _recover(taskc: TaskConfig):
            async with semaphore:
                await recover_fn(taskc)

        await asyncio.gather(*[asyncio.create_task(_recover(taskc)) for taskc in taskcs])
