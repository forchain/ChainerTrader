import pytest

from trader.execution import (
    ExecutionEvent,
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
        staged_execution_mode="small_live_auto",
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


def test_gateway_resolver_preserves_staged_live_safety_modes():
    manual = resolve_execution_gateway(live_execution_mode="manual_notify")
    small_live = resolve_execution_gateway(live_execution_mode="small_live_auto", live_trade_max_notional=25.0)
    full_live = resolve_execution_gateway(live_execution_mode="full_live_auto")

    assert manual.gateway_mode == GatewayMode.NOTIFICATION_ONLY
    assert manual.can_submit_orders is False
    assert small_live.gateway_mode == GatewayMode.BINANCE_LIVE
    assert small_live.max_notional == 25.0
    assert small_live.requires_live_order_cap is True
    assert full_live.gateway_mode == GatewayMode.BINANCE_LIVE
    assert full_live.requires_live_order_cap is False

    with pytest.raises(GatewayResolutionError, match="conflicts with live_execution_mode=manual_notify"):
        resolve_execution_gateway(live_execution_mode="manual_notify", requested_gateway=GatewayMode.BINANCE_LIVE)

    with pytest.raises(GatewayResolutionError, match="paper_auto is no longer supported"):
        resolve_execution_gateway(live_execution_mode="paper_auto")

    with pytest.raises(GatewayResolutionError, match="requires positive live_trade_max_notional"):
        resolve_execution_gateway(live_execution_mode="small_live_auto", live_trade_max_notional=0.0)


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
        staged_execution_mode="small_live_auto",
        symbol="BTCUSDT",
        trade_id="trade-1",
    )

    assert request.idempotency_key == "binance_live:small_live_auto:BTCUSDT:trade-1"
