from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from trader.libraries.chainer_trader import ChainerTraderLib
from trader.strategy.lifecycle import TradeContext

BREAKEVEN_EPS = 1e-10


@dataclass(frozen=True)
class BreakevenAdjustment:
    old_stop: float
    new_stop: float
    step: int


@dataclass(frozen=True)
class TrailingStopAdjustment:
    old_stop: float
    new_stop: float
    best_price: float


class StrategyRiskEngine:
    def initial_stop_price(
        self,
        *,
        direction: str,
        key_low: float,
        key_high: float,
        stoploss_atr_mult: float,
        atr_value: float,
        signal_metadata: dict[str, Any] | None = None,
    ) -> float:
        suggested_stop = None
        try:
            suggested_stop = (signal_metadata or {}).get("suggested_stop_price")
        except Exception:
            suggested_stop = None

        direction_norm = str(direction).upper()
        if suggested_stop is not None:
            stop_price = float(suggested_stop)
        else:
            stop_price = float(key_low) if direction_norm == "LONG" else float(key_high)
        if float(stoploss_atr_mult) == 0.0:
            return stop_price
        if direction_norm == "LONG":
            return stop_price - (float(stoploss_atr_mult) * float(atr_value))
        return stop_price + (float(stoploss_atr_mult) * float(atr_value))

    def take_profit_price(self, ctx: TradeContext) -> float | None:
        if ctx.entry_price is None or ctx.initial_stop_price is None or ctx.risk_reward_ratio <= 0.0:
            return None
        tp_price = ChainerTraderLib.risk_reward_price(
            ctx.direction,
            float(ctx.entry_price),
            float(ctx.initial_stop_price),
            float(ctx.risk_reward_ratio),
        )
        return float(tp_price) if tp_price is not None else None

    def breakeven_adjustment(self, ctx: TradeContext, *, close_price: float) -> BreakevenAdjustment | None:
        if not ctx.enable_breakeven:
            return None
        if ctx.entry_price is None or ctx.stop_price is None or ctx.initial_stop_price is None:
            return None

        entry_price = float(ctx.entry_price)
        initial_stop = float(ctx.initial_stop_price)
        is_long = ctx.direction == "LONG"
        risk = (entry_price - initial_stop) if is_long else (initial_stop - entry_price)
        if risk <= 0.0:
            return None

        new_stop = ChainerTraderLib.breakeven_price(
            ctx.direction,
            entry_price,
            initial_stop,
            float(close_price),
        )
        if new_stop is None:
            return None

        should_update = (new_stop > float(ctx.stop_price)) if is_long else (new_stop < float(ctx.stop_price))
        if not should_update:
            return None

        level = ((new_stop - entry_price) / risk) if is_long else ((entry_price - new_stop) / risk)
        step = int(math.floor(level + BREAKEVEN_EPS)) + 1
        return BreakevenAdjustment(
            old_stop=float(ctx.stop_price),
            new_stop=float(new_stop),
            step=max(int(ctx.breakeven_step), int(step)),
        )

    def trailing_stop_adjustment(
        self,
        ctx: TradeContext,
        *,
        best_price: float,
        ratio: float,
    ) -> TrailingStopAdjustment | None:
        if ratio <= 0.0 or ctx.initial_stop_price is None or ctx.stop_price is None:
            return None

        initial_stop = float(ctx.initial_stop_price)
        current_stop = float(ctx.stop_price)
        best = float(best_price)
        if ctx.direction == "LONG":
            candidate = initial_stop + ((best - initial_stop) * float(ratio))
            if candidate <= current_stop or (ctx.entry_price is not None and candidate <= float(ctx.entry_price)):
                return None
        else:
            candidate = initial_stop - ((initial_stop - best) * float(ratio))
            if candidate >= current_stop or (ctx.entry_price is not None and candidate >= float(ctx.entry_price)):
                return None
        return TrailingStopAdjustment(
            old_stop=current_stop,
            new_stop=float(candidate),
            best_price=best,
        )
