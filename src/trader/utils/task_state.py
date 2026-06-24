import json
import math
from datetime import datetime
from enum import Enum
from typing import Any

from trader.strategy.trader_result import TraderResult, parse_trader_result


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
