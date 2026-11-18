"""Task domain exceptions."""

from __future__ import annotations


class TaskError(Exception):
    """Base class for task domain errors."""


class TaskNotFound(TaskError):
    def __init__(self, task_id: int):
        self.task_id = task_id
        super().__init__(f"task {task_id} not found")


class TaskOwnership(TaskError):
    def __init__(self, task_id: int, user_id: int):
        self.task_id = task_id
        self.user_id = user_id
        super().__init__(f"task {task_id} is not owned by user {user_id}")


class TaskConfigError(ValueError):
    """Raised when a task configuration is missing or invalid."""
