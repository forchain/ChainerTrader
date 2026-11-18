import asyncio
from datetime import datetime
from types import SimpleNamespace

import pytest

from trader.core.task.domain import TaskState, TaskStateType
from trader.core.task.exceptions import TaskNotFound, TaskOwnership
from trader.core.task.use_cases import GetTask, ListTasks, TaskScope, paginate


class _FakeTaskQuery:
    def __init__(self, states):
        self.states = list(states)
        self.seen_user_ids = []

    async def get_all_task_state(self, user_id=None):
        self.seen_user_ids.append(user_id)
        return [state for state in self.states if user_id is None or state.user_id == user_id]

    async def get_task_state(self, task_id, user_id=None):
        for state in self.states:
            if state.id != task_id:
                continue
            if user_id is not None and state.user_id != user_id:
                return None
            return state
        return None


def _state(task_id: int, start_time: str, user_id: int | None = None):
    state = TaskState(task_id, f"task-{task_id}", datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S"), user_id=user_id)
    state.state = TaskStateType.RUNNING
    return state


def test_list_tasks_scopes_to_user_and_paginates_newest_first():
    query = _FakeTaskQuery(
        [
            _state(1, "2026-05-15 10:00:00", user_id=10),
            _state(2, "2026-05-15 10:02:00", user_id=10),
            _state(3, "2026-05-15 10:03:00", user_id=20),
        ]
    )

    page = asyncio.run(ListTasks(query).execute(TaskScope.for_user(10), page=1, per_page=1))

    assert query.seen_user_ids == [10]
    assert page.total == 2
    assert page.total_pages == 2
    assert [state.id for state in page.items] == [2]


def test_list_tasks_admin_scope_reads_all_tasks():
    query = _FakeTaskQuery(
        [
            _state(1, "2026-05-15 10:00:00", user_id=10),
            _state(2, "2026-05-15 10:01:00", user_id=20),
        ]
    )
    admin = SimpleNamespace(id=99, is_admin=True)

    page = asyncio.run(ListTasks(query).execute(TaskScope.for_actor(admin)))

    assert query.seen_user_ids == [None]
    assert [state.id for state in page.items] == [2, 1]
    assert page.per_page == 2


def test_get_task_distinguishes_missing_from_foreign_task():
    query = _FakeTaskQuery([_state(1, "2026-05-15 10:00:00", user_id=10)])

    with pytest.raises(TaskNotFound):
        asyncio.run(GetTask(query).execute(99, TaskScope.for_user(10)))
    with pytest.raises(TaskOwnership):
        asyncio.run(GetTask(query).execute(1, TaskScope.for_user(20)))
    assert asyncio.run(GetTask(query).execute(1, TaskScope.for_user(10))).id == 1


def test_get_task_admin_scope_can_read_any_owner():
    query = _FakeTaskQuery([_state(1, "2026-05-15 10:00:00", user_id=10)])
    admin = SimpleNamespace(id=99, is_admin=True)

    assert asyncio.run(GetTask(query).execute(1, TaskScope.for_actor(admin))).id == 1


def test_paginate_clamps_page_and_per_page_without_losing_totals():
    page = paginate(["a", "b", "c"], page=9, per_page=2)

    assert page.items == ["c"]
    assert (page.page, page.per_page, page.total, page.total_pages) == (2, 2, 3, 2)
    assert paginate(["a", "b"], page=1, per_page=None).per_page == 2
