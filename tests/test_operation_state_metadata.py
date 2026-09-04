from types import SimpleNamespace

from trader.utils.operate import Operate, OperateType, parse_opts
from trader.utils.operation_state import MaxDrawdownAnalyzer, enrich_operation_from_trade_context


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
        replacement_trade_id=13,
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
        "replacement_trade_id": 13,
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


class _SequenceBroker:
    def __init__(self, values: list[float]):
        self.values = values
        self.index = 0

    def get_cash(self):
        return self.values[0]

    def getvalue(self):
        return self.values[self.index]


class _SequenceClock:
    def __init__(self, values: list[object]):
        self.values = values
        self.index = 0

    def datetime(self):
        return self.values[self.index]


def test_max_drawdown_analyzer_tracks_active_position_drawdown_separately():
    times = [
        SimpleNamespace(day=1),
        SimpleNamespace(day=2),
        SimpleNamespace(day=3),
        SimpleNamespace(day=4),
        SimpleNamespace(day=5),
    ]
    broker = _SequenceBroker([100.0, 70.0, 90.0, 81.0, 50.0])
    clock = _SequenceClock(times)
    analyzer = MaxDrawdownAnalyzer.__new__(MaxDrawdownAnalyzer)
    MaxDrawdownAnalyzer.__init__(analyzer)
    analyzer.strategy = SimpleNamespace(
        broker=broker,
        datetime=clock,
        position=SimpleNamespace(size=0.0),
    )

    analyzer.start()
    position_sizes = [0.0, 0.0, 1.0, 1.0, 0.0]
    for index, position_size in enumerate(position_sizes):
        broker.index = index
        clock.index = index
        analyzer.strategy.position.size = position_size
        analyzer.next()

    analysis = analyzer.get_analysis()

    assert analysis["max_drawdown"] == 50.0
    assert analysis["active_max_drawdown"] == 10.0
    assert analysis["active_start"] is times[2]
    assert analysis["active_end"] is times[3]
