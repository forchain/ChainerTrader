import pytest

from trader.execution import ExecutionSide, OrderIntentType, ProtectionIntentType
from trader.execution.order_semantics import (
    OrderSemanticsError,
    select_order_semantics,
    validate_protection_prices,
)
from trader.utils.operate import Operate, OperateType


def _op(otype, price=100.0):
    return Operate(otype, 1_714_281_600, price)


def test_market_entry_and_close_select_ordinary_order_intents():
    entry = select_order_semantics(_op(OperateType.BUY), symbol="BTCUSDT", side=ExecutionSide.LONG, quantity=0.25)
    close = select_order_semantics(_op(OperateType.SELL), symbol="BTCUSDT", side=ExecutionSide.LONG, quantity=0.25)

    assert entry.order is not None
    assert entry.order.intent_type == OrderIntentType.ENTRY
    assert entry.risk is None
    assert close.order is not None
    assert close.order.intent_type == OrderIntentType.CLOSE
    assert close.risk is None


def test_stop_take_profit_and_bracket_select_native_protection_intents():
    stop_only = _op(OperateType.BUY)
    stop_only.stop_loss = 95.0
    take_profit_only = _op(OperateType.BUY)
    take_profit_only.take_profit = 110.0
    bracket = _op(OperateType.BUY)
    bracket.stop_loss = 95.0
    bracket.take_profit = 110.0

    assert select_order_semantics(stop_only, symbol="BTCUSDT", side=ExecutionSide.LONG, quantity=0.25).risk.protection_type == ProtectionIntentType.STOP_LOSS
    assert select_order_semantics(take_profit_only, symbol="BTCUSDT", side=ExecutionSide.LONG, quantity=0.25).risk.protection_type == ProtectionIntentType.TAKE_PROFIT
    assert select_order_semantics(bracket, symbol="BTCUSDT", side=ExecutionSide.LONG, quantity=0.25).risk.protection_type == ProtectionIntentType.BRACKET


def test_breakeven_update_selects_replacement_protection_intent():
    op = _op(OperateType.RISK_UPDATE)
    op.breakeven_new_stop = 101.0
    op.protection_order_id = "stop-1"

    selection = select_order_semantics(op, symbol="BTCUSDT", side=ExecutionSide.LONG, quantity=0.25)

    assert selection.order is None
    assert selection.risk.protection_type == ProtectionIntentType.REPLACE_STOP
    assert selection.risk.replacement_of_order_id == "stop-1"


def test_live_stop_loss_cannot_degrade_to_ordinary_order():
    op = _op(OperateType.BUY)
    op.stop_loss = 95.0

    with pytest.raises(OrderSemanticsError, match="requires native protection"):
        select_order_semantics(
            op,
            symbol="BTCUSDT",
            side=ExecutionSide.LONG,
            quantity=0.25,
            allow_native_protection=False,
        )


def test_protection_price_validation_is_side_specific():
    validate_protection_prices(ExecutionSide.LONG, entry_price=100.0, stop_price=95.0, take_profit_price=110.0)
    validate_protection_prices(ExecutionSide.SHORT, entry_price=100.0, stop_price=105.0, take_profit_price=90.0)

    with pytest.raises(OrderSemanticsError, match="long stop_price must be below entry_price"):
        validate_protection_prices(ExecutionSide.LONG, entry_price=100.0, stop_price=105.0, take_profit_price=None)

    with pytest.raises(OrderSemanticsError, match="short take_profit_price must be below entry_price"):
        validate_protection_prices(ExecutionSide.SHORT, entry_price=100.0, stop_price=None, take_profit_price=110.0)
