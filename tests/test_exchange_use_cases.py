import asyncio
from types import SimpleNamespace

import pytest

from trader.adapters.outbound.identity.fernet_cipher import encrypt_secret
from trader.core.exchange.domain import Balance, ExchangeConfig, MarginMode
from trader.core.exchange.exceptions import ExchangeConnectivityError, UserExchangeCredentialError
from trader.core.exchange.use_cases import (
    BuildAccountView,
    PreflightUserExchange,
    RouteExchangeForTask,
    SymbolOpenOrders,
)
from trader.core.shared.domain import Interval, Symbol, SymbolInterval


class _FakeExchange:
    def __init__(self, balances=None):
        self.balances = balances or []
        self.borrow_reads = []
        self.all_open_order_reads = 0
        self.symbol_open_order_reads = []
        self.cancel_calls = []
        self.balance_error = None

    def get_account_balances(self):
        if self.balance_error is not None:
            raise self.balance_error
        return list(self.balances)

    def get_max_borrowable(self, asset, symbol=None):
        self.borrow_reads.append((asset, symbol))
        return {"amount": "2.5"}

    def get_all_open_orders(self):
        self.all_open_order_reads += 1
        return []

    def get_open_orders(self, symbol):
        self.symbol_open_order_reads.append(symbol.name())
        return [
            {
                "symbol": symbol.name(),
                "side": "buy",
                "amount": 0.5,
                "id": f"{symbol.name()}-order",
                "type": "limit",
                "price": "100",
                "status": "open",
            }
        ]

    def cancel_all_open_orders(self, symbol):
        self.cancel_calls.append(symbol.name())
        return {"symbol": symbol.name()}


def test_account_view_reads_balances_and_locked_source():
    exchange = _FakeExchange([Balance(asset="USDT", free=5.0, locked=70.0)])
    view = BuildAccountView(exchange, symbol_interval=SymbolInterval("BTC-USDT", Interval("1m"))).execute()

    assert view.balances[0].max_borrowable == 2.5
    assert view.borrow_asset == "USDT"
    assert view.operable_amount == 7.5
    assert view.locked_source[0].symbol == "BTCUSDT"
    assert view.open_orders == view.locked_source
    assert exchange.borrow_reads == [("USDT", None)]


def test_account_view_can_skip_open_order_reads():
    exchange = _FakeExchange([Balance(asset="USDT", free=5.0)])

    view = BuildAccountView(exchange, symbol_interval=SymbolInterval("BTC-USDT", Interval("1m"))).execute(include_open_orders=False)

    assert view.open_orders == []
    assert view.locked_source == []
    assert exchange.symbol_open_order_reads == []


def test_account_view_reports_balance_read_failure():
    exchange = _FakeExchange()
    exchange.balance_error = RuntimeError("Invalid API-key")

    view = BuildAccountView(exchange).execute()

    assert view.balances == []
    assert "交易所账户读取失败" in view.account_error
    assert "Invalid API-key" in view.account_error


def test_symbol_open_orders_requires_explicit_symbol():
    exchange = _FakeExchange()

    with pytest.raises(ValueError, match="explicit symbol"):
        SymbolOpenOrders(exchange).cancel(None)
    with pytest.raises(ValueError, match="explicit symbol"):
        SymbolOpenOrders(exchange).list(Symbol(""))

    assert exchange.cancel_calls == []
    assert exchange.symbol_open_order_reads == []


def test_symbol_cancel_touches_only_requested_symbol_and_never_account_wide():
    exchange = _FakeExchange()

    SymbolOpenOrders(exchange).cancel(Symbol("SOL-USDT"))

    assert exchange.cancel_calls == ["SOLUSDT"]
    assert exchange.all_open_order_reads == 0


def test_symbol_open_order_preview_reads_only_requested_symbol():
    exchange = _FakeExchange()

    orders = SymbolOpenOrders(exchange).list(Symbol("SOL-USDT"))

    assert [order.order_id for order in orders] == ["SOLUSDT-order"]
    assert exchange.symbol_open_order_reads == ["SOLUSDT"]
    assert exchange.all_open_order_reads == 0


def test_preflight_requires_service_key():
    with pytest.raises(UserExchangeCredentialError, match="TRADER_SECRET_KEY"):
        asyncio.run(PreflightUserExchange(_credential_repo(), cipher=None).execute(7))


def test_preflight_requires_user_credential():
    with pytest.raises(UserExchangeCredentialError, match="missing BINANCE API credential for user_id=7"):
        asyncio.run(PreflightUserExchange(_credential_repo(present=False), cipher=_cipher("service-secret")).execute(7))


def test_preflight_reports_connectivity_failure():
    with pytest.raises(ExchangeConnectivityError, match="connectivity failure for user_id=7"):
        asyncio.run(
            PreflightUserExchange(_credential_repo(), cipher=_cipher("service-secret")).execute(
                7,
                connectivity_check=lambda _credential: False,
            )
        )


def test_route_exchange_for_task_builds_user_client_with_margin_mode():
    service_key = "service-secret"
    created = []

    class _FakeClient:
        def __init__(self, cfg):
            self.cfg = cfg
            self.margin_mode = cfg.margin_mode
            created.append(cfg)

    def factory(cfg):
        return _FakeClient(cfg)

    route = RouteExchangeForTask(
        _credential_repo(),
        base_cfg=ExchangeConfig(api_key="system-key", api_secret="system-secret"),
        cipher=_cipher(service_key),
        exchange_factory=factory,
    )
    routed = asyncio.run(route.execute(7, margin_mode=MarginMode.CROSS_MARGIN))

    assert routed.cfg.api_key == "user-api-key"
    assert routed.cfg.api_secret == "user-api-secret"
    assert routed.cfg.margin_mode == MarginMode.CROSS_MARGIN
    assert created and created[0].api_key == "user-api-key"


def test_route_exchange_for_task_refreshes_credential_each_call():
    service_key = "service-secret"
    credentials = [_Credential(service_key, api_key="first-key"), _Credential(service_key, api_key="second-key")]

    class _Repo:
        async def get_default(self, user_id, exchange):
            return credentials.pop(0)

    route = RouteExchangeForTask(
        _Repo(),
        base_cfg=ExchangeConfig(),
        cipher=_cipher(service_key),
        exchange_factory=lambda cfg: SimpleNamespace(cfg=cfg),
    )

    first = asyncio.run(route.execute(7))
    second = asyncio.run(route.execute(7))

    assert first.cfg.api_key == "first-key"
    assert second.cfg.api_key == "second-key"


def _cipher(service_key):
    from trader.adapters.outbound.identity.fernet_cipher import FernetSecretCipher

    return FernetSecretCipher(service_key)


class _Credential:
    def __init__(self, service_key, api_key="user-api-key", api_secret="user-api-secret"):
        self.id = 12
        self.encrypted_api_key = encrypt_secret(service_key, api_key)
        self.encrypted_api_secret = encrypt_secret(service_key, api_secret)
        self.masked_api_key = "user***key"


def _credential_repo(*, present=True):
    value = _Credential("service-secret")

    async def get_default(user_id, exchange):
        return value if present else None

    return SimpleNamespace(get_default=get_default)
