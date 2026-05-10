from trader.exchange.ccxt_driver import CcxtExchangeDriver
from trader.exchange.driver import ExchangeDriverType
from trader.exchange.exchange_config import ExchangeConfig, MarginMode
from trader.exchange.exchange_type import ExchangeType
from trader.execution.models import ExecutionSide, ExecutionStatus, ProtectionIntentType
from trader.utils.operate import OperateType
from trader.utils.symbol_interval import Interval, Symbol, SymbolInterval


class FakeCcxtClient:
    def __init__(self):
        self.load_markets_calls = 0
        self.fetch_ohlcv_calls = []
        self.create_order_calls = []
        self.cancel_order_calls = []
        self.markets = {
            "BTC/USDT": {
                "symbol": "BTC/USDT",
                "precision": {"amount": 3, "price": 2},
                "limits": {"amount": {"min": 0.001}, "price": {"min": 0.01}},
            }
        }

    def load_markets(self):
        self.load_markets_calls += 1
        return self.markets

    def fetch_time(self):
        return 1_700_000_000_000

    def market(self, symbol):
        return self.markets[symbol]

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        self.fetch_ohlcv_calls.append((symbol, timeframe, since, limit))
        return [
            [1_700_000_000_000, 100.0, 110.0, 90.0, 105.0, 12.5],
            [1_700_003_600_000, 105.0, 115.0, 95.0, 112.0, 15.0],
        ]

    def fetch_balance(self, params=None):
        return {
            "free": {"BTC": 1.25, "USDT": 125.5},
            "total": {"BTC": 1.5, "USDT": 200.0},
            "info": {"userAssets": [{"asset": "BTC", "netAsset": "-0.75"}]},
        }

    def fetch_trading_fee(self, symbol):
        return {"symbol": symbol, "maker": 0.001, "taker": 0.002}

    def create_order(self, symbol, order_type, side, amount, price=None, params=None):
        payload = (symbol, order_type, side, amount, price, params or {})
        self.create_order_calls.append(payload)
        return {"id": "order-1", "symbol": symbol, "type": order_type, "side": side, "amount": amount, "price": price}

    def cancel_order(self, order_id, symbol=None, params=None):
        payload = (order_id, symbol, params or {})
        self.cancel_order_calls.append(payload)
        return {"id": order_id, "symbol": symbol, "status": "canceled"}

    def fetch_open_orders(self, symbol):
        return [
            {
                "id": "stop-1",
                "symbol": symbol,
                "type": "stop_loss",
                "amount": 0.5,
                "stopPrice": 95.0,
                "status": "open",
                "info": {},
            },
            {
                "id": "tp-1",
                "symbol": symbol,
                "type": "take_profit",
                "amount": 0.5,
                "price": 110.0,
                "status": "open",
                "info": {"orderListId": 77},
            },
            {
                "id": "stop-oco",
                "symbol": symbol,
                "type": "stop_loss",
                "amount": 0.5,
                "stopPrice": 94.5,
                "status": "open",
                "info": {"orderListId": 77},
            },
        ]


def _driver():
    return CcxtExchangeDriver(
        ExchangeConfig(ty=ExchangeType.BINANCE, driver=ExchangeDriverType.CCXT, margin_mode=MarginMode.SPOT),
        client=FakeCcxtClient(),
    )


def test_ccxt_driver_loads_klines_and_normalizes_candles():
    driver = _driver()
    driver.start()
    candles = driver.get_latest_klines(SymbolInterval("BTC-USDT", Interval.INTERVAL_1h), 2)

    assert len(candles) == 2
    assert candles[0].open_time == 1_700_000_000
    assert candles[0].close_time == 1_700_003_599
    assert candles[1].close == 112.0
    assert driver.client.fetch_ohlcv_calls == [("BTC/USDT", "1h", None, 2)]


def test_ccxt_driver_reads_balances_positions_and_fees():
    driver = _driver()

    assert driver.get_account_balance("USDT") == 125.5
    balances = driver.get_account_balances()
    assert {balance.asset for balance in balances} == {"BTC", "USDT"}

    long_positions = driver.get_position_view(Symbol("XRP-USDT"))
    assert long_positions == []

    margin_driver = CcxtExchangeDriver(
        ExchangeConfig(ty=ExchangeType.BINANCE, driver=ExchangeDriverType.CCXT, margin_mode=MarginMode.CROSS_MARGIN),
        client=FakeCcxtClient(),
    )
    positions = margin_driver.get_position_view(Symbol("BTC-USDT"))
    assert len(positions) == 1
    assert positions[0].side == ExecutionSide.SHORT
    assert positions[0].quantity == 0.75

    assert driver.get_account_commission("BTCUSDT") == 0.002


def test_ccxt_driver_maps_open_orders_and_validates_ids():
    driver = _driver()
    orders = driver.get_open_protection_orders(Symbol("BTC-USDT"))

    assert len(orders) == 2
    assert orders[0].protection_type == ProtectionIntentType.STOP_LOSS
    assert orders[0].status == ExecutionStatus.ACCEPTED
    assert orders[0].exchange_order_ids == ("stop-1",)
    assert orders[1].protection_type == ProtectionIntentType.BRACKET
    assert orders[1].exchange_order_ids == ("tp-1", "stop-oco")
    assert driver.verify_order_ids(Symbol("BTC-USDT"), ["1", "2"]) is True
    assert driver.verify_order_ids(Symbol("BTC-USDT"), []) is False


def test_ccxt_driver_places_market_orders_with_normalized_amount_and_symbol():
    driver = _driver()
    payload = driver.new_order(Symbol("BTC-USDT"), OperateType.BUY, 0.250019)

    assert payload["symbol"] == "BTC/USDT"
    assert payload["side"] == "buy"
    assert payload["amount"] == 0.25
    assert driver.client.create_order_calls == [("BTC/USDT", "market", "buy", 0.25, None, {})]


def test_ccxt_driver_places_stop_take_profit_and_bracket_orders():
    driver = _driver()

    stop = driver.new_stop_order(Symbol("BTC-USDT"), OperateType.SELL, 0.250019, 95.129)
    take_profit = driver.new_take_profit_order(Symbol("BTC-USDT"), OperateType.SELL, 0.250019, 110.129)
    bracket = driver.new_oco_order(Symbol("BTC-USDT"), OperateType.SELL, 0.250019, 94.129, 111.129)

    assert stop["id"] == "order-1"
    assert take_profit["id"] == "order-1"
    assert bracket["orderListId"] == "ccxt-bracket"
    assert driver.client.create_order_calls == [
        ("BTC/USDT", "market", "sell", 0.25, None, {"stopLossPrice": 95.12}),
        ("BTC/USDT", "market", "sell", 0.25, None, {"takeProfitPrice": 110.12}),
        ("BTC/USDT", "market", "sell", 0.25, None, {"stopLossPrice": 94.12}),
        ("BTC/USDT", "market", "sell", 0.25, None, {"takeProfitPrice": 111.12}),
    ]


def test_ccxt_driver_deletes_orders_from_raw_symbol_strings():
    driver = _driver()
    payload = driver.delete_order("BTCUSDT")

    assert payload["id"] == "BTCUSDT"
    assert driver.client.cancel_order_calls == [("BTCUSDT", "BTC/USDT", {})]


def test_ccxt_driver_cancels_all_open_orders_for_symbol():
    driver = _driver()

    payload = driver.cancel_all_open_orders(Symbol("BTC-USDT"))

    assert [item["id"] for item in payload] == ["stop-1", "tp-1", "stop-oco"]
    assert driver.client.cancel_order_calls == [
        ("stop-1", "BTC/USDT", {}),
        ("tp-1", "BTC/USDT", {}),
        ("stop-oco", "BTC/USDT", {}),
    ]
