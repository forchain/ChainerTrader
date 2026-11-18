"""Task domain: task types, lifecycle states, aggregate snapshots, and result ranking rules."""

from __future__ import annotations

import json
import math
from datetime import datetime
from enum import Enum
from typing import Any

from trader.strategy.trader_result import TraderResult, parse_trader_result


class TaskType(Enum):
    TRADER = 0
    BACK_TRADER = 1
    UPDATE_KLINES = 2
    CHECK_KLINES = 3
    IMPORT_CSV = 4
    CHECK_KLINES_NUM = 5
    DEBUG = 6


def parse_task_type(name):
    if name == TaskType.TRADER.name:
        return TaskType.TRADER
    elif name == TaskType.BACK_TRADER.name:
        return TaskType.BACK_TRADER
    elif name == TaskType.UPDATE_KLINES.name:
        return TaskType.UPDATE_KLINES
    elif name == TaskType.CHECK_KLINES.name:
        return TaskType.CHECK_KLINES
    elif name == TaskType.IMPORT_CSV.name:
        return TaskType.IMPORT_CSV
    elif name == TaskType.CHECK_KLINES_NUM.name:
        return TaskType.CHECK_KLINES_NUM
    elif name == TaskType.DEBUG.name:
        return TaskType.DEBUG
    return None


class TaskStateType(Enum):
    READY = "READY"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"


def parse_task_state_type(name):
    if name is None:
        return TaskStateType.READY  # Default to READY if name is None

    if name == TaskStateType.READY.name:
        return TaskStateType.READY
    elif name == TaskStateType.RUNNING.name:
        return TaskStateType.RUNNING
    elif name == TaskStateType.DONE.name:
        return TaskStateType.DONE
    elif name == TaskStateType.FAILED.name:
        return TaskStateType.FAILED

    return TaskStateType.READY  # Default to READY for unknown states


TERMINAL_STATES = frozenset({TaskStateType.DONE, TaskStateType.FAILED})
ALLOWED_TRANSITIONS = {
    TaskStateType.READY: frozenset({TaskStateType.RUNNING, TaskStateType.FAILED}),
    TaskStateType.RUNNING: frozenset({TaskStateType.DONE, TaskStateType.FAILED}),
    TaskStateType.DONE: frozenset(),
    TaskStateType.FAILED: frozenset(),
}


def can_transition(current: TaskStateType, target: TaskStateType) -> bool:
    return target in ALLOWED_TRANSITIONS.get(current, frozenset())


def is_terminal_state(state: TaskStateType) -> bool:
    return state in TERMINAL_STATES


PRIMARY_KEY = "task_id"

DATETIME_FORMART = "%Y-%m-%d %H:%M:%S"


def _json_safe_value(value):
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, dict):
        return {key: _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe_value(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe_value(item) for item in value]
    return value


class TaskState:
    def __init__(
        self,
        id: int,
        name: str,
        start_time: datetime,
        tret: TraderResult = None,
        commission: float = 0,
        strategy_start_time: int = 0,
        strategy_end_time: int = 0,
        initial_cash: float = 0,
        config_json: str = None,
        user_id: int | None = None,
        error_message: str | None = None,
    ):
        self.id = id
        self.state = TaskStateType.READY
        self.tret = tret
        self.name = name
        self.start_time = start_time
        self.commission = commission
        self.strategy_start_time = strategy_start_time
        self.strategy_end_time = strategy_end_time
        self.initial_cash = initial_cash
        self.config_json = config_json
        self.user_id = user_id
        self.error_message = error_message

    def to_dict(self) -> dict[str, Any]:
        ret: dict[str, Any] = {
            PRIMARY_KEY: self.id,
            "state": self.state.name,
            "name": self.name,
            "start_time": self.start_time.strftime(DATETIME_FORMART),
            "commission": self.commission,
        }

        if self.strategy_start_time > 0:
            ret["strategy_start_time"] = datetime.fromtimestamp(self.strategy_start_time).strftime(DATETIME_FORMART)
        if self.strategy_end_time > 0:
            ret["strategy_end_time"] = datetime.fromtimestamp(self.strategy_end_time).strftime(DATETIME_FORMART)
        if self.initial_cash > 0:
            ret["initial_cash"] = self.initial_cash
        if self.config_json:
            ret["config_json"] = self.config_json
        if self.user_id is not None:
            ret["user_id"] = self.user_id
        if self.error_message:
            ret["error_message"] = self.error_message

        if self.tret:
            ret["tret"] = self.tret.to_dict()

        return _json_safe_value(ret)

    def to_json(self):
        return json.dumps(self.to_dict(), indent=4)

    def is_running(self) -> bool:
        return self.state == TaskStateType.RUNNING

    def is_terminal(self) -> bool:
        return is_terminal_state(self.state)

    def mark_running(self) -> None:
        self.state = TaskStateType.RUNNING

    def mark_done(self) -> None:
        self.state = TaskStateType.DONE

    def mark_failed(self, error_message: str) -> None:
        self.state = TaskStateType.FAILED
        self.error_message = error_message


def parse_task_state(data) -> TaskState:
    # Safely handle PRIMARY_KEY
    task_id = data.get(PRIMARY_KEY)
    if task_id is None:
        raise ValueError(f"Missing required field: {PRIMARY_KEY}")

    # Convert task_id to int if it's a string
    if isinstance(task_id, str):
        try:
            task_id = int(task_id)
        except (ValueError, TypeError):
            raise ValueError(f"Invalid task_id format: {task_id}")

    # Parse optional timestamps
    strategy_start_time = 0
    strategy_end_time = 0
    if data.get("strategy_start_time"):
        try:
            strategy_start_time = int(datetime.strptime(data.get("strategy_start_time"), DATETIME_FORMART).timestamp())
        except (ValueError, TypeError):
            pass
    if data.get("strategy_end_time"):
        try:
            strategy_end_time = int(datetime.strptime(data.get("strategy_end_time"), DATETIME_FORMART).timestamp())
        except (ValueError, TypeError):
            pass

    ts = TaskState(
        task_id,
        data.get("name"),
        datetime.strptime(data.get("start_time"), DATETIME_FORMART),
        strategy_start_time=strategy_start_time,
        strategy_end_time=strategy_end_time,
        initial_cash=float(data.get("initial_cash", 0)),
        config_json=data.get("config_json"),
        user_id=data.get("user_id"),
        error_message=data.get("error_message"),
    )

    # Safely handle state field
    state_name = data.get("state")
    if state_name:
        ts.state = parse_task_state_type(state_name)

    # Safely handle tret field
    if "tret" in data and data["tret"] is not None:
        try:
            ts.tret = parse_trader_result(data["tret"])
        except Exception as e:
            # Log error and continue without tret
            print(f"Error parsing trader result: {e}")
            ts.tret = None

    commission = data.get("commission")
    if commission:
        ts.commission = float(commission)

    return ts


def result_return_rate(result: Any) -> float | None:
    """Total return rate used to rank completed task results; ``None`` means unrankable."""
    tret = getattr(getattr(result, "ts", None), "tret", None)
    if tret is None:
        return None
    value = getattr(tret, "total_return_rate", None)
    return float(value) if value is not None else None


def rank_results(results: list[Any]) -> list[Any]:
    """Rank task results by total return rate, highest first."""

    def sort_key(result: Any) -> float:
        rate = result_return_rate(result)
        return rate if rate is not None else float("-inf")

    return sorted(results, key=sort_key, reverse=True)


def bounded_results(results: list[Any], limit: int) -> list[Any]:
    """Keep the best ``limit`` results; ``limit <= 0`` keeps every result in arrival order."""
    if limit <= 0 or len(results) <= limit:
        return results
    return rank_results(results)[:limit]


def collect_operates(results: list[Any], limit: int = 10) -> list[dict[str, Any]]:
    """Collect operation payloads from ranked results up to ``limit``."""
    operates: list[dict[str, Any]] = []
    for result in results:
        if len(operates) >= limit:
            break
        operate = getattr(getattr(result, "ts", None), "tret", None)
        operate = getattr(operate, "operate", None)
        if operate is None:
            continue
        operates.append(operate.to_dict())
    return operates


SHORT_CAPABLE_MODES = frozenset({"SHORT_ONLY", "BOTH"})


def task_requires_short_capability(task: Any) -> bool:
    """Return True when a task's strategy parameters can open short positions."""
    params = dict(getattr(task, "strategy_params", {}) or {})
    mode = str(params.get("chainer_mode") or "LONG_ONLY").strip().upper()
    return mode in SHORT_CAPABLE_MODES


def task_state_name(cfg: Any) -> str:
    symbol_interval = getattr(cfg, "symbol_interval", None)
    symbol_name = symbol_interval.name() if symbol_interval is not None else ""
    ttype = getattr(cfg, "ttype", None)
    ttype_name = getattr(ttype, "name", str(ttype or ""))
    return f"{getattr(cfg, 'id', 0)}.{ttype_name}.{symbol_name}"


# Alias kept for callers that speak of the aggregate root rather than its snapshot.
Task = TaskState


def __getattr__(name: str):
    if name == "TaskConfig":
        from trader.core.task.config import TaskConfig

        return TaskConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
