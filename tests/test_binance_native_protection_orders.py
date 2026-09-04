from types import SimpleNamespace

import pytest

from trader.exchange.binance.exchange import BinanceExchange
from trader.exchange.binance.margin import MarginTradingManager
from trader.exchange.exchange_config import ExchangeConfig, MarginMode
from trader.utils.operate import OperateType
from trader.utils.symbol_interval import Symbol


class _Log:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass


class _Response:
    rate_limits = []

    def __init__(self, payload):
        self._payload = payload

    def data(self):
        return self._payload


class _SpotRestApi:
    def __init__(self):
        self.new_order_calls = []
        self.oco_calls = []
        self.replace_calls = []

    def new_order(self, **kwargs):
        self.new_order_calls.append(kwargs)
        return _Response({"orderId": f"spot-{len(self.new_order_calls)}"})

    def order_oco(self, **kwargs):
        self.oco_calls.append(kwargs)
        return _Response({"orders": [{"orderId": "stop-1"}, {"orderId": "tp-1"}]})

    def order_cancel_replace(self, **kwargs):
        self.replace_calls.append(kwargs)
        return _Response({"orderId": "stop-2"})

    def exchange_info(self, symbol=None):
        return _Response(
            {
                "symbols": [
                    {
                        "symbol": symbol,
                        "filters": [
                            {"filterType": "LOT_SIZE", "minQty": "0.00001000", "stepSize": "0.00001000"},
                            {"filterType": "MIN_NOTIONAL", "minNotional": "5.00000000"},
                        ],
                    }
                ]
            }
        )


class _MarginRestApi:
    def __init__(self):
        self.new_order_calls = []
        self.oco_calls = []

    def margin_account_new_order(self, **kwargs):
        self.new_order_calls.append(kwargs)
        return _Response({"orderId": f"margin-{len(self.new_order_calls)}"})

    def margin_account_new_oco(self, **kwargs):
        self.oco_calls.append(kwargs)
        return _Response({"orders": [{"orderId": "stop-1"}, {"orderId": "tp-1"}]})


def _exchange(mode=MarginMode.SPOT, rest_api=None):
    exchange = BinanceExchange.__new__(BinanceExchange)
    exchange.log = _Log()
    exchange.cfg = ExchangeConfig(margin_mode=mode)
    exchange.margin_mode = mode
    exchange.rate_limits = {}
    exchange.spot_client = SimpleNamespace(rest_api=rest_api or _SpotRestApi())
    exchange.has_rate_limit = lambda *_args, **_kwargs: False
    return exchange


def _margin_manager(rest_api=None):
    manager = MarginTradingManager.__new__(MarginTradingManager)
    manager.log = _Log()
    manager.client = SimpleNamespace(rest_api=rest_api or _MarginRestApi())
    manager.rate_limits = None
    return manager


def test_spot_single_leg_protection_uses_stop_market_and_take_profit_market():
    rest_api = _SpotRestApi()
    exchange = _exchange(rest_api=rest_api)

    assert exchange.new_stop_order(Symbol("BTC-USDT"), OperateType.SELL, 0.25, 95.0) == {"orderId": "spot-1"}
    assert exchange.new_take_profit_order(Symbol("BTC-USDT"), OperateType.SELL, 0.25, 110.0) == {"orderId": "spot-2"}

    assert rest_api.new_order_calls[0]["type"] == "STOP_LOSS"
    assert rest_api.new_order_calls[0]["stop_price"] == 95.0
    assert "price" not in rest_api.new_order_calls[0]
    assert "time_in_force" not in rest_api.new_order_calls[0]
    assert rest_api.new_order_calls[1]["type"] == "TAKE_PROFIT"
    assert rest_api.new_order_calls[1]["stop_price"] == 110.0
    assert "price" not in rest_api.new_order_calls[1]


def test_protection_side_mapping_closes_shorts_with_buy_side_orders():
    rest_api = _SpotRestApi()
    exchange = _exchange(rest_api=rest_api)

    exchange.new_stop_order(Symbol("BTC-USDT"), OperateType.CLOSE, 0.25, 105.0)
    exchange.new_take_profit_order(Symbol("BTC-USDT"), OperateType.CLOSE, 0.25, 90.0)
    exchange.replace_stop_order(Symbol("BTC-USDT"), OperateType.CLOSE, "123", 0.25, 100.0)

    assert rest_api.new_order_calls[0]["side"] == "BUY"
    assert rest_api.new_order_calls[1]["side"] == "BUY"
    assert rest_api.replace_calls[0]["side"] == "BUY"


def test_margin_single_leg_protection_uses_margin_order_api(monkeypatch):
    manager_rest_api = _MarginRestApi()
    manager = _margin_manager(manager_rest_api)
    monkeypatch.setattr("trader.exchange.binance.exchange.MarginTradingManager", lambda *_args, **_kwargs: manager)
    exchange = _exchange(mode=MarginMode.CROSS_MARGIN)

    exchange.new_stop_order(Symbol("BTC-USDT"), OperateType.CLOSE, 0.25, 105.0)
    exchange.new_take_profit_order(Symbol("BTC-USDT"), OperateType.CLOSE, 0.25, 90.0)

    assert manager_rest_api.new_order_calls[0]["type"] == "STOP_LOSS"
    assert manager_rest_api.new_order_calls[0]["side"] == "BUY"
    assert manager_rest_api.new_order_calls[1]["type"] == "TAKE_PROFIT"
    assert manager_rest_api.new_order_calls[1]["side"] == "BUY"


def test_margin_manager_oco_uses_market_stop_leg_when_stop_limit_is_not_required():
    rest_api = _MarginRestApi()
    manager = _margin_manager(rest_api)

    manager.new_oco_order(Symbol("BTC-USDT"), OperateType.CLOSE, 0.25, 105.0, 90.0)

    assert rest_api.oco_calls[0]["side"] == "BUY"
    assert rest_api.oco_calls[0]["stop_price"] == 105.0
    assert "stop_limit_price" not in rest_api.oco_calls[0]


def test_spot_exchange_normalizes_quantities_to_symbol_lot_size():
    rest_api = _SpotRestApi()
    exchange = _exchange(rest_api=rest_api)

    exchange.new_stop_order(Symbol("BTC-USDT"), OperateType.SELL, 0.25001999, 95.0)

    assert rest_api.new_order_calls[0]["quantity"] == 0.25001
