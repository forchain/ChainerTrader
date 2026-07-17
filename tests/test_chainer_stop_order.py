import datetime as dt

import backtrader as bt
import pandas as pd

from trader.strategy.base_strategy import BaseStrategy


def _build_df(rows):
    base = dt.datetime(2024, 1, 1, 0, 0, 0)
    data = []
    for i, r in enumerate(rows):
        data.append(
            dict(
                datetime=base + dt.timedelta(hours=i),
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=float(r.get("volume", 1.0)),
            )
        )
    return pd.DataFrame(data)


def test_stop_order_triggers_on_low_even_if_close_above_stop():
    class StopOrderStrategy(BaseStrategy):
        params = (
            ("name", "STOP_ORDER_INTRABAR_TEST"),
            ("chainer_stoploss_atr_mult", 0.0),
            ("chainer_need_confirm", False),
            ("chainer_enable_breakeven", False),
            ("chainer_risk_reward_ratio", 0.0),
        )

        def __init__(self):
            super().__init__()
            self.ctx = None
            self.stop_completed_bar = None

        def notify_order(self, order):
            super().notify_order(order)
            if order.status == order.Completed and order.info.get("chainer_role") == "stop":
                self.stop_completed_bar = self.bar_idx()

        def next(self):
            super().next()
            if self.order is not None:
                return
            if self.ctx is not None:
                return
            # Enter at bar 3, stop will be key_low of that bar
            if self.bar_idx() == 3:
                self.ctx = self.enter_trade(
                    direction="LONG",
                    key_bar_index=self.bar_idx(),
                    need_confirm=False,
                    stoploss_atr_mult=0.0,
                    enable_breakeven=False,
                    risk_reward_ratio=0.0,
                )

    rows = [
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=105, low=95, close=100),  # key bar -> stop=95
        dict(open=100, high=106, low=94, close=104),  # entry fills at open=100, same-day low breaks stop(95)
        dict(open=104, high=110, low=99, close=106),
        dict(open=106, high=107, low=100, close=101),
    ]

    cerebro = bt.Cerebro()
    cerebro.addstrategy(StopOrderStrategy)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    strategies = cerebro.run()
    st = strategies[0]

    assert st.ctx is not None
    ctx = st.ctx
    assert ctx.entry_price is not None
    assert ctx.stop_price is not None
    assert float(ctx.stop_price) == 95.0
    # Stop should close on the entry bar when its intrabar low breaks the stop.
    assert ctx.exit_price is not None
    assert abs(float(ctx.exit_price) - 95.0) < 1e-9
    assert st.stop_completed_bar == 4


def test_short_stop_order_triggers_on_high_even_if_close_below_stop():
    class ShortStopOrderStrategy(BaseStrategy):
        params = (
            ("name", "SHORT_STOP_ORDER_INTRABAR_TEST"),
            ("chainer_mode", "SHORT_ONLY"),
            ("chainer_stoploss_atr_mult", 0.0),
            ("chainer_need_confirm", False),
            ("chainer_enable_breakeven", False),
            ("chainer_risk_reward_ratio", 0.0),
        )

        def __init__(self):
            super().__init__()
            self.ctx = None

        def next(self):
            super().next()
            if self.order is not None:
                return
            if self.ctx is not None:
                return
            if self.bar_idx() == 3:
                self.ctx = self.enter_trade(
                    direction="SHORT",
                    key_bar_index=self.bar_idx(),
                    need_confirm=False,
                    stoploss_atr_mult=0.0,
                    enable_breakeven=False,
                    risk_reward_ratio=0.0,
                )

    rows = [
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=105, low=95, close=100),  # key bar -> short stop=105
        dict(open=100, high=101, low=94, close=96),  # entry fills at open=100
        dict(open=96, high=106, low=90, close=94),  # high breaks stop(105), close remains below stop
        dict(open=94, high=95, low=91, close=93),
    ]

    cerebro = bt.Cerebro()
    cerebro.addstrategy(ShortStopOrderStrategy)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    strategies = cerebro.run()
    st = strategies[0]

    assert st.ctx is not None
    ctx = st.ctx
    assert ctx.direction == "SHORT"
    assert ctx.entry_price is not None
    assert ctx.stop_price is not None
    assert float(ctx.stop_price) == 105.0
    assert ctx.exit_price is not None
    assert abs(float(ctx.exit_price) - 105.0) < 1e-9


def test_replaced_created_stop_order_does_not_execute_after_trade_closed():
    class SameBarBreakevenShortStrategy(BaseStrategy):
        params = (
            ("name", "SAME_BAR_BREAKEVEN_SHORT_TEST"),
            ("chainer_mode", "SHORT_ONLY"),
            ("chainer_stoploss_atr_mult", 0.0),
            ("chainer_need_confirm", False),
            ("chainer_enable_breakeven", True),
            ("chainer_risk_reward_ratio", 0.0),
        )

        def __init__(self):
            super().__init__()
            self.ctx = None
            self.completed_orders = []

        def notify_order(self, order):
            super().notify_order(order)
            if order.status == order.Completed:
                self.completed_orders.append(
                    {
                        "tradeid": order.tradeid,
                        "role": order.info.get("chainer_role"),
                        "isbuy": order.isbuy(),
                        "price": float(order.executed.price),
                    }
                )

        def next(self):
            super().next()
            if self.order is not None:
                return
            if self.ctx is not None:
                return
            if self.bar_idx() == 3:
                self.ctx = self.enter_trade(
                    direction="SHORT",
                    key_bar_index=self.bar_idx(),
                    need_confirm=False,
                    stoploss_atr_mult=0.0,
                    enable_breakeven=True,
                    risk_reward_ratio=0.0,
                )

    rows = [
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=105, low=95, close=100),  # key bar -> initial short stop=105
        dict(open=100, high=101, low=89, close=90),  # entry fills, breakeven replaces stop on same bar
        dict(open=90, high=96, low=88, close=92),  # replacement stop exits
        dict(open=92, high=106, low=90, close=94),  # stale initial stop must not execute here
    ]

    cerebro = bt.Cerebro()
    cerebro.addstrategy(SameBarBreakevenShortStrategy)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    strategies = cerebro.run()
    st = strategies[0]

    stop_fills = [
        order for order in st.completed_orders if order["tradeid"] == st.ctx.trade_id and order["role"] == "stop"
    ]
    assert len(stop_fills) == 1
    assert st.position.size == 0


def test_short_take_profit_is_below_entry_and_triggers_on_low():
    class ShortTakeProfitStrategy(BaseStrategy):
        params = (
            ("name", "SHORT_TAKE_PROFIT_TEST"),
            ("chainer_mode", "SHORT_ONLY"),
            ("chainer_stoploss_atr_mult", 0.0),
            ("chainer_need_confirm", False),
            ("chainer_enable_breakeven", False),
            ("chainer_risk_reward_ratio", 1.0),
        )

        def __init__(self):
            super().__init__()
            self.ctx = None

        def next(self):
            super().next()
            if self.order is not None:
                return
            if self.ctx is not None:
                return
            if self.bar_idx() == 3:
                self.ctx = self.enter_trade(
                    direction="SHORT",
                    key_bar_index=self.bar_idx(),
                    need_confirm=False,
                    stoploss_atr_mult=0.0,
                    enable_breakeven=False,
                    risk_reward_ratio=1.0,
                )

    rows = [
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=105, low=95, close=100),  # key bar -> stop=105
        dict(open=100, high=101, low=99, close=96),  # entry fills at 100, tp=95
        dict(open=96, high=97, low=94, close=96),  # low reaches tp
        dict(open=96, high=97, low=93, close=94),
    ]

    cerebro = bt.Cerebro()
    cerebro.addstrategy(ShortTakeProfitStrategy)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    strategies = cerebro.run()
    st = strategies[0]

    assert st.ctx is not None
    ctx = st.ctx
    assert ctx.direction == "SHORT"
    assert ctx.entry_price is not None
    assert float(ctx.entry_price) == 100.0
    assert float(ctx.initial_stop_price) == 105.0
    assert ctx.tp_price is not None
    assert float(ctx.tp_price) == 95.0
    assert ctx.exit_price is not None
    assert abs(float(ctx.exit_price) - 95.0) < 1e-9
    assert ctx.exit_reason_code == "risk_reward_take_profit"
