from types import SimpleNamespace

from trader.execution import (
    ExecutionEventType,
    ExecutionReason,
    ExecutionSide,
    ExecutionStatus,
    GatewayCapability,
    OrderIntent,
    RiskIntent,
)
from trader.execution.gateways import BacktraderExecutionGateway, BinanceLiveExecutionGateway, _order_ids
from trader.utils.operate import OperateType


def _entry(side=ExecutionSide.LONG):
    return OrderIntent.entry(
        intent_id="intent-entry",
        operation_id="op-entry",
        symbol="BTCUSDT",
        side=side,
        quantity=0.25,
        notional=25000.0,
        trade_id="trade-1",
    )


def _close(side=ExecutionSide.LONG):
    return OrderIntent.close(
        intent_id="intent-close",
        operation_id="op-close",
        symbol="BTCUSDT",
        side=side,
        quantity=0.25,
        trade_id="trade-1",
    )


def _protection():
    return RiskIntent.place_protection(
        intent_id="risk-1",
        operation_id="op-entry",
        symbol="BTCUSDT",
        side=ExecutionSide.LONG,
        trade_id="trade-1",
        quantity=0.25,
        stop_price=95000.0,
        take_profit_price=110000.0,
    )


def _breakeven():
    return RiskIntent.replace_stop(
        intent_id="risk-2",
        operation_id="op-risk",
        symbol="BTCUSDT",
        side=ExecutionSide.LONG,
        trade_id="trade-1",
        quantity=0.25,
        stop_price=100000.0,
        replacement_of_order_id="stop-1",
    )


def _event_types(result):
    return [event.event_type for event in result.events]


class FakeBacktraderStrategy:
    def __init__(self):
        self.calls = []

    def buy(self, **kwargs):
        order = SimpleNamespace(ref=f"bt-{len(self.calls) + 1}", kwargs=kwargs)
        self.calls.append(("buy", kwargs))
        return order

    def sell(self, **kwargs):
        order = SimpleNamespace(ref=f"bt-{len(self.calls) + 1}", kwargs=kwargs)
        self.calls.append(("sell", kwargs))
        return order

    def cancel(self, order):
        self.calls.append(("cancel", order))


def test_backtrader_gateway_maps_market_and_protection_orders_to_strategy_methods():
    strategy = FakeBacktraderStrategy()
    gateway = BacktraderExecutionGateway(strategy)

    entry = gateway.open_position(_entry())
    protection = gateway.place_protection(_protection())
    close = gateway.close_position(_close())

    assert entry.status == ExecutionStatus.ACCEPTED
    assert protection.status == ExecutionStatus.ACCEPTED
    assert close.status == ExecutionStatus.ACCEPTED
    assert strategy.calls[0][0] == "buy"
    assert strategy.calls[1][0] == "sell"
    assert strategy.calls[2][0] == "sell"
    assert strategy.calls[3][0] == "sell"
    assert strategy.calls[1][1]["price"] == 95000.0
    assert strategy.calls[2][1]["price"] == 110000.0
    assert strategy.calls[2][1]["oco"] is not None


def test_order_ids_extract_margin_oco_wrapped_response():
    payload = SimpleNamespace(
        order_list_id=22024033207,
        orders=[
            SimpleNamespace(order_id=61534053446),
            SimpleNamespace(order_id=61534053447),
        ],
        order_reports=[
            SimpleNamespace(order_id=61534053446),
            SimpleNamespace(order_id=61534053447),
        ],
    )

    assert _order_ids(payload) == [
        "22024033207",
        "61534053446",
        "61534053447",
        "61534053446",
        "61534053447",
    ]


class FakeNativeBinanceExchange:
    def __init__(self, *, verify=True):
        self.verify = verify
        self.orders = []
        self.protections = []
        self.stop_orders = []
        self.take_profit_orders = []
        self.cancels = []
        self.replacements = []

    def new_order(self, symbol, op, quantity):
        self.orders.append((symbol.name(), op, quantity))
        return {"orderId": "live-entry-1"}

    def new_oco_order(self, symbol, side, quantity, stop_price, limit_price):
        self.protections.append((symbol.name(), side, quantity, stop_price, limit_price))
        return {"orderListId": "oco-1", "orders": [{"orderId": "stop-1"}, {"orderId": "tp-1"}]}

    def new_stop_order(self, symbol, side, quantity, stop_price):
        self.stop_orders.append((symbol.name(), side, quantity, stop_price))
        return {"orderId": "stop-1"}

    def new_take_profit_order(self, symbol, side, quantity, limit_price):
        self.take_profit_orders.append((symbol.name(), side, quantity, limit_price))
        return {"orderId": "tp-1"}

    def replace_stop_order(self, symbol, side, order_id, quantity, stop_price):
        self.replacements.append((symbol.name(), order_id, quantity, stop_price))
        return {"orderId": "stop-2"}

    def cancel_order(self, symbol, order_id):
        self.cancels.append((symbol.name(), order_id))
        return {"orderId": order_id, "status": "CANCELED"}

    def verify_order_ids(self, symbol, order_ids):
        ids = list(order_ids)
        return self.verify and (len(ids) == 1 or ("stop-1" in ids and "tp-1" in ids))

    def get_position_view(self, symbol):
        return []

    def get_open_protection_orders(self, symbol):
        return []


def test_binance_live_gateway_maps_market_native_oco_and_breakeven_replacement():
    exchange = FakeNativeBinanceExchange()
    gateway = BinanceLiveExecutionGateway(exchange, staged_execution_mode="small_live_auto")

    entry = gateway.open_position(_entry())
    protection = gateway.place_protection(_protection())
    replaced = gateway.replace_protection(_breakeven())
    close = gateway.close_position(_close())

    assert entry.status == ExecutionStatus.SUBMITTED
    assert exchange.orders[0] == ("BTCUSDT", OperateType.BUY, 0.25)
    assert protection.status == ExecutionStatus.ACCEPTED
    assert protection.gateway_order_id == "oco-1,stop-1,tp-1"
    assert ExecutionEventType.PROTECTION_ARMED in _event_types(protection)
    assert protection.events[-1].metadata["native"] is True
    assert replaced.status == ExecutionStatus.ACCEPTED
    assert replaced.gateway_order_id == "stop-2"
    assert ExecutionEventType.PROTECTION_REPLACED in _event_types(replaced)
    assert close.status == ExecutionStatus.SUBMITTED
    assert exchange.orders[-1] == ("BTCUSDT", OperateType.SELL, 0.25)


def test_binance_live_gateway_rejects_market_order_without_exchange_order_id():
    class MissingOrderIdExchange(FakeNativeBinanceExchange):
        def new_order(self, symbol, op, quantity):
            self.orders.append((symbol.name(), op, quantity))
            return None

    result = BinanceLiveExecutionGateway(MissingOrderIdExchange()).open_position(_entry())

    assert result.status == ExecutionStatus.FAILED
    assert result.reason == ExecutionReason.GATEWAY_REJECTED
    assert result.events[0].event_type == ExecutionEventType.ORDER_REJECTED


def test_binance_live_gateway_maps_single_protection_orders_to_closing_side():
    exchange = FakeNativeBinanceExchange()
    gateway = BinanceLiveExecutionGateway(exchange, staged_execution_mode="small_live_auto")

    long_stop = RiskIntent.place_protection(
        intent_id="risk-long-stop",
        operation_id="op-entry",
        symbol="BTCUSDT",
        side=ExecutionSide.LONG,
        trade_id="trade-1",
        quantity=0.25,
        stop_price=95000.0,
    )
    long_take_profit = RiskIntent.place_protection(
        intent_id="risk-long-tp",
        operation_id="op-entry",
        symbol="BTCUSDT",
        side=ExecutionSide.LONG,
        trade_id="trade-1",
        quantity=0.25,
        take_profit_price=110000.0,
    )
    short_stop = RiskIntent.place_protection(
        intent_id="risk-short-stop",
        operation_id="op-entry",
        symbol="BTCUSDT",
        side=ExecutionSide.SHORT,
        trade_id="trade-2",
        quantity=0.25,
        stop_price=105000.0,
    )

    assert gateway.place_protection(long_stop).status == ExecutionStatus.ACCEPTED
    assert gateway.place_protection(long_take_profit).status == ExecutionStatus.ACCEPTED
    assert gateway.place_protection(short_stop).status == ExecutionStatus.ACCEPTED
    assert exchange.stop_orders[0] == ("BTCUSDT", OperateType.SELL, 0.25, 95000.0)
    assert exchange.take_profit_orders[0] == ("BTCUSDT", OperateType.SELL, 0.25, 110000.0)
    assert exchange.stop_orders[1] == ("BTCUSDT", OperateType.CLOSE, 0.25, 105000.0)


def test_binance_live_gateway_rejects_unsupported_or_unverified_native_protection():
    unsupported = BinanceLiveExecutionGateway(object(), staged_execution_mode="small_live_auto").place_protection(_protection())
    assert unsupported.status == ExecutionStatus.REJECTED
    assert unsupported.capability == GatewayCapability.OCO_PROTECTION
    assert ExecutionEventType.PROTECTION_ARMED not in _event_types(unsupported)

    unverified = BinanceLiveExecutionGateway(
        FakeNativeBinanceExchange(verify=False),
        staged_execution_mode="small_live_auto",
    ).place_protection(_protection())
    assert unverified.status == ExecutionStatus.FAILED
    assert ExecutionEventType.PROTECTION_MISSING in _event_types(unverified)
    assert ExecutionEventType.PROTECTION_ARMED not in _event_types(unverified)
