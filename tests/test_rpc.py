import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from trader.common.common import NAME
from trader.common.config import Config
from trader.rpc.app import app
from trader.rpc.models import AcctsInfo, TasksInfo


@pytest.fixture
def rpc_test_client(monkeypatch):
    """Use context-managed TestClient so FastAPI lifespan runs (RpcApp on app.state)."""
    monkeypatch.setattr("trader.rpc.rpc_app.os.kill", lambda pid, sig: None)

    async def _sleep(logger, seconds, desc):
        await asyncio.sleep(0)

    monkeypatch.setattr("trader.rpc.rpc_app.sleep", _sleep)

    app.state.cfg = Config(api="127.0.0.1:0", tasks="[]")
    with TestClient(app) as client:
        yield client


def test_read_name(rpc_test_client):
    response = rpc_test_client.get("/name")
    assert response.status_code == 200
    assert response.json() == {"name": NAME}


def test_read_root_redirects_to_admin(rpc_test_client):
    response = rpc_test_client.get("/", follow_redirects=False)
    assert response.status_code in (302, 307)
    assert response.headers["location"].endswith("/admin")


def test_lifespan_attaches_rpc_app_to_state(rpc_test_client):
    assert hasattr(app.state, "app")
    assert app.state.app is not None


def test_admin_dashboard_returns_200_when_lifecycle_active(rpc_test_client, monkeypatch):
    monkeypatch.setattr(
        "trader.rpc.app.get_accounts_info",
        lambda rpc_app: AcctsInfo(total=0, balances=[]),
    )
    monkeypatch.setattr(
        "trader.rpc.app.get_taskinfo",
        AsyncMock(return_value=TasksInfo(total=0, completed=0, tasks=[])),
    )
    response = rpc_test_client.get("/admin")
    assert response.status_code == 200
    assert "<!DOCTYPE html>" in response.text


def test_admin_returns_503_when_rpc_app_not_initialized(monkeypatch):
    monkeypatch.delattr(app.state, "cfg", raising=False)
    monkeypatch.delattr(app.state, "app", raising=False)
    with TestClient(app) as client:
        response = client.get("/admin")
    assert response.status_code == 503
    assert response.json()["detail"] == "RPC application is not initialized"


@pytest.mark.parametrize(
    "path",
    ["/admin/tasks", "/admin/klines", "/admin/logs", "/admin/live"],
)
def test_admin_subroutes_return_503_when_rpc_app_not_initialized(monkeypatch, path):
    monkeypatch.delattr(app.state, "cfg", raising=False)
    monkeypatch.delattr(app.state, "app", raising=False)
    with TestClient(app) as client:
        response = client.get(path)
    assert response.status_code == 503
    assert response.json()["detail"] == "RPC application is not initialized"


def test_read_root_follow_redirect_returns_503_when_rpc_app_not_initialized(monkeypatch):
    monkeypatch.delattr(app.state, "cfg", raising=False)
    monkeypatch.delattr(app.state, "app", raising=False)
    with TestClient(app) as client:
        response = client.get("/", follow_redirects=True)
    assert response.status_code == 503
    assert response.json()["detail"] == "RPC application is not initialized"
