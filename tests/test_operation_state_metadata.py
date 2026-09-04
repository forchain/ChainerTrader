from types import SimpleNamespace

from trader.utils.operate import Operate, OperateType, parse_opts
from trader.utils.operation_state import enrich_operation_from_trade_context


def test_enrich_operation_from_trade_context_copies_framework_risk_references():
    op = Operate(OperateType.LONG, 1714281600, 101.5)
    ctx = SimpleNamespace(
        trade_id=12,
        direction="LONG",
        initial_stop_price=97.0,
        stop_price=98.0,
        tp_price=110.0,
        risk_reward_ratio=2.0,
        signal_metadata={"signal_event_id": "sig-12", "suggested_stop_price": 97.0},
        breakeven_step=1,
        exit_reason_code=None,
        exit_reason_label=None,
        exit_reason_detail=None,
        stop_multiple_r=None,
        exit_risk_reward_ratio=None,
    )

    enrich_operation_from_trade_context(op, ctx)

    assert op.stop_loss == 98.0
    assert op.take_profit == 110.0
    assert op.risk_reward_ratio == 2.0
    assert op.signal_event_id == "sig-12"
    assert op.signal_metadata["suggested_stop_price"] == 97.0
    assert op.framework_trade == {
        "trade_id": 12,
        "direction": "LONG",
        "initial_stop_price": 97.0,
        "stop_price": 98.0,
        "take_profit": 110.0,
        "risk_reward_ratio": 2.0,
        "breakeven_step": 1,
        "exit_reason_code": None,
        "exit_reason_label": None,
        "exit_reason_detail": None,
        "stop_multiple_r": None,
        "exit_risk_reward_ratio": None,
    }


def test_operate_serialization_preserves_optional_monitoring_metadata():
    op = Operate(OperateType.LONG, 1714281600, 101.5)
    op.stop_loss = 98.0
    op.take_profit = 110.0
    op.risk_reward_ratio = 2.0
    op.signal_event_id = "sig-12"
    op.signal_number = 12
    op.signal_metadata = {"signal_event_id": "sig-12", "legs": [{"structure_price_low": 98.0}]}
    op.framework_trade = {"trade_id": 7, "stop_price": 98.0}

    parsed = parse_opts([op.to_dict()])[0]

    assert parsed.stop_loss == 98.0
    assert parsed.take_profit == 110.0
    assert parsed.risk_reward_ratio == 2.0
    assert parsed.signal_event_id == "sig-12"
    assert parsed.signal_number == 12
    assert parsed.signal_metadata == {"signal_event_id": "sig-12", "legs": [{"structure_price_low": 98.0}]}
    assert parsed.framework_trade == {"trade_id": 7, "stop_price": 98.0}
