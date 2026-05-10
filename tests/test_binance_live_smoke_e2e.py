import os
from decimal import Decimal
from types import SimpleNamespace

import pytest

from trader.exchange.binance.exchange import BinanceExchange
from trader.exchange.driver import ExchangeDriverType
from trader.exchange.exchange_config import ExchangeConfig
from trader.execution.models import GatewayCapability
from trader.tools.binance_live_smoke import (
    LiveSmokeReport,
    _cancel_all_open_orders,
    _env_driver_type,
    _latest_price,
    run_binance_live_smoke_from_env,
)
from trader.utils.symbol_interval import Symbol


@pytest.mark.skipif(
    os.getenv("CHAINERTRADER_ENABLE_BINANCE_LIVE_E2E") != "1",
    reason="requires CHAINERTRADER_ENABLE_BINANCE_LIVE_E2E=1 and real Binance credentials; places real orders",
)
def test_binance_live_smoke_covers_chainer_protection_and_macd_metadata():
    missing = [name for name in ("BINANCE_API_KEY", "BINANCE_API_SECRET", "CHAINERTRADER_SMALL_LIVE_MAX_NOTIONAL") if not os.getenv(name)]
    if missing:
        pytest.skip(f"Binance live smoke config missing: {', '.join(missing)}")

    report = run_binance_live_smoke_from_env()

    assert report.passed, report.to_dict()
    step_names = {step.name for step in report.steps if step.status == "passed"}
    if os.getenv("CHAINERTRADER_LIVE_SMOKE_ENABLE_SPOT") == "1":
        assert {"spot_long_entry", "spot_long_close"}.issubset(step_names)
    if os.getenv("CHAINERTRADER_LIVE_SMOKE_ENABLE_MARGIN") == "1":
        assert {"margin_short_entry", "margin_short_close"}.issubset(step_names)


def test_live_smoke_defaults_to_ccxt_driver(monkeypatch):
    monkeypatch.delenv("CHAINERTRADER_LIVE_SMOKE_DRIVER", raising=False)

    assert _env_driver_type() == ExchangeDriverType.CCXT


def test_live_smoke_can_explicitly_select_binance_native_driver(monkeypatch):
    monkeypatch.setenv("CHAINERTRADER_LIVE_SMOKE_DRIVER", "binance_native")

    assert _env_driver_type() == ExchangeDriverType.BINANCE_NATIVE


def test_ccxt_backed_binance_exchange_declares_protection_capabilities():
    exchange = BinanceExchange(ExchangeConfig(driver=ExchangeDriverType.CCXT))

    assert GatewayCapability.PROTECTIVE_STOP in exchange.supported_gateway_capabilities()
    assert GatewayCapability.TAKE_PROFIT_LIMIT in exchange.supported_gateway_capabilities()
    assert GatewayCapability.OCO_PROTECTION in exchange.supported_gateway_capabilities()
    assert GatewayCapability.BREAKEVEN_REPLACEMENT in exchange.supported_gateway_capabilities()


def test_live_smoke_cancel_all_open_orders_uses_exchange_adapter_without_spot_client():
    class FakeCcxtBackedExchange:
        spot_client = None
        margin_mode = None

        def __init__(self):
            self.calls = []

        def cancel_all_open_orders(self, symbol):
            self.calls.append(symbol.name())
            return [{"id": "stop-1", "status": "canceled"}]

    exchange = FakeCcxtBackedExchange()
    report = LiveSmokeReport(symbol="BTCUSDT", notional=11.0, spot_enabled=True, margin_enabled=False)

    _cancel_all_open_orders(exchange, Symbol("BTC-USDT"), report, step_prefix="spot")

    assert exchange.calls == ["BTCUSDT"]
    assert report.steps[-1].name == "spot_cancel_open_orders"
    assert report.steps[-1].status == "passed"


def test_latest_price_reads_binance_oneof_wrappers():
    class ActualInstance:
        def __init__(self, price):
            self.price = price

    class WrappedResponse:
        def __init__(self, price):
            self.actual_instance = ActualInstance(price)

    class FakeRestApi:
        def ticker_price(self, symbol):
            return SimpleNamespace(data=lambda: WrappedResponse("79866.20000000"))

    class FakeExchange:
        spot_client = SimpleNamespace(rest_api=FakeRestApi())

    assert _latest_price(FakeExchange(), Symbol("BTC-USDT")) == Decimal("79866.20000000")


def test_binance_exchange_normalize_quantity_reads_oneof_wrapped_exchange_info():
    class ActualInstance:
        def __init__(self, symbols):
            self.symbols = symbols

    class WrappedInfo:
        def __init__(self, symbols):
            self.actual_instance = ActualInstance(symbols)

    class Filter:
        def __init__(self, step_size, min_qty):
            self.filterType = "LOT_SIZE"
            self.stepSize = step_size
            self.minQty = min_qty

    class SymbolInfo:
        def __init__(self):
            self.filters = [Filter("0.000001", "0.000001")]

    class FakeExchange:
        def exchange_info(self, symbol):
            return WrappedInfo([SymbolInfo()])

    normalized = BinanceExchange._normalize_quantity(FakeExchange(), Symbol("BTC-USDT"), 0.00013783623426395764)

    assert normalized == 0.000137


def test_binance_exchange_normalize_price_reads_oneof_wrapped_exchange_info():
    class ActualInstance:
        def __init__(self, symbols):
            self.symbols = symbols

    class WrappedInfo:
        def __init__(self, symbols):
            self.actual_instance = ActualInstance(symbols)

    class Filter:
        def __init__(self, tick_size, min_price):
            self.filterType = "PRICE_FILTER"
            self.tickSize = tick_size
            self.minPrice = min_price

    class SymbolInfo:
        def __init__(self):
            self.filters = [Filter("0.01", "0.01")]

    class FakeExchange:
        def exchange_info(self, symbol):
            return WrappedInfo([SymbolInfo()])

    normalized = BinanceExchange._normalize_price(FakeExchange(), Symbol("BTC-USDT"), 83785.1805)

    assert normalized == 83785.18
