from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from trader.auth.context import SessionAuthMiddleware
from trader.common.config import Config
from trader.rpc.api.tasks import router


class _UserRepo:
    async def get_session(self, _session_hash):
        return None


class _CredentialRepo:
    async def get_default(self, _user_id, _exchange):
        return None


def test_user_owned_live_task_requires_saved_exchange_credential():
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware)
    app.include_router(router, prefix="/api/tasks")
    app.state.cfg = Config(auth_username="admin", auth_password="AdminPass123", secret_key="service-secret")
    app.state.app = SimpleNamespace(
        db_manager=SimpleNamespace(user=_UserRepo(), exchange_credential=_CredentialRepo()),
        send_add_tasks_msg=lambda *_args, **_kwargs: {"result": "should-not-start"},
    )

    @app.middleware("http")
    async def inject_user(request, call_next):
        request.state.user = SimpleNamespace(id=5, username="alice", role="user", status="active", must_change_password=False, is_admin=False)
        return await call_next(request)

    client = TestClient(app)
    response = client.post(
        "/api/tasks",
        content='[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1h","strategy":"macd_triple_divergence"}]',
    )

    assert response.status_code == 400
    assert "missing BINANCE API credential" in response.json()["detail"]


def test_user_owned_live_task_requires_service_key():
    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware)
    app.include_router(router, prefix="/api/tasks")
    app.state.cfg = Config(auth_username="admin", auth_password="AdminPass123")
    app.state.app = SimpleNamespace(
        db_manager=SimpleNamespace(user=_UserRepo(), exchange_credential=_CredentialRepo()),
        send_add_tasks_msg=lambda *_args, **_kwargs: {"result": "should-not-start"},
    )

    @app.middleware("http")
    async def inject_user(request, call_next):
        request.state.user = SimpleNamespace(id=5, username="alice", role="user", status="active", must_change_password=False, is_admin=False)
        return await call_next(request)

    client = TestClient(app)
    response = client.post(
        "/api/tasks",
        content='[{"task_type":"TRADER","symbol":"BTC-USDT","interval":"1h","strategy":"macd_triple_divergence"}]',
    )

    assert response.status_code == 400
    assert "TRADER_SECRET_KEY" in response.json()["detail"]
