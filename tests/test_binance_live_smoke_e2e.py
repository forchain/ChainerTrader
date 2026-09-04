from decimal import Decimal
from types import SimpleNamespace

import os

import pytest

from trader.exchange.binance.exchange import BinanceExchange
from trader.tools.binance_live_smoke import _latest_price, run_binance_live_smoke_from_env
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
    assert {"spot_long_entry_bracket", "spot_long_breakeven_replace", "spot_long_close"}.issubset(step_names)
    if os.getenv("CHAINERTRADER_LIVE_SMOKE_ENABLE_MARGIN") == "1":
        assert {"margin_short_entry_bracket", "margin_short_breakeven_replace", "margin_short_close"}.issubset(step_names)


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
