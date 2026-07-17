import datetime as dt

import backtrader as bt
import pandas as pd
import pytest

from trader.analyzers.backtest_report import BacktestReportAnalyzer
from trader.strategy.base_strategy import BaseStrategy
from trader.strategy.lifecycle import KlineRef, TradeLifecycleEngine
from trader.strategy.risk import StrategyRiskEngine


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
            ("chainer_atr_period", 3),
            ("chainer_mode", "LONG_ONLY"),  # Support LONG entries
            ("chainer_stoploss_atr_mult", 1.0),
            ("chainer_need_confirm", False),
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


def test_suggested_stop_price_is_atr_adjusted_when_atr_is_enabled():
    risk = StrategyRiskEngine()

    long_stop = risk.initial_stop_price(
        direction="LONG",
        key_low=95.0,
        key_high=110.0,
        stoploss_atr_mult=1.0,
        atr_value=5.0,
        signal_metadata={"suggested_stop_price": 90.0},
    )
    short_stop = risk.initial_stop_price(
        direction="SHORT",
        key_low=95.0,
        key_high=110.0,
        stoploss_atr_mult=1.0,
        atr_value=5.0,
        signal_metadata={"suggested_stop_price": 115.0},
    )

    assert long_stop == 85.0
    assert short_stop == 120.0


def test_trailing_stop_anchors_to_initial_stop_and_only_tightens():
    lifecycle = TradeLifecycleEngine()
    risk = StrategyRiskEngine()
    long_ctx = lifecycle.create_trade(
        trade_id=1,
        key="long",
        direction="LONG",
        entry_key_bar_index=1,
        key_kline_ref=KlineRef(dt=dt.datetime(2024, 1, 1), high=100.0, low=90.0),
        stoploss_atr_mult=0.0,
        entry_need_confirm=False,
        exit_need_confirm=False,
        enable_breakeven=True,
        risk_reward_ratio=0.0,
    )
    long_ctx.initial_stop_price = 90.0
    long_ctx.stop_price = 108.0  # A prior breakeven move must not be loosened.

    long_adjustment = risk.trailing_stop_adjustment(long_ctx, best_price=130.0, ratio=0.5)

    assert long_adjustment is not None
    assert long_adjustment.old_stop == 108.0
    assert long_adjustment.new_stop == 110.0
    assert long_adjustment.best_price == 130.0

    short_ctx = lifecycle.create_trade(
        trade_id=2,
        key="short",
        direction="SHORT",
        entry_key_bar_index=1,
        key_kline_ref=KlineRef(dt=dt.datetime(2024, 1, 1), high=110.0, low=100.0),
        stoploss_atr_mult=0.0,
        entry_need_confirm=False,
        exit_need_confirm=False,
        enable_breakeven=True,
        risk_reward_ratio=0.0,
    )
    short_ctx.initial_stop_price = 110.0
    short_ctx.stop_price = 92.0  # A prior breakeven move must not be loosened.

    short_adjustment = risk.trailing_stop_adjustment(short_ctx, best_price=70.0, ratio=0.5)

    assert short_adjustment is not None
    assert short_adjustment.old_stop == 92.0
    assert short_adjustment.new_stop == 90.0
    assert short_adjustment.best_price == 70.0


def test_trailing_stop_does_not_move_until_it_is_profitable():
    lifecycle = TradeLifecycleEngine()
    risk = StrategyRiskEngine()
    long_ctx = lifecycle.create_trade(
        trade_id=1,
        key="long",
        direction="LONG",
        entry_key_bar_index=1,
        key_kline_ref=KlineRef(dt=dt.datetime(2024, 1, 1), high=110.0, low=90.0),
        stoploss_atr_mult=0.0,
        entry_need_confirm=False,
        exit_need_confirm=False,
        enable_breakeven=False,
        risk_reward_ratio=0.0,
    )
    long_ctx.entry_price = 100.0
    long_ctx.initial_stop_price = 90.0
    long_ctx.stop_price = 90.0

    assert risk.trailing_stop_adjustment(long_ctx, best_price=105.0, ratio=0.1) is None


def test_trailing_stop_uses_close_confirmation_before_next_open_exit():
    risk_updates = []

    class TrailingStopProbe(BaseStrategy):
        params = (
            ("name", "TRAILING_STOP_PROBE"),
            ("chainer_mode", "LONG_ONLY"),
            ("chainer_stoploss_atr_mult", 0.0),
            ("chainer_trailing_stop_ratio", 0.5),
            ("chainer_need_confirm", False),
            ("chainer_enable_breakeven", False),
            ("chainer_risk_reward_ratio", 0.0),
            ("live_operation_sink", risk_updates.append),
        )

        def __init__(self):
            super().__init__()
            self.entry_ctx = None

        def log_info(self, msg):
            pass

        def log_debug(self, msg):
            pass

        def get_long_signal(self):
            return False

        def get_short_signal(self):
            return False

        def next(self):
            super().next()
            if self.entry_ctx is None and len(self) == 4:
                self.entry_ctx = self.enter_trade(direction="LONG", key_bar_index=self.bar_idx())

    rows = [dict(open=100, high=101, low=90, close=100) for _ in range(4)] + [
        # Entry fills at this open. No favorable peak exists yet.
        dict(open=100, high=100, low=99, close=99),
        # This high is a candidate peak, not yet confirmed.
        dict(open=99, high=120, low=98, close=115),
        # A higher high replaces the candidate without moving the stop.
        dict(open=110, high=125, low=110, close=120),
        # The lower high confirms the 125 peak, but this same close is already
        # below the new stop. The confirmation bar is a cooldown bar and cannot exit.
        dict(open=115, high=120, low=100, close=106),
        # A later close below the trailing stop submits a market exit for the next open.
        dict(open=104, high=106, low=100, close=106),
        dict(open=103, high=105, low=101, close=104),
    ]
    cerebro = bt.Cerebro()
    cerebro.addstrategy(TrailingStopProbe)
    cerebro.adddata(bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime"))
    cerebro.addanalyzer(
        BacktestReportAnalyzer,
        _name="backtest_report",
        strategy_name="trailing_stop_probe",
        symbol="BTCUSDT",
        interval="1d",
    )
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    strategy = cerebro.run()[0]

    trade = strategy.entry_ctx
    assert trade is not None
    assert float(trade.initial_stop_price) == 90.0
    assert float(trade.trailing_best_price) == 125.0
    assert float(trade.trailing_stop_price) == 107.5
    assert trade.trailing_update_count == 1
    assert float(trade.exit_price) == 103.0
    assert trade.exit_reason_code == "framework_stop"
    assert "移动止盈" in str(trade.exit_reason_detail)

    report_trade = strategy.analyzers.backtest_report.report["trades"][0]
    assert report_trade["framework_trailing_best_price"] == 125.0
    assert report_trade["framework_trailing_stop_price"] == 107.5
    assert report_trade["framework_trailing_update_count"] == 1

    assert len(risk_updates) == 1
    assert risk_updates[0].trigger_reason == "trailing_stop_move"
    assert risk_updates[0].stop_loss == 107.5
    assert risk_updates[0].framework_trade["trailing_best_price"] == 125.0


def test_short_trailing_stop_updates_after_a_confirmed_trough():
    class ShortTrailingStopProbe(BaseStrategy):
        params = (
            ("name", "SHORT_TRAILING_STOP_PROBE"),
            ("chainer_mode", "SHORT_ONLY"),
            ("chainer_stoploss_atr_mult", 0.0),
            ("chainer_trailing_stop_ratio", 0.5),
            ("chainer_need_confirm", False),
            ("chainer_enable_breakeven", False),
            ("chainer_risk_reward_ratio", 0.0),
        )

        def __init__(self):
            super().__init__()
            self.entry_ctx = None

        def log_info(self, msg):
            pass

        def log_debug(self, msg):
            pass

        def get_long_signal(self):
            return False

        def get_short_signal(self):
            return False

        def next(self):
            super().next()
            if self.entry_ctx is None and len(self) == 4:
                self.entry_ctx = self.enter_trade(direction="SHORT", key_bar_index=self.bar_idx())

    rows = [dict(open=100, high=110, low=99, close=100) for _ in range(4)] + [
        dict(open=100, high=101, low=80, close=85),
        dict(open=85, high=86, low=70, close=75),
        # The higher low confirms the 70 trough, but this close is already above
        # the new stop. The confirmation bar is a cooldown bar and cannot exit.
        dict(open=75, high=100, low=72, close=92),
        # Intraday price crosses the stop, but the close remains below it.
        dict(open=80, high=91, low=75, close=85),
        # A close above the short trailing stop exits at the next open.
        dict(open=93, high=95, low=90, close=92),
        dict(open=94, high=96, low=92, close=95),
    ]
    cerebro = bt.Cerebro()
    cerebro.addstrategy(ShortTrailingStopProbe)
    cerebro.adddata(bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime"))
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    strategy = cerebro.run()[0]

    trade = strategy.entry_ctx
    assert trade is not None
    assert float(trade.trailing_best_price) == 70.0
    assert float(trade.trailing_stop_price) == 90.0
    assert trade.trailing_update_count == 1
    assert float(trade.exit_price) == 94.0


def test_trailing_stop_ratio_rejects_values_outside_zero_to_one():
    class InvalidTrailingStopRatioStrategy(BaseStrategy):
        params = (("chainer_trailing_stop_ratio", 1.01),)

    cerebro = bt.Cerebro()
    cerebro.addstrategy(InvalidTrailingStopRatioStrategy)
    cerebro.adddata(bt.feeds.PandasData(dataname=_build_df([dict(open=100, high=101, low=99, close=100)]), datetime="datetime"))

    with pytest.raises(ValueError, match="chainer_trailing_stop_ratio"):
        cerebro.run()


def test_suggested_stop_price_overrides_framework_stop_price():
    class SuggestedStopIsolationStrategy(BaseStrategy):
        params = (
            ("name", "SUGGESTED_STOP_ISOLATION_TEST"),
            ("chainer_mode", "LONG_ONLY"),
            ("chainer_stoploss_atr_mult", 0.0),
            ("chainer_need_confirm", False),
            ("chainer_enable_breakeven", False),
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
                enable_breakeven=False,
                risk_reward_ratio=0.0,
                signal_metadata={"suggested_stop_price": 70.0, "signal_time": "2024-01-01T00:00:00"},
            )

    rows = [
        dict(open=100, high=105, low=95, close=100),
        dict(open=100, high=105, low=95, close=100),
        dict(open=100, high=105, low=95, close=100),
        dict(open=100, high=105, low=95, close=100),
        dict(open=100, high=105, low=95, close=100),
    ]
    cerebro = bt.Cerebro()
    cerebro.addstrategy(SuggestedStopIsolationStrategy)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    strategies = cerebro.run()
    st = strategies[0]

    assert st.entry_ctx is not None
    # framework default would be key_low (95.0), but suggested_stop_price (70.0) should override
    assert float(st.entry_ctx.initial_stop_price) == 70.0
    assert st.entry_ctx.signal_metadata.get("suggested_stop_price") == 70.0
