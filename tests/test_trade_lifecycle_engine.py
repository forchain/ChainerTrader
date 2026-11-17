from datetime import datetime

from trader.strategy.lifecycle import (
    EntryConfirmation,
    ExitConfirmation,
    KlineRef,
    OperateFactory,
    TradeLifecycleEngine,
)
from trader.strategy.risk import StrategyRiskEngine
from trader.utils.operate import OperateType


def _ctx(engine: TradeLifecycleEngine, *, direction="LONG", entry_need_confirm=True, trailing=0.0):
    return engine.create_trade(
        trade_id=engine.allocate_trade_id(),
        key="k",
        direction=direction,
        entry_key_bar_index=1,
        key_kline_ref=KlineRef(dt=datetime(2024, 1, 1), high=110.0, low=100.0),
        stoploss_atr_mult=0.0,
        entry_need_confirm=entry_need_confirm,
        exit_need_confirm=True,
        enable_breakeven=True,
        risk_reward_ratio=2.0,
        trailing_stop_ratio=trailing,
    )


def test_engine_owns_registry_and_replacement_queue():
    engine = TradeLifecycleEngine()
    ctx = _ctx(engine)
    engine.register(ctx)
    engine.set_active_trade(ctx)

    assert engine.resolve(ctx.trade_id) is ctx
    assert engine.registry.active_trade is ctx
    assert engine.pending_replacement is None


def test_entry_confirmation_transitions_without_cerebro():
    engine = TradeLifecycleEngine()
    ctx = _ctx(engine)

    assert engine.entry_confirmation(ctx, close=105.0, opposing_signal=False, can_open=True) == EntryConfirmation.PENDING
    assert engine.entry_confirmation(ctx, close=111.0, opposing_signal=False, can_open=True) == EntryConfirmation.CONFIRMED

    opposing = _ctx(engine)
    assert engine.entry_confirmation(opposing, close=105.0, opposing_signal=True, can_open=True) == EntryConfirmation.CANCELLED_OPPOSING_SIGNAL
    assert opposing.entry_key_bar_index in engine.registry.banned_entry_key_bar_index

    failed = _ctx(engine)
    assert engine.entry_confirmation(failed, close=99.0, opposing_signal=False, can_open=True) == EntryConfirmation.CANCELLED_FAILED


def test_exit_confirmation_transitions_without_cerebro():
    engine = TradeLifecycleEngine()
    ctx = _ctx(engine, entry_need_confirm=False)
    engine.mark_entry_filled(ctx, price=100.0, fallback_stop_price=95.0)
    engine.request_exit(
        ctx,
        exit_key_bar_index=2,
        exit_key_ref=KlineRef(dt=datetime(2024, 1, 2), high=110.0, low=100.0),
        exit_need_confirm=True,
        reason_code="signal_exit",
        reason_label="exit",
    )

    assert engine.exit_confirmation(ctx, close=105.0) == ExitConfirmation.PENDING
    assert engine.exit_confirmation(ctx, close=99.0) == ExitConfirmation.CONFIRMED


def test_exit_confirmation_failure_bans_exit_key():
    engine = TradeLifecycleEngine()
    ctx = _ctx(engine, entry_need_confirm=False)
    engine.mark_entry_filled(ctx, price=100.0, fallback_stop_price=95.0)
    engine.request_exit(
        ctx,
        exit_key_bar_index=2,
        exit_key_ref=KlineRef(dt=datetime(2024, 1, 2), high=110.0, low=100.0),
        exit_need_confirm=True,
        reason_code="signal_exit",
        reason_label="exit",
    )

    assert engine.exit_confirmation(ctx, close=112.0) == ExitConfirmation.FAILED
    assert 2 in engine.registry.banned_exit_key_bar_index


def test_breakeven_and_trailing_transitions_mutate_context_inside_engine():
    engine = TradeLifecycleEngine()
    risk = StrategyRiskEngine()
    ctx = _ctx(engine, entry_need_confirm=False, trailing=0.8)
    engine.mark_entry_filled(ctx, price=100.0, fallback_stop_price=90.0)

    adjustment = engine.advance_breakeven(ctx, close_price=120.0, risk_engine=risk)

    assert adjustment is not None
    assert ctx.stop_price == adjustment.new_stop
    assert ctx.stop_source == "breakeven"

    first = engine.advance_trailing(ctx, high=130.0, low=118.0, close=125.0, risk_engine=risk)
    assert first.adjustment is None
    second = engine.advance_trailing(ctx, high=126.0, low=120.0, close=122.0, risk_engine=risk)
    assert second.peak_confirmed is True
    assert second.adjustment is not None
    assert ctx.stop_source == "trailing"
    broken = engine.advance_trailing(ctx, high=124.0, low=110.0, close=ctx.trailing_stop_price - 1.0, risk_engine=risk)
    assert broken.stop_broken is True


def test_operate_factory_builds_typed_events_without_call_site_mutation():
    engine = TradeLifecycleEngine()
    ctx = _ctx(engine, entry_need_confirm=False)
    engine.mark_entry_filled(ctx, price=100.0, fallback_stop_price=90.0)
    ctx.tp_price = 120.0
    ctx.breakeven_step = 2

    risk_op = OperateFactory.risk_update_breakeven(ctx, dtime=10, old_stop=100.0, new_stop=110.0)
    entry_op = OperateFactory.entry(OperateType.LONG, 10, 100.0, ctx)
    exit_op = OperateFactory.exit(OperateType.CLOSE, 11, 101.0, ctx)

    assert risk_op.trigger_reason == "breakeven_move"
    assert risk_op.framework_trade["trade_id"] == ctx.trade_id
    assert entry_op.framework_trade["direction"] == "LONG"
    assert exit_op.price == 101.0
