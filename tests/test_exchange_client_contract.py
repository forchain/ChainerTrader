from datetime import datetime
from types import SimpleNamespace

import pytest

from trader.adapters.outbound.binance.ccxt_driver import CcxtExchangeDriver
from trader.adapters.outbound.binance.exchange import BinanceExchange
from trader.adapters.outbound.binance.native_driver import BinanceNativeExchangeDriver
from trader.core.exchange.interfaces import ExchangeClient
from trader.core.shared.domain import Interval, OperateType, Symbol, SymbolInterval
from trader.exchange.driver import ExchangeDriverType
from trader.exchange.exchange_config import ExchangeConfig, MarginMode
from trader.execution.models import ExecutionSide, ExecutionStatus, ProtectionIntentType

SI = SymbolInterval("BTC-USDT", Interval.INTERVAL_1h)


class FakeCcxtClient:
    def __init__(self):
        self.markets = {
            "BTC/USDT": {
                "precision": {"amount": 3, "price": 2},
                "limits": {"amount": {"min": 0.001}, "price": {"min": 0.01}},
            }
        }

    def load_markets(self):
        return self.markets

    def fetch_time(self):
        return 1_700_000_000_000

    def market(self, symbol):
        return self.markets[symbol]

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        return [
            [1_700_000_000_000, 100.0, 110.0, 90.0, 105.0, 12.5, 1_700_003_599_999],
            [1_700_003_600_000, 105.0, 115.0, 95.0, 112.0, 15.0, 1_700_007_199_999],
        ]

    def fetch_balance(self, params=None):
        return {
            "free": {"BTC": 1.25, "USDT": 125.5},
            "total": {"BTC": 1.5, "USDT": 200.0},
            "info": {},
        }

    def fetch_trading_fee(self, symbol):
        return {"symbol": symbol, "maker": 0.001, "taker": 0.002}

    def create_order(self, symbol, order_type, side, amount, price=None, params=None):
        return {"id": "order-1", "symbol": symbol, "type": order_type, "side": side, "amount": amount}

    def cancel_order(self, order_id, symbol=None, params=None):
        return {"id": order_id, "symbol": symbol, "status": "canceled"}

    def fetch_open_orders(self, symbol, since=None, limit=None, params=None):
        return [
            {
                "id": "stop-1",
                "symbol": symbol,
                "type": "stop_loss",
                "amount": 0.5,
                "stopPrice": 95.0,
                "status": "open",
                "info": {},
            }
        ]


class _Response:
    rate_limits = []

    def __init__(self, payload):
        self._payload = payload

    def data(self):
        return self._payload


class FakeNativeRestApi:
    def __init__(self):
        self.order_calls = []

    def ping(self):
        return _Response(None)

    def time(self):
        return _Response(SimpleNamespace(server_time=1_700_000_000_000))

    def exchange_info(self, symbol=None):
        return _Response(
            {
                "symbols": [
                    {
                        "symbol": symbol,
                        "filters": [
                            {"filterType": "LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"},
                            {"filterType": "PRICE_FILTER", "minPrice": "0.01", "tickSize": "0.01"},
                        ],
                    }
                ]
            }
        )

    def klines(self, symbol, interval, start_time=None, end_time=None, limit=500):
        return _Response(
            [
                [
                    1_700_000_000_000,
                    "100.0",
                    "110.0",
                    "90.0",
                    "105.0",
                    "12.5",
                    1_700_003_599_999,
                    "1300.0",
                    42,
                    "6.0",
                    "650.0",
                    "0",
                ],
                [
                    1_700_003_600_000,
                    "105.0",
                    "115.0",
                    "95.0",
                    "112.0",
                    "15.0",
                    1_700_007_199_999,
                    "1600.0",
                    51,
                    "7.0",
                    "700.0",
                    "0",
                ],
            ]
        )

    def get_account(self, omit_zero_balances=True):
        return _Response(
            SimpleNamespace(
                balances=[
                    SimpleNamespace(asset="BTC", free="1.25", locked="0.25"),
                    SimpleNamespace(asset="USDT", free="125.5", locked="0.0"),
                ]
            )
        )

    def account_commission(self, symbol=None):
        return _Response(SimpleNamespace(standard_commission=SimpleNamespace(taker="0.002")))

    def new_order(self, **kwargs):
        self.order_calls.append(kwargs)
        return _Response({"orderId": f"native-{len(self.order_calls)}"})

    def order_oco(self, **kwargs):
        return _Response({"orderListId": "oco-1", "orders": [{"orderId": "stop-1"}, {"orderId": "tp-1"}]})

    def get_open_orders(self, symbol=None):
        return _Response(
            [
                SimpleNamespace(
                    order_list_id=-1,
                    type="STOP_LOSS",
                    order_id=9001,
                    orig_qty="0.5",
                    stop_price="95.0",
                    price="0.0",
                    side="SELL",
                    status="NEW",
                )
            ]
        )

    def delete_order(self, symbol, order_id=None):
        return _Response({"orderId": order_id, "status": "CANCELED"})

    def delete_open_orders(self, symbol):
        return _Response([{"orderId": 9001, "status": "CANCELED"}])


def _ccxt_driver():
    return CcxtExchangeDriver(
        ExchangeConfig(driver=ExchangeDriverType.CCXT, margin_mode=MarginMode.SPOT),
        client=FakeCcxtClient(),
    )


def _native_driver():
    return BinanceNativeExchangeDriver(
        ExchangeConfig(driver=ExchangeDriverType.BINANCE_NATIVE, margin_mode=MarginMode.SPOT),
        client=SimpleNamespace(rest_api=FakeNativeRestApi()),
    )


@pytest.fixture(params=["ccxt", "native"])
def driver(request):
    return _ccxt_driver() if request.param == "ccxt" else _native_driver()


def test_driver_implements_exchange_client_protocol(driver):
    assert isinstance(driver, ExchangeClient)
    assert driver.name() == "BINANCE"
    assert driver.driver_name() in {"ccxt", "binance_native"}


def test_exchange_facade_used_by_callers_implements_exchange_client_protocol():
    exchange = BinanceExchange(
        ExchangeConfig(driver=ExchangeDriverType.BINANCE_NATIVE),
        client=SimpleNamespace(rest_api=FakeNativeRestApi()),
    )

    assert isinstance(exchange, ExchangeClient)
    assert exchange.driver_name() == "binance_native"


def test_driver_connectivity_and_server_time(driver):
    assert driver.start() is True
    assert driver.ping() is True
    assert isinstance(driver.time(), datetime)
    assert isinstance(driver.server_datetime(), datetime)
    assert isinstance(driver.server_time_offset(), float)
    driver.stop()


def test_driver_reads_klines(driver):
    candles = driver.get_klines(SI, limit=2)

    assert [candle.open_time for candle in candles] == [1_700_000_000, 1_700_003_600]
    assert candles[0].close == 105.0
    assert candles[0].close_time == 1_700_003_599
    assert len(driver.get_latest_klines(SI, limit=2)) == 2
    assert len(driver.get_klines_by_end(SI, 1_700_003_600, limit=2)) == 2


def test_driver_reads_balances_positions_and_commission(driver):
    assert driver.get_account_balance("USDT") == 125.5
    assert {balance.asset for balance in driver.get_account_balances()} == {"BTC", "USDT"}

    positions = driver.get_position_view(Symbol("BTC-USDT"))
    assert positions[0].side == ExecutionSide.LONG
    assert positions[0].quantity == 1.25

    assert driver.get_account_commission("BTCUSDT") == 0.002
    assert driver.exchange_info("BTCUSDT") is not None


def test_driver_places_orders_lists_protection_and_cancels(driver):
    assert driver.new_order(Symbol("BTC-USDT"), OperateType.BUY, 0.25) is not None
    assert driver.new_stop_order(Symbol("BTC-USDT"), OperateType.SELL, 0.5, 95.0) is not None
    assert driver.new_take_profit_order(Symbol("BTC-USDT"), OperateType.SELL, 0.5, 110.0) is not None

    assert len(driver.get_open_orders(Symbol("BTC-USDT"))) == 1
    protections = driver.get_open_protection_orders(Symbol("BTC-USDT"))
    assert len(protections) == 1
    assert protections[0].protection_type == ProtectionIntentType.STOP_LOSS
    assert protections[0].status == ExecutionStatus.ACCEPTED
    assert protections[0].quantity == 0.5

    assert driver.cancel_order(Symbol("BTC-USDT"), "9001") is not None
    assert driver.cancel_all_open_orders(Symbol("BTC-USDT")) is not None
    assert driver.verify_order_ids(Symbol("BTC-USDT"), ["9001"]) is True
    assert driver.verify_order_ids(Symbol("BTC-USDT"), []) is False


def test_driver_reports_spot_margin_surface(driver):
    payload = driver.get_max_borrowable("USDT")

    assert payload["ok"] is False
    assert driver.is_cross_margin_ready() is False
    driver.bind_order_context(task_id=7, strategy_name="Contract")
