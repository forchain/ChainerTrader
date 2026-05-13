from types import SimpleNamespace

import pytest

from trader.rpc.api.tasks import get_tasks
from trader.rpc.models import get_taskinfo
from trader.utils.task_state import TaskStateType


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _task_state(task_id: int, state: TaskStateType, start_time: str):
    return SimpleNamespace(
        id=task_id,
        state=state,
        to_dict=lambda: {"id": task_id, "state": state.name, "start_time": start_time},
    )


@pytest.mark.anyio
async def test_get_taskinfo_supports_async_task_manager_and_sorts_descending():
    states = [
        _task_state(1, TaskStateType.RUNNING, "2026-05-13 20:00:00"),
        _task_state(2, TaskStateType.DONE, "2026-05-13 21:00:00"),
    ]
    async def get_all_task_state():
        return states

    app = SimpleNamespace(task_manager=SimpleNamespace(get_all_task_state=get_all_task_state))

    result = await get_taskinfo(app)

    assert result.total == 2
    assert result.completed == 1
    assert [task["id"] for task in result.tasks] == [2, 1]


@pytest.mark.anyio
async def test_tasks_api_get_tasks_awaits_task_state_coroutine():
    states = [
        _task_state(7, TaskStateType.RUNNING, "2026-05-13 20:00:00"),
        _task_state(8, TaskStateType.DONE, "2026-05-13 21:00:00"),
    ]
    async def get_all_task_state():
        return states

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(app=SimpleNamespace(task_manager=SimpleNamespace(get_all_task_state=get_all_task_state)))
        )
    )

    payload = await get_tasks(request)

    assert payload == [
        {"id": 7, "state": "RUNNING", "start_time": "2026-05-13 20:00:00"},
        {"id": 8, "state": "DONE", "start_time": "2026-05-13 21:00:00"},
    ]

