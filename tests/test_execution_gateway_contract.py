import pytest

from trader.adapters.outbound.binance.execution_gateway import BinanceLiveExecutionGateway
from trader.adapters.outbound.notification.execution_gateway import NotificationOnlyExecutionGateway
from trader.core.execution import (
    ExecutionEvent,
    ExecutionEventType,
    ExecutionGateway,
    ExecutionReason,
    ExecutionResult,
    ExecutionSide,
    ExecutionStatus,
    GatewayCapabilities,
    GatewayCapability,
    GatewayMode,
    GatewayResolutionError,
    OrderIntent,
    OrderIntentType,
    ProtectionIntentType,
    ReconcileRequest,
    ReconcileResult,
    RiskIntent,
    resolve_execution_gateway,
)


def test_order_and_risk_intents_validate_and_preserve_signal_context():
    entry = OrderIntent.entry(
        intent_id="intent-1",
        operation_id="op-1",
        symbol="BTCUSDT",
        side=ExecutionSide.LONG,
        quantity=0.25,
        notional=25000.0,
        trade_id="trade-1",
        signal_event_id="signal-1",
        metadata={"strategy": "macd_triple_divergence"},
    )

    protection = RiskIntent.place_protection(
        intent_id="risk-1",
        operation_id="op-1",
        symbol="BTCUSDT",
        side=ExecutionSide.LONG,
        trade_id="trade-1",
        quantity=0.25,
        stop_price=95000.0,
        take_profit_price=110000.0,
        signal_event_id="signal-1",
        metadata={"risk_reward_ratio": 2.0},
    )

    assert entry.intent_type == OrderIntentType.ENTRY
    assert entry.idempotency_key == "intent-1:op-1:entry"
    assert entry.metadata["strategy"] == "macd_triple_divergence"
    assert protection.protection_type == ProtectionIntentType.BRACKET
    assert protection.idempotency_key == "risk-1:op-1:place_protection"
    assert protection.signal_event_id == "signal-1"

    with pytest.raises(ValueError, match="quantity must be positive"):
        OrderIntent.entry(
            intent_id="bad",
            operation_id="op-2",
            symbol="BTCUSDT",
            side=ExecutionSide.LONG,
            quantity=0.0,
            notional=100.0,
        )


def test_execution_events_and_results_use_normalized_taxonomy():
    event = ExecutionEvent.order_accepted(
        gateway=GatewayMode.BINANCE_LIVE,
        staged_execution_mode="auto_trade",
        intent_id="intent-1",
        operation_id="op-1",
        symbol="BTCUSDT",
        order_id="live-order-1",
        metadata={"signal_event_id": "signal-1"},
    )
    result = ExecutionResult.from_accepted(
        intent_id="intent-1",
        operation_id="op-1",
        status=ExecutionStatus.ACCEPTED,
        events=[event],
        gateway_order_id="live-order-1",
    )

    assert event.to_dict()["event_type"] == "order_accepted"
    assert event.to_dict()["gateway"] == "binance_live"
    assert event.to_dict()["metadata"] == {"signal_event_id": "signal-1"}
    assert result.accepted is True
    assert result.to_dict()["status"] == "accepted"
    assert result.to_dict()["events"][0]["order_id"] == "live-order-1"


def test_gateway_capabilities_return_explicit_unsupported_results():
    capabilities = GatewayCapabilities(
        gateway=GatewayMode.BINANCE_LIVE,
        supported={
            GatewayCapability.MARKET_ENTRY,
            GatewayCapability.MARKET_CLOSE,
            GatewayCapability.PROTECTIVE_STOP,
        },
    )

    assert capabilities.supports(GatewayCapability.MARKET_ENTRY) is True
    assert capabilities.supports(GatewayCapability.OCO_PROTECTION) is False

    result = ExecutionResult.unsupported(
        intent_id="risk-1",
        operation_id="op-1",
        capability=GatewayCapability.OCO_PROTECTION,
        gateway=GatewayMode.BINANCE_LIVE,
    )

    assert result.accepted is False
    assert result.status == ExecutionStatus.REJECTED
    assert result.reason == ExecutionReason.UNSUPPORTED_CAPABILITY
    assert result.to_dict()["capability"] == "oco_protection"


def test_gateway_resolver_supports_manual_notify_and_auto_trade_only():
    manual = resolve_execution_gateway(live_execution_mode="manual_notify")
    auto = resolve_execution_gateway(live_execution_mode="auto_trade", live_trade_max_notional=25.0)

    assert manual.gateway_mode == GatewayMode.NOTIFICATION_ONLY
    assert manual.can_submit_orders is False
    assert auto.gateway_mode == GatewayMode.BINANCE_LIVE
    assert auto.max_notional == 25.0
    assert auto.requires_live_order_cap is True

    with pytest.raises(GatewayResolutionError, match="conflicts with live_execution_mode=manual_notify"):
        resolve_execution_gateway(live_execution_mode="manual_notify", requested_gateway=GatewayMode.BINANCE_LIVE)

    for mode in ["small_live_auto", "full_live_auto", "paper_auto", "manual", "notify"]:
        with pytest.raises(GatewayResolutionError, match=f"unsupported live_execution_mode={mode}"):
            resolve_execution_gateway(live_execution_mode=mode)


def test_execution_gateway_interface_declares_required_operations():
    assert ExecutionGateway.__abstractmethods__ == {
        "open_position",
        "place_protection",
        "replace_protection",
        "close_position",
        "cancel_order",
        "reconcile",
    }

    request = ReconcileRequest(
        gateway=GatewayMode.BINANCE_LIVE,
        staged_execution_mode="auto_trade",
        symbol="BTCUSDT",
        trade_id="trade-1",
    )

    assert request.idempotency_key == "binance_live:auto_trade:BTCUSDT:trade-1"


class ContractExchange:
    """Exchange fake that records every order-side call for the shared gateway contract."""

    def __init__(self):
        self.calls = []

    def new_order(self, symbol, op, quantity):
        self.calls.append(("new_order", symbol.name(), op, quantity))
        return {"orderId": "live-entry-1"}

    def new_oco_order(self, symbol, side, quantity, stop_price, take_profit_price):
        self.calls.append(("new_oco_order", symbol.name(), side, quantity, stop_price, take_profit_price))
        return {"orders": [{"orderId": "stop-1"}, {"orderId": "tp-1"}]}

    def new_stop_order(self, symbol, side, quantity, stop_price):
        self.calls.append(("new_stop_order", symbol.name(), side, quantity, stop_price))
        return {"orderId": "stop-1"}

    def new_take_profit_order(self, symbol, side, quantity, take_profit_price):
        self.calls.append(("new_take_profit_order", symbol.name(), side, quantity, take_profit_price))
        return {"orderId": "tp-1"}

    def replace_stop_order(self, symbol, side, order_id, quantity, stop_price):
        self.calls.append(("replace_stop_order", symbol.name(), order_id, quantity, stop_price))
        return {"orderId": "stop-2"}

    def cancel_order(self, symbol, order_id):
        self.calls.append(("cancel_order", symbol.name(), order_id))
        return {"orderId": order_id, "status": "CANCELED"}

    def verify_order_ids(self, symbol, order_ids):
        return bool(order_ids)

    def get_position_view(self, symbol):
        return []

    def get_open_protection_orders(self, symbol):
        return []


def _notification_only_gateway(exchange):
    return NotificationOnlyExecutionGateway(staged_execution_mode="manual_notify")


def _binance_live_gateway(exchange):
    return BinanceLiveExecutionGateway(exchange, staged_execution_mode="auto_trade")


# The backtrader implementation joins this suite in ticket #100.
GATEWAY_IMPLEMENTATIONS = [
    pytest.param(_notification_only_gateway, GatewayMode.NOTIFICATION_ONLY, False, id="notification_only"),
    pytest.param(_binance_live_gateway, GatewayMode.BINANCE_LIVE, True, id="binance_live"),
]


def _contract_entry():
    return OrderIntent.entry(
        intent_id="contract-entry",
        operation_id="contract-op-entry",
        symbol="BTCUSDT",
        side=ExecutionSide.LONG,
        quantity=0.25,
        notional=25000.0,
        trade_id="trade-1",
    )


def _contract_close():
    return OrderIntent.close(
        intent_id="contract-close",
        operation_id="contract-op-close",
        symbol="BTCUSDT",
        side=ExecutionSide.LONG,
        quantity=0.25,
        trade_id="trade-1",
    )


def _contract_cancel():
    return OrderIntent(
        intent_id="contract-cancel",
        operation_id="contract-op-cancel",
        symbol="BTCUSDT",
        side=ExecutionSide.LONG,
        intent_type=OrderIntentType.CANCEL,
        metadata={"order_id": "order-1"},
    )


def _contract_protection():
    return RiskIntent.place_protection(
        intent_id="contract-risk-place",
        operation_id="contract-op-entry",
        symbol="BTCUSDT",
        side=ExecutionSide.LONG,
        trade_id="trade-1",
        quantity=0.25,
        stop_price=95000.0,
        take_profit_price=110000.0,
    )


def _contract_replacement():
    return RiskIntent.replace_stop(
        intent_id="contract-risk-replace",
        operation_id="contract-op-risk",
        symbol="BTCUSDT",
        side=ExecutionSide.LONG,
        trade_id="trade-1",
        quantity=0.25,
        stop_price=100000.0,
        replacement_of_order_id="stop-1",
    )


@pytest.mark.parametrize("factory, expected_mode, submits_orders", GATEWAY_IMPLEMENTATIONS)
def test_shared_gateway_contract_implements_the_port_for_every_implementation(factory, expected_mode, submits_orders):
    gateway = factory(ContractExchange())

    assert isinstance(gateway, ExecutionGateway)
    assert gateway.capabilities.gateway == expected_mode


@pytest.mark.parametrize("factory, expected_mode, submits_orders", GATEWAY_IMPLEMENTATIONS)
def test_shared_gateway_contract_echoes_intent_identity_for_entry_and_close(factory, expected_mode, submits_orders):
    exchange = ContractExchange()
    gateway = factory(exchange)
    entry = _contract_entry()
    close = _contract_close()

    entry_result = gateway.open_position(entry)
    close_result = gateway.close_position(close)

    for intent, result in ((entry, entry_result), (close, close_result)):
        assert result.intent_id == intent.intent_id
        assert result.operation_id == intent.operation_id
        assert isinstance(result.status, ExecutionStatus)
        assert all(event.gateway == expected_mode for event in result.events)
        assert all(event.intent_id == intent.intent_id for event in result.events)
    if submits_orders:
        assert entry_result.accepted is True
        assert close_result.accepted is True
        assert entry_result.gateway_order_id
        assert close_result.gateway_order_id
    else:
        assert entry_result.accepted is False
        assert close_result.accepted is False
        assert entry_result.gateway_order_id is None
        assert close_result.gateway_order_id is None
        assert exchange.calls == []


@pytest.mark.parametrize("factory, expected_mode, submits_orders", GATEWAY_IMPLEMENTATIONS)
def test_shared_gateway_contract_makes_protection_outcomes_explicit(factory, expected_mode, submits_orders):
    gateway = factory(ContractExchange())

    placement = gateway.place_protection(_contract_protection())
    replacement = gateway.replace_protection(_contract_replacement())

    for result, armed_event in (
        (placement, ExecutionEventType.PROTECTION_ARMED),
        (replacement, ExecutionEventType.PROTECTION_REPLACED),
    ):
        assert isinstance(result, ExecutionResult)
        assert isinstance(result.status, ExecutionStatus)
        if result.accepted:
            assert armed_event in [event.event_type for event in result.events]
        else:
            assert result.status == ExecutionStatus.REJECTED
            assert result.reason == ExecutionReason.UNSUPPORTED_CAPABILITY
            assert result.capability is not None
            assert result.gateway_order_id is None


@pytest.mark.parametrize("factory, expected_mode, submits_orders", GATEWAY_IMPLEMENTATIONS)
def test_shared_gateway_contract_supports_cancel_and_reconcile(factory, expected_mode, submits_orders):
    gateway = factory(ContractExchange())
    request = ReconcileRequest(
        gateway=expected_mode,
        staged_execution_mode="manual_notify" if not submits_orders else "auto_trade",
        symbol="BTCUSDT",
        trade_id="trade-1",
    )

    cancel_result = gateway.cancel_order(_contract_cancel())
    reconcile_result = gateway.reconcile(request)

    assert cancel_result.intent_id == "contract-cancel"
    assert isinstance(cancel_result.status, ExecutionStatus)
    assert isinstance(reconcile_result, ReconcileResult)
    assert reconcile_result.request is request


def test_notification_only_gateway_never_places_orders():
    exchange = ContractExchange()
    gateway = NotificationOnlyExecutionGateway(staged_execution_mode="manual_notify")

    results = [
        gateway.open_position(_contract_entry()),
        gateway.place_protection(_contract_protection()),
        gateway.replace_protection(_contract_replacement()),
        gateway.close_position(_contract_close()),
        gateway.cancel_order(_contract_cancel()),
    ]

    assert all(result.accepted is False for result in results)
    assert all(result.gateway_order_id is None for result in results)
    assert all(result.reason == ExecutionReason.UNSUPPORTED_CAPABILITY for result in results)
    assert exchange.calls == []
