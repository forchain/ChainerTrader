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
        self.max_borrowable_calls = []
        self.margin_repay_calls = []
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
            "info": {
                "marginLevel": "1.7",
                "collateralMarginLevel": "1.6",
                "userAssets": [
                    {"asset": "BTC", "netAsset": "-0.75", "borrowed": "0.5", "interest": "0.01", "free": "0.25"},
                    {"asset": "ETH", "netAsset": "-2.0", "borrowed": "2.0", "interest": "0.02", "free": "1.0"},
                    {"asset": "BNB", "netAsset": "-1.0", "borrowed": "1.0", "interest": "0.01", "free": "1.0"},
                ],
            },
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

    def fetch_open_orders(self, symbol, since=None, limit=None, params=None):
        self.fetch_open_orders_call = (symbol, since, limit, params or {})
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

    def sapiPostMarginRepay(self, params):
        self.margin_repay_calls.append(params)
        self.last_margin_repay_params = params
        return {"tranId": 123456, **params}

    def sapiGetMarginMaxBorrowable(self, params):
        self.max_borrowable_calls.append(params)
        return {"asset": params["asset"], "amount": "123.45", "borrowLimit": "500.0"}


class FailingMaxBorrowableClient(FakeCcxtClient):
    def sapiGetMarginMaxBorrowable(self, params):
        self.max_borrowable_calls.append(params)
        raise RuntimeError("signature rejected")


class RestrictedMarketDataClient(FakeCcxtClient):
    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):
        self.fetch_ohlcv_calls.append((symbol, timeframe, since, limit))
        raise RuntimeError(
            'binance GET https://api.binance.com/api/v3/exchangeInfo 451 {"msg":"Service unavailable from a restricted location"}'
        )


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


def test_ccxt_driver_falls_back_to_binance_public_data_api_for_restricted_market_data(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [
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
                ]
            ]

    def fake_get(url, params, timeout):
        calls.append((url, params, timeout))
        return FakeResponse()

    monkeypatch.setattr("trader.exchange.ccxt_driver.requests.get", fake_get)
    driver = CcxtExchangeDriver(
        ExchangeConfig(ty=ExchangeType.BINANCE, driver=ExchangeDriverType.CCXT, margin_mode=MarginMode.SPOT),
        client=RestrictedMarketDataClient(),
    )

    candles = driver.get_klines(SymbolInterval("BTC-USDT", Interval.INTERVAL_1h), start_time=1_700_000_000, limit=1)

    assert len(candles) == 1
    assert candles[0].open_time == 1_700_000_000
    assert candles[0].close_time == 1_700_003_599
    assert candles[0].close == 105.0
    assert calls == [
        (
            "https://data-api.binance.vision/api/v3/klines",
            {
                "symbol": "BTCUSDT",
                "interval": "1h",
                "limit": 1,
                "startTime": 1_700_000_000_000,
            },
            20,
        )
    ]


def test_ccxt_driver_fallback_uses_bounded_start_time_for_end_time_window(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return [
                [
                    1_700_086_400_000,
                    "100.0",
                    "110.0",
                    "90.0",
                    "105.0",
                    "12.5",
                    1_700_172_799_999,
                    "1300.0",
                    42,
                    "6.0",
                    "650.0",
                    "0",
                ]
            ]

    def fake_get(url, params, timeout):
        calls.append((url, params, timeout))
        return FakeResponse()

    monkeypatch.setattr("trader.exchange.ccxt_driver.requests.get", fake_get)
    driver = CcxtExchangeDriver(
        ExchangeConfig(ty=ExchangeType.BINANCE, driver=ExchangeDriverType.CCXT, margin_mode=MarginMode.SPOT),
        client=RestrictedMarketDataClient(),
    )

    candles = driver.get_klines(SymbolInterval("BTC-USDT", Interval.INTERVAL_1d), end_time=1_700_086_400, limit=1)

    assert len(candles) == 1
    assert candles[0].open_time == 1_700_086_400
    assert calls == [
        (
            "https://data-api.binance.vision/api/v3/klines",
            {
                "symbol": "BTCUSDT",
                "interval": "1d",
                "limit": 1,
                "startTime": 1_700_086_400_000,
                "endTime": 1_700_086_400_000,
            },
            20,
        )
    ]


def test_ccxt_driver_get_klines_by_end_fetches_window_ending_at_requested_time():
    driver = _driver()

    candles = driver.get_klines_by_end(SymbolInterval("BTC-USDT", Interval.INTERVAL_1h), 1_700_003_600, limit=2)

    assert len(candles) == 2
    assert driver.client.fetch_ohlcv_calls == [("BTC/USDT", "1h", 1_700_000_000_000, 2)]


def test_ccxt_driver_start_does_not_require_market_network_preload():
    driver = _driver()

    assert driver.start() is True
    assert driver.client.load_markets_calls == 0


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


def test_ccxt_cross_margin_close_maps_to_buy_auto_repay_not_sell():
    client = FakeCcxtClient()
    driver = CcxtExchangeDriver(
        ExchangeConfig(ty=ExchangeType.BINANCE, driver=ExchangeDriverType.CCXT, margin_mode=MarginMode.CROSS_MARGIN),
        client=client,
    )

    payload = driver.new_order(Symbol("BTC-USDT"), OperateType.CLOSE, 0.250019)

    assert payload["side"] == "buy"
    assert client.create_order_calls == [
        ("BTC/USDT", "market", "buy", 0.25, None, {"marginMode": "cross", "sideEffectType": "AUTO_REPAY"})
    ]


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


def test_ccxt_cross_margin_open_order_queries_use_margin_mode_params():
    client = FakeCcxtClient()
    driver = CcxtExchangeDriver(
        ExchangeConfig(ty=ExchangeType.BINANCE, driver=ExchangeDriverType.CCXT, margin_mode=MarginMode.CROSS_MARGIN),
        client=client,
    )

    orders = driver.get_open_orders(Symbol("BTC-USDT"))

    assert len(orders) == 3
    assert client.fetch_open_orders_call == ("BTC/USDT", None, None, {"marginMode": "cross"})


def test_ccxt_cross_margin_all_open_order_queries_use_no_symbol_with_margin_mode_params():
    client = FakeCcxtClient()
    driver = CcxtExchangeDriver(
        ExchangeConfig(ty=ExchangeType.BINANCE, driver=ExchangeDriverType.CCXT, margin_mode=MarginMode.CROSS_MARGIN),
        client=client,
    )

    orders = driver.get_all_open_orders()

    assert len(orders) == 3
    assert client.fetch_open_orders_call == (None, None, None, {"marginMode": "cross"})


def test_ccxt_cross_margin_cancel_all_uses_margin_mode_params():
    client = FakeCcxtClient()
    driver = CcxtExchangeDriver(
        ExchangeConfig(ty=ExchangeType.BINANCE, driver=ExchangeDriverType.CCXT, margin_mode=MarginMode.CROSS_MARGIN),
        client=client,
    )

    driver.cancel_all_open_orders(Symbol("BTC-USDT"))

    assert client.fetch_open_orders_call == ("BTC/USDT", None, None, {"marginMode": "cross"})
    assert client.cancel_order_calls == [
        ("stop-1", "BTC/USDT", {"marginMode": "cross"}),
        ("tp-1", "BTC/USDT", {"marginMode": "cross"}),
        ("stop-oco", "BTC/USDT", {"marginMode": "cross"}),
    ]


def test_ccxt_driver_does_not_expose_no_symbol_account_order_cleanup():
    driver = _driver()

    assert not hasattr(driver, "cancel_all_account_open_orders")


def test_ccxt_default_type_is_spot_for_cross_margin_to_avoid_futures_endpoint_routing():
    driver = CcxtExchangeDriver(
        ExchangeConfig(ty=ExchangeType.BINANCE, driver=ExchangeDriverType.CCXT, margin_mode=MarginMode.CROSS_MARGIN),
        client=FakeCcxtClient(),
    )
    assert driver._default_type() == "spot"


def test_ccxt_build_client_disables_private_currency_fetch_during_market_loading(monkeypatch):
    created_payloads = []

    class FakeExchange:
        def __init__(self, payload):
            created_payloads.append(payload)

    class FakeCcxtModule:
        binance = FakeExchange

    monkeypatch.setattr("trader.exchange.ccxt_driver.ccxt", FakeCcxtModule)

    CcxtExchangeDriver(ExchangeConfig(ty=ExchangeType.BINANCE, api_key="key", api_secret="secret"))

    options = created_payloads[0]["options"]
    assert options["fetchCurrencies"] is False
    assert options["fetchMarkets"] == {"types": ["spot"]}


def test_ccxt_build_client_applies_rest_http_proxy(monkeypatch):
    created_clients = []
    created_payloads = []

    class FakeExchange:
        def __init__(self, payload):
            self.payload = payload
            created_payloads.append(payload)
            self.httpProxy = payload.get("httpProxy")
            self.http_proxy = payload.get("http_proxy")
            self.proxies = payload.get("proxies")
            created_clients.append(self)

    class FakeCcxtModule:
        binance = FakeExchange

    monkeypatch.setattr("trader.exchange.ccxt_driver.ccxt", FakeCcxtModule)

    CcxtExchangeDriver(ExchangeConfig(ty=ExchangeType.BINANCE, http_proxy="http://127.0.0.1:7890"))

    assert created_payloads[0]["proxies"] == {
        "http": "http://127.0.0.1:7890",
        "https": "http://127.0.0.1:7890",
    }
    assert created_clients[0].proxies == {
        "http": "http://127.0.0.1:7890",
        "https": "http://127.0.0.1:7890",
    }
    assert created_clients[0].httpProxy is None
    assert created_clients[0].http_proxy is None


def test_ccxt_repay_single_for_borrow_block_uses_margin_repay_endpoint():
    client = FakeCcxtClient()
    driver = CcxtExchangeDriver(
        ExchangeConfig(ty=ExchangeType.BINANCE, driver=ExchangeDriverType.CCXT, margin_mode=MarginMode.CROSS_MARGIN),
        client=client,
    )

    result = driver.auto_repay_for_borrow_block("BTC-USDT")

    assert result["symbol"] == "BTCUSDT"
    assert "results" in result
    assert isinstance(result["results"], list)


def test_ccxt_driver_queries_cross_margin_max_borrowable():
    client = FakeCcxtClient()
    driver = CcxtExchangeDriver(
        ExchangeConfig(ty=ExchangeType.BINANCE, driver=ExchangeDriverType.CCXT, margin_mode=MarginMode.CROSS_MARGIN),
        client=client,
    )

    result = driver.get_max_borrowable("USDT", symbol="BTCUSDT")

    assert result["asset"] == "USDT"
    assert result["amount"] == "123.45"
    assert result["borrowLimit"] == "500.0"
    assert client.max_borrowable_calls == [{"asset": "USDT", "isIsolated": "FALSE"}]


def test_ccxt_driver_returns_structured_max_borrowable_failure():
    client = FailingMaxBorrowableClient()
    driver = CcxtExchangeDriver(
        ExchangeConfig(ty=ExchangeType.BINANCE, driver=ExchangeDriverType.CCXT, margin_mode=MarginMode.CROSS_MARGIN),
        client=client,
    )

    result = driver.get_max_borrowable("USDT", symbol="BTCUSDT")

    assert result["ok"] is False
    assert result["asset"] == "USDT"
    assert "signature rejected" in result["reason"]


def test_ccxt_repay_all_liabilities_respects_caps_and_exclusions():
    client = FakeCcxtClient()
    driver = CcxtExchangeDriver(
        ExchangeConfig(ty=ExchangeType.BINANCE, driver=ExchangeDriverType.CCXT, margin_mode=MarginMode.CROSS_MARGIN),
        client=client,
    )

    result = driver.auto_repay_all_liabilities_for_borrow_block(
        "BTC-USDT",
        max_total=1.0,
        max_per_asset=0.75,
        min_amount=0.000001,
        excluded_assets=["BNB"],
    )

    assert result["ok"] is True
    assert result["policy"] == "repay_all"
    assert result["total_repaid"] == 1.0
    assert client.margin_repay_calls == [
        {"asset": "BTC", "amount": "0.25"},
        {"asset": "ETH", "amount": "0.75"},
    ]
    bnb = next(item for item in result["results"] if item["asset"] == "BNB")
    assert bnb["status"] == "skipped"
    assert bnb["reason"] == "excluded_asset"


# ---------------------------------------------------------------------------
# clientOrderId tagging tests
# ---------------------------------------------------------------------------


def test_ccxt_new_order_without_order_context_sends_no_client_order_id():
    driver = _driver()
    driver.new_order(Symbol("BTC-USDT"), OperateType.BUY, 0.25)

    _, _, _, _, _, params = driver.client.create_order_calls[-1]
    assert "clientOrderId" not in params


def test_ccxt_bind_order_context_injects_client_order_id_into_new_order():
    driver = _driver()
    driver.bind_order_context(task_id=42, strategy_name="ShihunRSI 2")

    driver.new_order(Symbol("BTC-USDT"), OperateType.BUY, 0.25)
    driver.new_order(Symbol("BTC-USDT"), OperateType.SELL, 0.25)

    calls = driver.client.create_order_calls
    # First order
    _, _, _, _, _, params1 = calls[0]
    assert params1["clientOrderId"] == "ct42sShihunRS_0001"
    # Second order – sequence increments
    _, _, _, _, _, params2 = calls[1]
    assert params2["clientOrderId"] == "ct42sShihunRS_0002"


def test_ccxt_bind_order_context_injects_client_order_id_into_trigger_orders():
    driver = _driver()
    driver.bind_order_context(task_id=7, strategy_name="Breakout")

    driver.new_stop_order(Symbol("BTC-USDT"), OperateType.SELL, 0.25, 95.0)
    driver.new_take_profit_order(Symbol("BTC-USDT"), OperateType.SELL, 0.25, 110.0)

    calls = driver.client.create_order_calls
    _, _, _, _, _, stop_params = calls[0]
    assert stop_params["clientOrderId"] == "ct7sBreakout_0001"
    assert "stopLossPrice" in stop_params

    _, _, _, _, _, tp_params = calls[1]
    assert tp_params["clientOrderId"] == "ct7sBreakout_0002"
    assert "takeProfitPrice" in tp_params


def test_ccxt_close_order_with_context_carries_auto_repay_and_client_order_id():
    client = FakeCcxtClient()
    driver = CcxtExchangeDriver(
        ExchangeConfig(ty=ExchangeType.BINANCE, driver=ExchangeDriverType.CCXT, margin_mode=MarginMode.CROSS_MARGIN),
        client=client,
    )
    driver.bind_order_context(task_id=3, strategy_name="Grid")

    driver.new_order(Symbol("BTC-USDT"), OperateType.CLOSE, 0.25)

    _, _, _, _, _, params = client.create_order_calls[-1]
    assert params["sideEffectType"] == "AUTO_REPAY"
    assert params["clientOrderId"] == "ct3sGrid_0001"
