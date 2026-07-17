from __future__ import annotations

import backtrader as bt

from trader.strategy.lifecycle import (
    ORDER_ROLE_ENTRY,
    ORDER_ROLE_EXIT,
    ORDER_ROLE_KEY,
    ORDER_ROLE_STOP,
    ORDER_ROLE_TP,
    TradeContext,
)


class BacktraderStrategyExecutionAdapter:
    def __init__(self, strategy):
        self.strategy = strategy

    def open_entry(self, ctx: TradeContext):
        if ctx.direction == "LONG":
            entry_order = self.strategy.buy(tradeid=ctx.trade_id, **{ORDER_ROLE_KEY: ORDER_ROLE_ENTRY})
            if entry_order is not None and ctx.stop_price is not None:
                ctx.stop_order = self.strategy.sell(
                    size=float(entry_order.size),
                    exectype=bt.Order.Stop,
                    price=float(ctx.stop_price),
                    tradeid=ctx.trade_id,
                    **{ORDER_ROLE_KEY: ORDER_ROLE_STOP},
                )
            return entry_order

        entry_order = self.strategy.sell(tradeid=ctx.trade_id, **{ORDER_ROLE_KEY: ORDER_ROLE_ENTRY})
        if entry_order is not None and ctx.stop_price is not None:
            ctx.stop_order = self.strategy.buy(
                size=float(entry_order.size),
                exectype=bt.Order.Stop,
                price=float(ctx.stop_price),
                tradeid=ctx.trade_id,
                **{ORDER_ROLE_KEY: ORDER_ROLE_STOP},
            )
        return entry_order

    def close_position(self, ctx: TradeContext, *, oco_order=None):
        close_size = self.close_size()
        if close_size <= 0.0:
            return None
        pos_size = self.position_size()
        if pos_size > 0:
            return self.strategy.sell(size=close_size, tradeid=ctx.trade_id, oco=oco_order, **{ORDER_ROLE_KEY: ORDER_ROLE_EXIT})
        return self.strategy.buy(size=close_size, tradeid=ctx.trade_id, oco=oco_order, **{ORDER_ROLE_KEY: ORDER_ROLE_EXIT})

    def cancel_stop(self, ctx: TradeContext) -> None:
        order = getattr(ctx, "stop_order", None)
        if order is None:
            return
        try:
            if order.alive():
                self.strategy.cancel(order)
                return
        except Exception:
            pass
        ctx.stop_order = None

    def cancel_take_profit(self, ctx: TradeContext) -> None:
        order = getattr(ctx, "tp_order", None)
        if order is None:
            return
        try:
            if order.alive():
                self.strategy.cancel(order)
                return
        except Exception:
            pass
        ctx.tp_order = None

    def place_or_replace_stop(self, ctx: TradeContext):
        if ctx.stop_price is None:
            return None
        close_size = self.close_size()
        if close_size <= 0.0:
            return None

        old_order = getattr(ctx, "stop_order", None)
        oco_order = getattr(ctx, "tp_order", None)
        self.cancel_stop(ctx)
        stop_price = float(ctx.stop_price)
        if ctx.direction == "LONG":
            order = self.strategy.sell(
                size=close_size,
                exectype=bt.Order.Stop,
                price=stop_price,
                tradeid=ctx.trade_id,
                oco=oco_order or old_order,
                **{ORDER_ROLE_KEY: ORDER_ROLE_STOP},
            )
        else:
            order = self.strategy.buy(
                size=close_size,
                exectype=bt.Order.Stop,
                price=stop_price,
                tradeid=ctx.trade_id,
                oco=oco_order or old_order,
                **{ORDER_ROLE_KEY: ORDER_ROLE_STOP},
            )
        ctx.stop_order = order
        return order

    def place_or_replace_take_profit(self, ctx: TradeContext):
        if ctx.tp_price is None:
            return None
        close_size = self.close_size()
        if close_size <= 0.0:
            return None

        self.cancel_take_profit(ctx)
        oco_order = getattr(ctx, "stop_order", None)
        tp_price = float(ctx.tp_price)
        if ctx.direction == "LONG":
            order = self.strategy.sell(
                size=close_size,
                exectype=bt.Order.Limit,
                price=tp_price,
                tradeid=ctx.trade_id,
                oco=oco_order,
                **{ORDER_ROLE_KEY: ORDER_ROLE_TP},
            )
        else:
            order = self.strategy.buy(
                size=close_size,
                exectype=bt.Order.Limit,
                price=tp_price,
                tradeid=ctx.trade_id,
                oco=oco_order,
                **{ORDER_ROLE_KEY: ORDER_ROLE_TP},
            )
        ctx.tp_order = order
        return order

    def position_size(self) -> float:
        return float(getattr(self.strategy.position, "size", 0.0))

    def close_size(self) -> float:
        return float(abs(self.position_size()))
