from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from trader.common.config import Config
from trader.core.exchange.exceptions import ExchangeConnectivityError, UserExchangeCredentialError
from trader.core.identity.exceptions import AuthenticationError, PasswordPolicyError
from trader.core.optimization.exceptions import OptimizationConfigError, RankingError
from trader.core.task.domain import TaskState, TaskStateType
from trader.core.task.exceptions import FundReservationError, TaskNotFound, TaskOwnership


def test_http_adapter_has_no_module_level_app_or_rpc_app():
    import trader.adapters.inbound.http as http_pkg
    import trader.adapters.inbound.http.factory as http_factory

    assert not hasattr(http_pkg, "app")
    assert not hasattr(http_factory, "app")
    assert not hasattr(http_factory, "RpcApp")


def test_exception_translation_table_maps_domain_exceptions():
    from trader.adapters.inbound.http.exceptions import translate_domain_exception

    cases = [
        (AuthenticationError("bad creds"), 401),
        (PasswordPolicyError("weak"), 422),
        (TaskNotFound(7), 404),
        (TaskOwnership(7, 2), 403),
        (UserExchangeCredentialError("missing cred"), 400),
        (ExchangeConnectivityError("ping failed"), 400),
        (FundReservationError("insufficient funds"), 400),
        (OptimizationConfigError("bad opt"), 400),
        (RankingError("bad rank"), 400),
    ]
    for exc, expected_status in cases:
        http_exc = translate_domain_exception(exc)
        assert http_exc.status_code == expected_status
        assert http_exc.detail == str(exc)


class _FakeTaskManager:
    def __init__(self, states: list[TaskState]):
        self._states = {ts.id: ts for ts in states}
        self.db_manager = None

    async def get_all_task_state(self, user_id: int | None = None) -> list[TaskState]:
        items = list(self._states.values())
        if user_id is not None:
            items = [ts for ts in items if ts.user_id == user_id]
        return items

    async def get_task_state(self, task_id: int, user_id: int | None = None) -> TaskState | None:
        ts = self._states.get(task_id)
        if ts is None:
            return None
        if user_id is not None and ts.user_id != user_id:
            return None
        return ts

    def close_task(self, task_id: int, user_id: int | None = None) -> bool:
        return False

    def del_task(self, task_id: int, user_id: int | None = None) -> bool:
        return False


class _FakeStat:
    def get_operates(self):
        return []


def test_create_app_with_fakes_exercises_routes_without_db_exchange_or_network():
    from trader.adapters.inbound.http import create_app

    ts = TaskState(11, "11.TRADER.BTCUSDT-1h", datetime(2026, 1, 1), user_id=0)
    ts.state = TaskStateType.DONE
    fake_user = SimpleNamespace(id=0, username="local-admin", role="admin", status="active", is_admin=True, must_change_password=False)

    composition = SimpleNamespace(
        cfg=Config(),
        logger=SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None, debug=lambda *a, **k: None),
        live_event_bus=SimpleNamespace(subscribe=None, unsubscribe=None, recent=lambda *a, **k: []),
        db_manager=SimpleNamespace(kline=None, user=None, exchange_credential=None, task=None),
        exchange=None,
        task_manager=_FakeTaskManager([ts]),
        stat=_FakeStat(),
        version=lambda: "0.79.3-test",
        current_user_resolver=lambda request: fake_user,
    )

    app = create_app(composition)
    assert isinstance(app, FastAPI)

    with TestClient(app) as client:
        assert client.get("/name").status_code == 200
        assert client.get("/api/tasks").json()[0]["task_id"] == 11
        assert client.get("/api/task", params={"id": 11}).json()["task_id"] == 11
        assert client.get("/api/task", params={"id": 999}).json() == {"id": 999, "error": "invalid"}
        assert client.get("/api/operates").status_code == 200
        assert client.get("/admin/live").status_code == 200
        assert client.get("/admin/tasks").status_code == 200
        assert client.get("/static/js/main.js").status_code == 200
        invalid_submit = client.post("/api/tasks", content="configs/tasks/does_not_exist.json")
        assert invalid_submit.status_code == 400
        assert "detail" in invalid_submit.json()
