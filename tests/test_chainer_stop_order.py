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
        dict(open=100, high=106, low=99, close=104),  # entry fills at open=100, stop order becomes active
        dict(open=104, high=110, low=94, close=106),  # low breaks stop(95), but close stays above
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
    # Stop should have closed the trade even though close(106) > stop(95)
    assert ctx.exit_price is not None
    assert abs(float(ctx.exit_price) - 95.0) < 1e-9
