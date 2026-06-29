from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from trader.auth.context import SessionAuthMiddleware
from trader.auth.credentials import encrypt_secret
from trader.common.config import Config
from trader.exchange.exchange_config import ExchangeConfig
from trader.rpc.api.exchange.account import router as account_router
from trader.rpc.api.exchange.account_commission import router as account_commission_router


class _UserRepo:
    async def get_session(self, _session_hash):
        return None


def _client_with_user_exchange(monkeypatch, *, account_payload=None, commission_payload=None):
    service_key = "service-secret"
    credential = SimpleNamespace(
        id=22,
        encrypted_api_key=encrypt_secret(service_key, "user-api-key"),
        encrypted_api_secret=encrypt_secret(service_key, "user-api-secret"),
        masked_api_key="user***ikey",
    )
    captured = {}

    class _CredentialRepo:
        async def get_default(self, user_id, exchange):
            assert user_id == 5
            assert exchange == "BINANCE"
            return credential

    class _SystemExchange:
        cfg = ExchangeConfig(api_key="system-api-key", api_secret="system-api-secret")

        def get_account(self):
            raise AssertionError("account API must not use the system exchange")

        def account_commission(self, symbol=None):
            raise AssertionError("commission API must not use the system exchange")

    class _UserExchange:
        def __init__(self, cfg, _logger=None):
            self.cfg = cfg
            captured["api_key"] = cfg.api_key
            captured["api_secret"] = cfg.api_secret

        def get_account(self):
            return account_payload or {"source": "user", "api_key": self.cfg.api_key}

        def account_commission(self, symbol=None):
            return commission_payload or {"source": "user", "symbol": symbol, "api_key": self.cfg.api_key}

    monkeypatch.setattr("trader.exchange.binance.exchange.BinanceExchange", _UserExchange)

    app = FastAPI()
    app.add_middleware(SessionAuthMiddleware)
    app.include_router(account_router, prefix="/api/exchange/account")
    app.include_router(account_commission_router, prefix="/api/exchange/account_commission")
    app.state.cfg = Config(auth_username="admin", auth_password="AdminPass123", secret_key=service_key)
    app.state.app = SimpleNamespace(
        db_manager=SimpleNamespace(user=_UserRepo(), exchange_credential=_CredentialRepo()),
        exchange=_SystemExchange(),
        logger=None,
    )

    @app.middleware("http")
    async def inject_user(request, call_next):
        request.state.user = SimpleNamespace(id=5, username="alice", role="user", status="active", must_change_password=False, is_admin=False)
        return await call_next(request)

    return TestClient(app), captured


def test_exchange_account_api_uses_user_credential_not_system_exchange(monkeypatch):
    client, captured = _client_with_user_exchange(monkeypatch)

    response = client.get("/api/exchange/account")

    assert response.status_code == 200
    assert response.json() == {"source": "user", "api_key": "user-api-key"}
    assert captured == {"api_key": "user-api-key", "api_secret": "user-api-secret"}


def test_exchange_account_commission_api_uses_user_credential_not_system_exchange(monkeypatch):
    client, captured = _client_with_user_exchange(monkeypatch)

    response = client.get("/api/exchange/account_commission", params={"symbol": "BTCUSDT"})

    assert response.status_code == 200
    assert response.json() == {"source": "user", "symbol": "BTCUSDT", "api_key": "user-api-key"}
    assert captured == {"api_key": "user-api-key", "api_secret": "user-api-secret"}
