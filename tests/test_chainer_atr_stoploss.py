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


def test_stoploss_atr_mult_applies_even_when_cfg_atr_disabled():
    # Regression: if ATR is created lazily at enter_trade time, Backtrader won't backfill
    # history and ATR is NaN for atrperiod bars => stoploss_atr_mult has no effect.
    class AtrStopStrategy(BaseStrategy):
        params = (
            ("name", "ATR_STOP_MULT_TEST"),
            ("atr", False),  # simulate cfg.atr disabled
            ("atrperiod", 3),
            ("chainer_mode", "LONG_ONLY"),  # Support LONG entries
            ("chainer_stoploss_atr_mult", 1.0),
            ("chainer_long_need_confirm", False),
            ("chainer_short_need_confirm", True),
            ("chainer_enable_breakeven", True),
            ("chainer_risk_reward_ratio", 0.0),
        )

        def __init__(self):
            super().__init__()
            self.entry_ctx = None

        def next(self):
            super().next()
            if self.order is not None:
                return
            if self.entry_ctx is not None:
                return
            if len(self) < 4:
                return
            self.entry_ctx = self.enter_trade(
                trade_key=None,
                direction="LONG",
                key_bar_index=self.bar_idx(),
                stoploss_atr_mult=None,
                need_confirm=False,
                enable_breakeven=True,
                risk_reward_ratio=0.0,
            )

    # Constant true range => ATR should be stable and > 0 once warmed up.
    rows = [
        dict(open=100, high=105, low=95, close=100),
        dict(open=100, high=105, low=95, close=100),
        dict(open=100, high=105, low=95, close=100),
        dict(open=100, high=105, low=95, close=100),
        dict(open=100, high=105, low=95, close=100),
    ]
    cerebro = bt.Cerebro()
    cerebro.addstrategy(AtrStopStrategy)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    strategies = cerebro.run()
    st = strategies[0]

    assert st.entry_ctx is not None
    assert st.entry_ctx.stoploss_atr_mult == 1.0
    assert st.entry_ctx.initial_stop_price is not None
    # key_low=95, ATR(3) should be ~10 => stop should be < 95 when mult=1.0
    assert float(st.entry_ctx.initial_stop_price) < float(st.entry_ctx.key_kline_ref.low)
