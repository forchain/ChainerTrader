"""Task bounded context: task state, configuration, lifecycle rules, and use cases."""

from trader.core.task.domain import (
    Task,
    TaskState,
    TaskStateType,
    TaskType,
    TraderResult,
    bounded_results,
    can_transition,
    collect_operates,
    is_terminal_state,
    parse_task_state,
    parse_task_state_type,
    parse_task_type,
    parse_trader_result,
    rank_results,
    result_return_rate,
)
from trader.core.task.exceptions import TaskConfigError, TaskError, TaskNotFound, TaskOwnership
from trader.core.task.interfaces import TaskQuery, TaskRepository
from trader.core.task.use_cases import GetTask, ListTasks, TaskPage, TaskScope, paginate


def __getattr__(name: str):
    if name == "TaskConfig":
        from trader.core.task.config import TaskConfig

        return TaskConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "GetTask",
    "ListTasks",
    "Task",
    "TaskConfig",
    "TaskConfigError",
    "TaskError",
    "TaskNotFound",
    "TaskOwnership",
    "TaskPage",
    "TaskQuery",
    "TaskRepository",
    "TaskScope",
    "TaskState",
    "TaskStateType",
    "TaskType",
    "TraderResult",
    "bounded_results",
    "can_transition",
    "collect_operates",
    "is_terminal_state",
    "paginate",
    "parse_task_state",
    "parse_task_state_type",
    "parse_task_type",
    "parse_trader_result",
    "rank_results",
    "result_return_rate",
]
