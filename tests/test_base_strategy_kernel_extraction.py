import inspect

from trader.strategy import base_strategy
from trader.strategy.backtrader_adapter import BacktraderStrategyExecutionAdapter
from trader.strategy.base_strategy import BaseStrategy
from trader.strategy.lifecycle import KlineRef, SignalSnapshot, TradeContext, TradeLifecycleEngine, TradeStatus
from trader.strategy.risk import StrategyRiskEngine
from trader.strategy.signal_router import SignalRouteActionType, SignalRouter, SignalRoutingState


def test_base_strategy_has_no_strategy_specific_fallbacks():
    source = inspect.getsource(base_strategy.BaseStrategy)

    assert "macd_stop_enabled" not in source
    assert "MACD 三背离" not in source
    assert "策略止损逻辑退出" not in source


def test_base_strategy_does_not_own_protective_order_helpers():
    source = inspect.getsource(base_strategy.BaseStrategy)

    assert "_place_or_replace_stop_order" not in source
    assert "_place_or_replace_tp_order" not in source
    assert "_cancel_stop_order" not in source
    assert "_cancel_tp_order" not in source
    assert "bt.Order.Stop" not in source
    assert "bt.Order.Limit" not in source


def test_base_strategy_legacy_types_alias_lifecycle_domain_types():
    assert BaseStrategy.TradeStatus is TradeStatus
    assert BaseStrategy.TradeContext is TradeContext
    assert BaseStrategy.KlineRef is KlineRef
    assert BaseStrategy.SignalSnapshot is SignalSnapshot


def test_lifecycle_engine_transitions_without_backtrader_strategy():
    engine = TradeLifecycleEngine()
    ctx = engine.create_trade(
        trade_id=1,
        key="trade-1",
        direction="LONG",
        entry_key_bar_index=3,
        key_kline_ref=KlineRef(dt=base_strategy.datetime.fromtimestamp(0), high=105.0, low=95.0),
        stoploss_atr_mult=0.0,
        entry_need_confirm=True,
        exit_need_confirm=True,
        enable_breakeven=True,
        risk_reward_ratio=1.0,
        signal_metadata={"suggested_stop_price": 94.0},
    )

    assert ctx.status == TradeStatus.PENDING_ENTRY_CONFIRM
    engine.mark_entry_opening(ctx, order="entry-order")
    assert ctx.status == TradeStatus.OPENING
    engine.mark_entry_filled(ctx, price=100.0, fallback_stop_price=95.0)
    assert ctx.status == TradeStatus.ACTIVE
    assert ctx.entry_price == 100.0
    engine.request_exit(
        ctx,
        exit_key_bar_index=4,
        exit_key_ref=KlineRef(dt=base_strategy.datetime.fromtimestamp(60), high=106.0, low=96.0),
        exit_need_confirm=True,
        reason_code="signal_exit",
        reason_label="信号出场",
        reason_detail="test",
    )
    assert ctx.status == TradeStatus.PENDING_EXIT_CONFIRM
    engine.mark_exit_closing(ctx, order="exit-order")
    assert ctx.status == TradeStatus.CLOSING
    engine.mark_exit_filled(ctx, price=101.0, value=1010.0)
    assert ctx.status == TradeStatus.CLOSED
    assert ctx.exit_reason_code == "signal_exit"


def test_signal_router_returns_actions_without_backtrader_strategy():
    router = SignalRouter()
    snapshot = SignalSnapshot(bar_index=10, long_signal=True, short_signal=False, long_context={"signal_bar_index": 10})

    actions = router.route(
        snapshot,
        SignalRoutingState(
            mode="LONG_ONLY",
            can_open_new_position=True,
            active_trade=None,
            position_size=0.0,
        ),
    )

    assert [action.action_type for action in actions] == [
        SignalRouteActionType.DETECTED,
        SignalRouteActionType.ENTER,
    ]
    assert actions[-1].direction == "LONG"
    assert actions[-1].context == {"signal_bar_index": 10}


def test_signal_router_exits_short_only_active_short():
    router = SignalRouter()
    lifecycle = TradeLifecycleEngine()
    ctx = lifecycle.create_trade(
        trade_id=1,
        key="short",
        direction="SHORT",
        entry_key_bar_index=1,
        key_kline_ref=KlineRef(dt=base_strategy.datetime.fromtimestamp(0), high=110.0, low=90.0),
        stoploss_atr_mult=0.0,
        entry_need_confirm=False,
        exit_need_confirm=False,
        enable_breakeven=False,
        risk_reward_ratio=0.0,
    )
    ctx.status = TradeStatus.ACTIVE

    actions = router.route(
        SignalSnapshot(bar_index=2, long_signal=True, short_signal=False, long_context={"kind": "exit"}),
        SignalRoutingState(mode="SHORT_ONLY", can_open_new_position=True, active_trade=ctx, position_size=-1.0),
    )

    assert actions[-1].action_type == SignalRouteActionType.EXIT
    assert actions[-1].exit_reason_code == "signal_exit"
    assert actions[-1].exit_reason_detail == "SHORT_ONLY 模式下出现反向信号"


def test_risk_engine_computes_initial_stop_take_profit_and_breakeven():
    risk = StrategyRiskEngine()
    stop = risk.initial_stop_price(
        direction="LONG",
        key_low=95.0,
        key_high=110.0,
        stoploss_atr_mult=1.0,
        atr_value=2.5,
    )
    assert stop == 92.5

    lifecycle = TradeLifecycleEngine()
    ctx = lifecycle.create_trade(
        trade_id=1,
        key="long",
        direction="LONG",
        entry_key_bar_index=1,
        key_kline_ref=KlineRef(dt=base_strategy.datetime.fromtimestamp(0), high=110.0, low=90.0),
        stoploss_atr_mult=0.0,
        entry_need_confirm=False,
        exit_need_confirm=False,
        enable_breakeven=True,
        risk_reward_ratio=2.0,
    )
    ctx.entry_price = 100.0
    ctx.initial_stop_price = 90.0
    ctx.stop_price = 90.0

    assert risk.take_profit_price(ctx) == 120.0
    adjustment = risk.breakeven_adjustment(ctx, close_price=121.0)
    assert adjustment is not None
    assert adjustment.old_stop == 90.0
    assert adjustment.new_stop == 110.0
    assert adjustment.step == 2


def test_backtrader_adapter_owns_concrete_order_calls():
    strategy = FakeBacktraderStrategy()
    adapter = BacktraderStrategyExecutionAdapter(strategy)
    ctx = TradeLifecycleEngine().create_trade(
        trade_id=1,
        key="short",
        direction="SHORT",
        entry_key_bar_index=1,
        key_kline_ref=KlineRef(dt=base_strategy.datetime.fromtimestamp(0), high=110.0, low=90.0),
        stoploss_atr_mult=0.0,
        entry_need_confirm=False,
        exit_need_confirm=False,
        enable_breakeven=False,
        risk_reward_ratio=1.0,
    )
    ctx.stop_price = 110.0
    ctx.tp_price = 80.0
    strategy.position.size = -2.0

    adapter.open_entry(ctx)
    adapter.place_or_replace_stop(ctx)
    adapter.place_or_replace_take_profit(ctx)
    adapter.close_position(ctx)

    assert [call[0] for call in strategy.calls] == ["sell", "buy", "buy", "buy"]
    assert strategy.calls[1][1]["price"] == 110.0
    assert strategy.calls[2][1]["price"] == 80.0
    assert strategy.calls[2][1]["oco"] is ctx.stop_order


class FakeOrder:
    def __init__(self, ref):
        self.ref = ref

    def alive(self):
        return True


class FakePosition:
    size = 0.0


class FakeBacktraderStrategy:
    def __init__(self):
        self.calls = []
        self.position = FakePosition()
        self._order_seq = 0

    def buy(self, **kwargs):
        self.calls.append(("buy", kwargs))
        return self._order()

    def sell(self, **kwargs):
        self.calls.append(("sell", kwargs))
        return self._order()

    def cancel(self, order):
        self.calls.append(("cancel", {"order": order}))

    def _order(self):
        self._order_seq += 1
        return FakeOrder(self._order_seq)
