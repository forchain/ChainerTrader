from trader.core.shared.domain import Operate


def _ctx_value(ctx, name: str):
    return getattr(ctx, name, None)


def enrich_operation_from_trade_context(op: Operate, ctx) -> Operate:
    """Attach shared framework trade references to an emitted operation."""
    if ctx is None:
        return op

    stop_price = _ctx_value(ctx, "stop_price") or _ctx_value(ctx, "initial_stop_price")
    take_profit = _ctx_value(ctx, "tp_price")
    risk_reward_ratio = _ctx_value(ctx, "risk_reward_ratio")
    signal_metadata = dict(_ctx_value(ctx, "signal_metadata") or {})

    if stop_price is not None:
        op.stop_loss = float(stop_price)
    if take_profit is not None:
        op.take_profit = float(take_profit)
    if risk_reward_ratio is not None:
        op.risk_reward_ratio = float(risk_reward_ratio)
    if signal_metadata:
        op.signal_metadata = signal_metadata
        signal_event_id = signal_metadata.get("signal_event_id") or signal_metadata.get("event_id")
        if signal_event_id:
            op.signal_event_id = signal_event_id

    op.framework_trade = {
        "trade_id": _ctx_value(ctx, "trade_id"),
        "direction": _ctx_value(ctx, "direction"),
        "initial_stop_price": _ctx_value(ctx, "initial_stop_price"),
        "stop_price": _ctx_value(ctx, "stop_price"),
        "take_profit": take_profit,
        "risk_reward_ratio": risk_reward_ratio,
        "breakeven_step": _ctx_value(ctx, "breakeven_step"),
        "exit_reason_code": _ctx_value(ctx, "exit_reason_code"),
        "exit_reason_label": _ctx_value(ctx, "exit_reason_label"),
        "exit_reason_detail": _ctx_value(ctx, "exit_reason_detail"),
        "replacement_trade_id": _ctx_value(ctx, "replacement_trade_id"),
        "stop_multiple_r": _ctx_value(ctx, "stop_multiple_r"),
        "exit_risk_reward_ratio": _ctx_value(ctx, "exit_risk_reward_ratio"),
    }
    return op
