import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from trader.common.common import NAME
from trader.common.config import Config
from trader.exchange.balance import Balance
from trader.rpc.app import app
from trader.rpc.models import AcctsInfo, TasksInfo, get_accounts_info


@pytest.fixture
def rpc_test_client(monkeypatch):
    """Use context-managed TestClient so FastAPI lifespan runs (RpcApp on app.state)."""
    monkeypatch.setattr("trader.rpc.rpc_app.os.kill", lambda pid, sig: None)

    async def _sleep(logger, seconds, desc):
        await asyncio.sleep(0)

    monkeypatch.setattr("trader.rpc.rpc_app.sleep", _sleep)

    app.state.cfg = Config(api="127.0.0.1:8100", tasks="[]")
    with TestClient(app) as client:
        yield client


def test_read_name(rpc_test_client):
    response = rpc_test_client.get("/name")
    assert response.status_code == 200
    assert response.json() == {"name": NAME}


def test_read_root_renders_public_homepage(rpc_test_client):
    response = rpc_test_client.get("/")
    assert response.status_code == 200
    assert "欢迎使用 ChainerTrader" in response.text
    assert "统计信息" not in response.text
    assert "最近任务" not in response.text


def test_lifespan_attaches_rpc_app_to_state(rpc_test_client):
    assert hasattr(app.state, "app")
    assert app.state.app is not None


def test_admin_dashboard_returns_200_when_lifecycle_active(rpc_test_client, monkeypatch):
    monkeypatch.setattr(
        "trader.rpc.app.get_accounts_info",
        lambda rpc_app: AcctsInfo(
            total=3,
            balances=[
                Balance(asset="USDT", free=12.5, locked=0.0),
                Balance(asset="BTC", free=0.0, locked=0.01),
                Balance(asset="ETH", free=1.25, locked=0.0),
            ],
        ),
    )
    monkeypatch.setattr(
        "trader.rpc.app.get_taskinfo",
        AsyncMock(return_value=TasksInfo(total=0, completed=0, tasks=[])),
    )
    response = rpc_test_client.get("/admin")
    assert response.status_code == 200
    assert "<!DOCTYPE html>" in response.text
    assert "面向高并发并行优化的量化平台" in response.text
    assert "通过并行计算大规模验证策略与参数组合" in response.text
    assert "USDT" not in response.text
    assert "ETH" not in response.text
    assert "BTC" not in response.text


def test_public_homepage_renders_when_anonymous(rpc_test_client):
    response = rpc_test_client.get("/")
    assert response.status_code == 200
    assert "欢迎使用 ChainerTrader" in response.text
    assert "项目概览" not in response.text
    assert "登录后继续" not in response.text
    assert "面向高并发并行优化的量化平台" in response.text


def test_public_nav_hides_admin_dropdown_for_anonymous(rpc_test_client):
    response = rpc_test_client.get("/")
    assert response.status_code == 200
    assert 'href="/"' in response.text
    assert 'href="/login"' in response.text
    assert 'href="/account"' not in response.text
    assert 'href="/admin/tasks"' not in response.text
    assert 'href="/admin/live"' not in response.text
    assert 'href="/admin/logs"' not in response.text
    assert "管理员" not in response.text
    assert 'href="/admin/users"' not in response.text


def test_admin_nav_shows_admin_dropdown_for_user_management_only(monkeypatch):
    from fastapi import FastAPI
    from fastapi import Request
    from types import SimpleNamespace

    from trader.auth.context import SessionAuthMiddleware
    from trader.rpc.app import templates

    nav_app = FastAPI()
    nav_app.add_middleware(SessionAuthMiddleware)
    nav_app.state.cfg = Config(auth_username="admin", auth_password="marketBot2026")
    nav_app.state.app = SimpleNamespace(
        db_manager=SimpleNamespace(user=SimpleNamespace()),
        version=lambda: "0.1.1",
    )

    @nav_app.get("/")
    async def root(request: Request):
        return templates.TemplateResponse(
            request,
            "index.html",
            {"version": "0.1.1", "user": SimpleNamespace(is_admin=True)},
        )

    @nav_app.get("/account")
    async def account():
        return {"page": "account"}

    @nav_app.get("/admin")
    async def admin():
        return {"page": "admin"}

    with TestClient(nav_app) as client:
        home = client.get("/")
        assert home.status_code == 200
        assert client.get("/account", follow_redirects=False).status_code == 303
        assert client.get("/admin", follow_redirects=False).status_code == 303
        assert "管理员" in home.text
        assert 'href="/account"' in home.text
        assert 'href="/admin/tasks"' in home.text
        assert 'href="/admin/live"' in home.text
        assert 'href="/admin/logs"' in home.text
        assert 'href="/admin/users"' in home.text
        assert 'href="/login"' not in home.text


def test_account_page_shows_balances_with_default_filter(rpc_test_client, monkeypatch):
    monkeypatch.setattr(
        "trader.rpc.app.require_user",
        AsyncMock(return_value=type("User", (), {"id": 1, "username": "trader", "role": "user"})()),
    )
    monkeypatch.setattr(
        "trader.rpc.app.get_accounts_info",
        lambda rpc_app: AcctsInfo(
            total=3,
            balances=[
                Balance(asset="USDT", free=12.5, locked=0.0),
                Balance(asset="BTC", free=0.0, locked=0.01),
                Balance(asset="ETH", free=1.25, locked=0.0),
            ],
        ),
    )
    response = rpc_test_client.get("/account")
    assert response.status_code == 200
    assert "账户余额" in response.text
    assert 'id="toggle-all-assets"' in response.text
    assert "USDT" in response.text
    assert "ETH" in response.text
    assert "BTC" in response.text
    assert 'data-has-free="false"' in response.text
    assert 'class="account-row d-none"' in response.text
    assert "创建 API Key" in response.text
    assert "重置 API Key" not in response.text
    assert "类型" not in response.text


def test_account_page_shows_existing_credential_summary_and_reset_button(rpc_test_client, monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "trader.rpc.app.require_user",
        AsyncMock(return_value=type("User", (), {"id": 1, "username": "trader", "role": "user"})()),
    )
    monkeypatch.setattr(
        "trader.rpc.app.get_accounts_info",
        lambda rpc_app: AcctsInfo(total=0, balances=[]),
    )

    class _Credential:
        exchange = "primary-key"
        masked_api_key = "abcd***wxyz"

    credential_repo = SimpleNamespace(list_by_user=AsyncMock(return_value=[_Credential()]))
    rpc_stub = SimpleNamespace(
        db_manager=SimpleNamespace(exchange_credential=credential_repo),
        exchange=None,
        logger=None,
    )
    monkeypatch.setattr("trader.rpc.app._require_rpc_app", lambda request: rpc_stub)

    response = rpc_test_client.get("/account")
    assert response.status_code == 200
    assert "创建 API Key" not in response.text
    assert "重置 API Key" in response.text
    assert "默认" in response.text
    assert "abcd***wxyz" in response.text


def test_accounts_info_returns_empty_when_exchange_is_not_configured():
    assert get_accounts_info(type("AppStub", (), {"exchange": None})()) == AcctsInfo(total=0, balances=[])


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
    assert response.status_code == 200
    assert "欢迎使用 ChainerTrader" in response.text
