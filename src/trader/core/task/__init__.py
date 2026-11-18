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
    task_requires_short_capability,
    task_state_name,
)
from trader.core.task.exceptions import FundReservationError, TaskConfigError, TaskError, TaskNotFound, TaskOwnership
from trader.core.task.interfaces import FundReservationStore, TaskEventPublisher, TaskQuery, TaskRepository, TaskRunner
from trader.core.task.use_cases import (
    CancelTaskOpenOrders,
    CleanupRunningTasksBeforeStart,
    GetTask,
    ListTasks,
    PlanStartupTasks,
    PreflightLiveTaskFunds,
    RecoverRunningTasks,
    ReleaseTaskFunds,
    RestoreRecoveredTaskBudget,
    StartupExecutionPlan,
    StopTask,
    StopUserRunningTasks,
    SubmitTasks,
    TaskPage,
    TaskScope,
    paginate,
)


def __getattr__(name: str):
    if name == "TaskConfig":
        from trader.core.task.config import TaskConfig

        return TaskConfig
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CancelTaskOpenOrders",
    "CleanupRunningTasksBeforeStart",
    "FundReservationError",
    "FundReservationStore",
    "GetTask",
    "ListTasks",
    "PlanStartupTasks",
    "PreflightLiveTaskFunds",
    "RecoverRunningTasks",
    "ReleaseTaskFunds",
    "RestoreRecoveredTaskBudget",
    "StartupExecutionPlan",
    "StopTask",
    "StopUserRunningTasks",
    "SubmitTasks",
    "Task",
    "TaskConfig",
    "TaskConfigError",
    "TaskError",
    "TaskEventPublisher",
    "TaskNotFound",
    "TaskOwnership",
    "TaskPage",
    "TaskQuery",
    "TaskRepository",
    "TaskRunner",
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
    "task_requires_short_capability",
    "task_state_name",
]
