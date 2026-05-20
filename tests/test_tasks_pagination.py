from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from trader.rpc.app import app
from trader.rpc.models import get_taskinfo
from trader.utils.task_state import TaskStateType


class _FakeTaskManager:
    def __init__(self, states):
        self._states = states
        self.seen_user_ids = []

    async def get_all_task_state(self, user_id=None):
        self.seen_user_ids.append(user_id)
        return self._states


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _state(task_id: int, start_time: str, state: TaskStateType = TaskStateType.RUNNING):
    return SimpleNamespace(
        id=task_id,
        state=state,
        to_dict=lambda: {
            "task_id": task_id,
            "state": state.name,
            "name": f"task-{task_id}",
            "start_time": start_time,
        },
    )


@pytest.mark.anyio
async def test_get_taskinfo_applies_pagination_slice_after_sorting():
    states = [
        _state(1, "2026-05-15 10:00:00"),
        _state(2, "2026-05-15 10:01:00"),
        _state(3, "2026-05-15 10:02:00"),
    ]
    rpc_app = SimpleNamespace(task_manager=_FakeTaskManager(states))

    page_1 = await get_taskinfo(rpc_app, page=1, per_page=2)
    page_2 = await get_taskinfo(rpc_app, page=2, per_page=2)

    assert page_1.total == 3
    assert page_1.total_pages == 2
    assert [task["task_id"] for task in page_1.tasks] == [3, 2]
    assert [task["task_id"] for task in page_2.tasks] == [1]


@pytest.mark.anyio
async def test_get_taskinfo_scopes_admin_to_admin_owned_tasks():
    manager = _FakeTaskManager([_state(11, "2026-05-15 10:00:00")])
    rpc_app = SimpleNamespace(task_manager=manager)
    admin = SimpleNamespace(id=99, is_admin=True)

    await get_taskinfo(rpc_app, user=admin)

    assert manager.seen_user_ids == [99]


def test_admin_tasks_page_shows_pagination_controls_when_multiple_pages(monkeypatch):
    async def _fake_current_user(_request):
        return SimpleNamespace(id=1, is_admin=True)

    async def _fake_get_taskinfo(_app, _user, page=1, per_page=None):
        return SimpleNamespace(
            total=50,
            completed=0,
            tasks=[{"task_id": 1, "name": "task-1", "start_time": "2026-05-15 10:00:00", "state": "RUNNING"}],
            page=page,
            per_page=20,
            total_pages=3,
        )

    monkeypatch.setattr("trader.rpc.app.current_user", _fake_current_user)
    monkeypatch.setattr("trader.rpc.app.get_taskinfo", _fake_get_taskinfo)
    app.state.app = SimpleNamespace()
    client = TestClient(app)

    response = client.get("/admin/tasks?page=2")

    assert response.status_code == 200
    assert "第 2 / 3 页" in response.text
    assert "/admin/tasks?page=1" in response.text
    assert "/admin/tasks?page=3" in response.text
