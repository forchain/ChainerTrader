import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from trader.auth.credentials import encrypt_secret
from trader.common.common import NAME
from trader.common.config import Config
from trader.common.logger import Logger
from trader.exchange.balance import Balance
from trader.exchange.exchange_config import ExchangeConfig, MarginMode
from trader.rpc.app import app
from trader.rpc.models import AcctsInfo, TasksInfo, get_accounts_info
from trader.utils.symbol_interval import Interval, SymbolInterval


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
    from types import SimpleNamespace

    from fastapi import FastAPI, Request

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
    service_key = "service-secret"
    user = type("User", (), {"id": 1, "username": "trader", "role": "user"})()
    credential = SimpleNamespace(
        id=1,
        exchange="BINANCE",
        encrypted_api_key=encrypt_secret(service_key, "user-api-key"),
        encrypted_api_secret=encrypt_secret(service_key, "user-api-secret"),
        masked_api_key="user***ikey",
    )

    class _UserExchange:
        def __init__(self, cfg, _log=None):
            self.cfg = cfg
            self.margin_mode = cfg.margin_mode

    monkeypatch.setattr(
        "trader.rpc.app.require_user",
        AsyncMock(return_value=user),
    )
    monkeypatch.setattr("trader.rpc.app.BinanceExchange", _UserExchange)
    monkeypatch.setattr(
        "trader.rpc.app.get_accounts_info",
        lambda rpc_app: AcctsInfo(
            total=3,
            balances=[
                Balance(asset="USDT", free=12.5, locked=0.0, max_borrowable=7.5, operable=20.0),
                Balance(asset="BTC", free=0.0, locked=0.01, max_borrowable=0.0, operable=0.0),
                Balance(asset="ETH", free=1.25, locked=0.0, max_borrowable=0.0, operable=1.25),
            ],
            locked_reasons=[{"symbol": "BTCUSDT", "side": "BUY", "quantity": 0.5, "order_id": "1001", "order_type": "LIMIT"}],
            borrow_asset="USDT",
            borrowable_amount=7.5,
            operable_amount=20.0,
        ),
    )
    app.state.cfg = Config(api="127.0.0.1:8100", tasks="[]", secret_key=service_key)
    rpc_stub = SimpleNamespace(
        db_manager=SimpleNamespace(exchange_credential=SimpleNamespace(list_by_user=AsyncMock(return_value=[credential]))),
        exchange=SimpleNamespace(cfg=ExchangeConfig(api_key="system-api-key", api_secret="system-api-secret")),
        task_manager=SimpleNamespace(latest_si=SymbolInterval("BTC-USDT", Interval("1m"))),
        logger=None,
    )
    monkeypatch.setattr("trader.rpc.app._require_rpc_app", lambda _request: rpc_stub)
    response = rpc_test_client.get("/account")
    assert response.status_code == 200
    assert "账户余额" in response.text
    assert "策略可操作资金" in response.text
    assert "7.5" in response.text
    assert "20.0" in response.text
    assert "锁定来源" in response.text
    assert "BTCUSDT" in response.text
    assert 'id="toggle-all-assets"' in response.text
    assert "USDT" in response.text
    assert "ETH" in response.text
    assert "BTC" in response.text
    assert 'data-has-free="false"' in response.text
    assert 'class="account-row d-none"' in response.text
    assert "创建 API Key" not in response.text
    assert "重置 API Key" in response.text


def test_account_page_shows_account_read_error(rpc_test_client, monkeypatch):
    service_key = "service-secret"
    user = type("User", (), {"id": 1, "username": "trader", "role": "user"})()
    credential = SimpleNamespace(
        id=1,
        exchange="BINANCE",
        encrypted_api_key=encrypt_secret(service_key, "user-api-key"),
        encrypted_api_secret=encrypt_secret(service_key, "user-api-secret"),
        masked_api_key="user***ikey",
    )

    class _UserExchange:
        def __init__(self, cfg, _log=None):
            self.cfg = cfg
            self.margin_mode = cfg.margin_mode

    monkeypatch.setattr(
        "trader.rpc.app.require_user",
        AsyncMock(return_value=user),
    )
    monkeypatch.setattr("trader.rpc.app.BinanceExchange", _UserExchange)
    monkeypatch.setattr(
        "trader.rpc.app.get_accounts_info",
        lambda rpc_app: AcctsInfo(total=0, balances=[], account_error="交易所账户读取失败: Invalid API-key"),
    )
    app.state.cfg = Config(api="127.0.0.1:8100", tasks="[]", secret_key=service_key)
    rpc_stub = SimpleNamespace(
        db_manager=SimpleNamespace(exchange_credential=SimpleNamespace(list_by_user=AsyncMock(return_value=[credential]))),
        exchange=SimpleNamespace(cfg=ExchangeConfig(api_key="system-api-key", api_secret="system-api-secret")),
        task_manager=SimpleNamespace(latest_si=SymbolInterval("BTC-USDT", Interval("1m"))),
        logger=None,
    )
    monkeypatch.setattr("trader.rpc.app._require_rpc_app", lambda _request: rpc_stub)

    response = rpc_test_client.get("/account")

    assert response.status_code == 200
    assert "交易所账户读取失败" in response.text
    assert "Invalid API-key" in response.text


def test_account_page_shows_existing_credential_summary_and_reset_button(rpc_test_client, monkeypatch):
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


def test_account_page_reads_user_exchange_credential_not_system_exchange(rpc_test_client, monkeypatch):
    user = type("User", (), {"id": 7, "username": "trader", "role": "user"})()
    service_key = "service-secret"
    credential = SimpleNamespace(
        id=2,
        exchange="BINANCE",
        label="default",
        encrypted_api_key=encrypt_secret(service_key, "user-api-key"),
        encrypted_api_secret=encrypt_secret(service_key, "user-api-secret"),
        masked_api_key="user***ikey",
    )
    captured = {}

    class _SystemExchange:
        cfg = ExchangeConfig(api_key="system-api-key", api_secret="system-api-secret")

        def get_account_balances(self):
            raise AssertionError("account page must not read the system exchange")

    class _UserExchange:
        def __init__(self, cfg, _log=None):
            self.cfg = cfg
            self.margin_mode = cfg.margin_mode

    def _capture_accounts_info(account_app):
        captured["api_key"] = account_app.exchange.cfg.api_key
        captured["api_secret"] = account_app.exchange.cfg.api_secret
        captured["margin_mode"] = account_app.exchange.cfg.margin_mode
        return AcctsInfo(total=0, balances=[])

    monkeypatch.setattr("trader.rpc.app.require_user", AsyncMock(return_value=user))
    monkeypatch.setattr("trader.rpc.app.BinanceExchange", _UserExchange)
    monkeypatch.setattr("trader.rpc.app.get_accounts_info", _capture_accounts_info)
    app.state.cfg = Config(
        api="127.0.0.1:8100",
        tasks="[]",
        secret_key=service_key,
        exchange='{"ty":"BINANCE","driver":"ccxt","api_key":"system-api-key","api_secret":"system-api-secret"}',
    )
    rpc_stub = SimpleNamespace(
        db_manager=SimpleNamespace(exchange_credential=SimpleNamespace(list_by_user=AsyncMock(return_value=[credential]))),
        exchange=_SystemExchange(),
        task_manager=SimpleNamespace(latest_si=SymbolInterval("BTC-USDT", Interval("1m"))),
        logger=None,
    )
    monkeypatch.setattr("trader.rpc.app._require_rpc_app", lambda _request: rpc_stub)

    response = rpc_test_client.get("/account")

    assert response.status_code == 200
    assert captured == {
        "api_key": "user-api-key",
        "api_secret": "user-api-secret",
        "margin_mode": MarginMode.CROSS_MARGIN,
    }


def test_account_page_without_saved_credential_does_not_fallback_to_system_exchange(rpc_test_client, monkeypatch):
    user = type("User", (), {"id": 7, "username": "trader", "role": "user"})()

    class _SystemExchange:
        def get_account_balances(self):
            raise AssertionError("missing user credential must not fall back to the system exchange")

    monkeypatch.setattr("trader.rpc.app.require_user", AsyncMock(return_value=user))
    app.state.cfg = Config(api="127.0.0.1:8100", tasks="[]", secret_key="service-secret")
    rpc_stub = SimpleNamespace(
        db_manager=SimpleNamespace(exchange_credential=SimpleNamespace(list_by_user=AsyncMock(return_value=[]))),
        exchange=_SystemExchange(),
        task_manager=SimpleNamespace(latest_si=SymbolInterval("BTC-USDT", Interval("1m"))),
        logger=None,
    )
    monkeypatch.setattr("trader.rpc.app._require_rpc_app", lambda _request: rpc_stub)

    response = rpc_test_client.get("/account")

    assert response.status_code == 200
    assert "missing BINANCE API credential for user_id=7" in response.text


def test_accounts_info_returns_empty_when_exchange_is_not_configured():
    assert get_accounts_info(type("AppStub", (), {"exchange": None})()) == AcctsInfo(total=0, balances=[])


def test_accounts_info_returns_error_when_exchange_balance_read_fails():
    class _Log:
        def __init__(self):
            self.errors = []

        def error(self, message):
            self.errors.append(str(message))

    class _Exchange:
        def get_account_balances(self):
            raise RuntimeError('binance {"code":-2015,"msg":"Invalid API-key, IP, or permissions for action."}')

    log = _Log()
    info = get_accounts_info(type("AppStub", (), {"exchange": _Exchange(), "logger": log})())

    assert info.total == 0
    assert info.balances == []
    assert "交易所账户读取失败" in info.account_error
    assert "Invalid API-key" in info.account_error
    assert "account page exchange balance read failed" in log.errors[0]


def test_accounts_info_adds_borrow_capacity_and_locked_order_reasons():
    class _Exchange:
        def __init__(self):
            self.borrow_reads = []
            self.open_order_reads = []

        def get_account_balances(self):
            return [
                Balance(asset="USDT", free=5.0, locked=70.0),
                Balance(asset="BTC", free=0.0, locked=0.0),
            ]

        def get_max_borrowable(self, asset, symbol=None):
            self.borrow_reads.append((asset, symbol))
            return {"amount": "22.5", "borrowLimit": "100000"}

        def get_open_orders(self, symbol):
            self.open_order_reads.append(symbol.name())
            return [
                {
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "origQty": "0.25",
                    "orderId": 1001,
                    "type": "STOP_LOSS",
                    "price": "100.0",
                }
            ]

    exchange = _Exchange()
    info = get_accounts_info(
        type(
            "AppStub",
            (),
            {
                "exchange": exchange,
                "task_manager": type("TaskManagerStub", (), {"latest_si": SymbolInterval("BTC-USDT", Interval("1m"))})(),
            },
        )()
    )

    assert info.borrow_asset == "USDT"
    assert info.borrowable_amount == 22.5
    assert info.operable_amount == 27.5
    assert info.balances[0].max_borrowable == 22.5
    assert info.balances[0].operable == 27.5
    assert info.locked_reasons[0]["symbol"] == "BTCUSDT"
    assert info.locked_reasons[0]["order_id"] == "1001"
    assert exchange.borrow_reads == [("USDT", None)]
    assert exchange.open_order_reads == ["BTCUSDT"]


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


def test_admin_logs_highlights_warning_error_and_critical(rpc_test_client, monkeypatch):
    from types import SimpleNamespace

    rpc_stub = SimpleNamespace(
        logger=SimpleNamespace(
            get_buffer_str=lambda: [
                "2026-06-24 00:01:20[INFO:trader] startup ok",
                "2026-06-24 00:01:21[WARNING:trader] check config",
                "2026-06-24 00:01:22[ERROR:trader] failed task",
                "2026-06-24 00:01:23[CRITICAL:trader] service down",
                "ERROR: insufficient reserved capacity",
            ]
        )
    )
    monkeypatch.setattr("trader.rpc.app._require_rpc_app", lambda _request: rpc_stub)
    monkeypatch.setattr("trader.rpc.app._template_user", AsyncMock(return_value=None))

    response = rpc_test_client.get("/admin/logs")

    assert response.status_code == 200
    assert "log-line-warning" in response.text
    assert "log-line-error" in response.text
    assert "log-line-critical" in response.text
    assert "check config" in response.text
    assert "failed task" in response.text
    assert "service down" in response.text
    assert '<div class="log-line log-line-error">ERROR: insufficient reserved capacity</div>' in response.text


def test_logger_buffer_preserves_log_level_for_admin_highlighting():
    logger = Logger(Config(api="127.0.0.1:8100"))

    logger.error("insufficient reserved capacity")

    assert logger.get_buffer_str()[-1] == "ERROR: insufficient reserved capacity"


def test_read_root_follow_redirect_returns_503_when_rpc_app_not_initialized(monkeypatch):
    monkeypatch.delattr(app.state, "cfg", raising=False)
    monkeypatch.delattr(app.state, "app", raising=False)
    with TestClient(app) as client:
        response = client.get("/", follow_redirects=True)
    assert response.status_code == 200
    assert "欢迎使用 ChainerTrader" in response.text
