import datetime as dt

import backtrader as bt
import pandas as pd
import pytest

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


class _MACrossEntryExitStrategy(BaseStrategy):
    params = (
        ("name", "MA_CROSS_ENTRY_EXIT_TEST"),
        ("fastLen", 2),
        ("slowLen", 3),
        ("atr", True),
        ("atrperiod", 3),
        ("chainer_stoploss_atr_mult", 0.0),
        ("chainer_long_need_confirm", True),
        ("chainer_short_need_confirm", True),
        ("chainer_enable_breakeven", True),
        ("chainer_risk_reward_ratio", 1.0),
        ("chainer_mode", "LONG_ONLY"),  # Default to LONG_ONLY for LONG entry tests
    )

    def __init__(self):
        super().__init__()
        self.events = []
        self.fast = bt.indicators.SMA(self.data.close, period=self.p.fastLen)
        self.slow = bt.indicators.SMA(self.data.close, period=self.p.slowLen)
        self.cross = bt.indicators.CrossOver(self.fast, self.slow)

    def log_info(self, msg):
        self.events.append(("INFO", self.cur_datetime(), msg))

    def log_debug(self, msg):
        # Keep debug quiet in tests
        self.events.append(("DEBUG", self.cur_datetime(), msg))

    def next(self):
        super().next()

        if self.order is not None:
            return

        ctx = getattr(self, "_active_trade", None)

        # Entry trigger: MA cross up
        if self.cross[0] > 0 and ctx is None and not self.position:
            self.enter_trade(
                trade_key=None,
                direction="LONG",
                key_bar_index=self.bar_idx(),
                stoploss_atr_mult=None,
                need_confirm=None,
                enable_breakeven=None,
                risk_reward_ratio=None,
            )
            return

        # Exit trigger: MA cross down
        if self.cross[0] < 0 and ctx is not None and self.position:
            self.exit_trade(trade_ref=None, key_bar_index=self.bar_idx(), need_confirm=None)


def _run(df, strategy_kwargs=None):
    cerebro = bt.Cerebro()
    kwargs = strategy_kwargs or {}
    cerebro.addstrategy(_MACrossEntryExitStrategy, **kwargs)
    data_feed = bt.feeds.PandasData(dataname=df, datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    strategies = cerebro.run()
    return strategies[0]


def test_entry_confirm_failure_bans_key_time():
    # Key bar is when SMA(2) crosses above SMA(3). Next bar closes below key low -> confirm failure -> cancelled and banned.
    rows = [
        dict(open=100, high=101, low=99, close=100),  # warmup
        dict(open=100, high=101, low=99, close=100),  # warmup
        dict(open=100, high=101, low=98, close=99),  # keep fast < slow
        dict(open=99, high=105, low=95, close=104),  # key bar (cross up)
        dict(open=104, high=105, low=90, close=94),  # close < key_low => fail confirm
        dict(open=94, high=96, low=93, close=95),
    ]
    st = _run(_build_df(rows), dict(fastLen=2, slowLen=3, chainer_long_need_confirm=True, chainer_short_need_confirm=True))

    cancelled = [t for t in st._trades_by_id.values() if t.status == BaseStrategy.TradeStatus.CANCELLED]  # noqa: SLF001
    assert len(cancelled) == 1
    ctx = cancelled[0]
    assert ctx.cancel_reason == "entry_confirm_failed"
    assert ctx.entry_key_bar_index in st._banned_entry_key_bar_index  # noqa: SLF001
    assert st._active_trade is None  # noqa: SLF001


def test_entry_confirm_success_then_breakeven_then_stop_exit():
    # Cross up at key bar; confirm on next bar (close > key_high) places buy; filled next bar open (Backtrader default).
    # Then price reaches 1x RR -> stop moves to entry; then price drops below stop -> stop exit; filled next bar open.
    rows = [
        dict(open=100, high=101, low=99, close=100),  # warmup
        dict(open=100, high=101, low=99, close=100),  # warmup
        dict(open=100, high=101, low=98, close=99),  # keep fast < slow
        dict(open=99, high=105, low=96, close=104),  # key bar (cross up), initial stop=96
        dict(open=104, high=110, low=103, close=106),  # confirm (close>105) places buy
        dict(open=106, high=120, low=105, close=118),  # buy fills at open=106; close hits RR => move stop to 106
        dict(open=118, high=119, low=104, close=105),  # close <= stop(106) => stop exit order
        dict(open=105, high=106, low=100, close=101),  # stop exit fills at open=105
    ]
    st = _run(
        _build_df(rows),
        dict(
            fastLen=2,
            slowLen=3,
            chainer_long_need_confirm=True,
            chainer_short_need_confirm=True,
            chainer_enable_breakeven=True,
            chainer_risk_reward_ratio=0.0,
            chainer_stoploss_atr_mult=0.0,
        ),
    )

    # Trade should be closed by stop logic
    closed = [t for t in st._trades_by_id.values() if t.status == BaseStrategy.TradeStatus.CLOSED]  # noqa: SLF001
    assert len(closed) == 1
    ctx = closed[0]
    assert ctx.entry_price is not None
    assert ctx.exit_price is not None
    assert ctx.breakeven_step >= 1

    # There must be a breakeven move and a stop-exit log line
    msgs = [m for _, __, m in st.events]
    assert any("保本移动止损" in m for m in msgs)
    assert any("止损成交出场" in m for m in msgs)


def test_breakeven_step_matches_r_level_when_price_jumps_multiple_r():
    # Entry confirm success -> entry fills next bar open.
    # Then a single bar close jumps to 3R profit; stop should move to 2R and breakeven_step should be 3.
    rows = [
        dict(open=100, high=101, low=99, close=100),  # warmup
        dict(open=100, high=101, low=99, close=100),  # warmup
        dict(open=100, high=101, low=98, close=99),  # keep fast < slow
        dict(open=99, high=105, low=90, close=104),  # key bar (cross up), initial stop=90
        dict(open=104, high=110, low=103, close=106),  # confirm (close>105) places buy
        dict(open=100, high=135, low=99, close=130),  # entry fill at open=100; close=130 => profit=30 => 3R (R=10)
        dict(open=130, high=131, low=110, close=119),  # close <= stop(120) => stop exit order
        dict(open=119, high=120, low=100, close=111),  # stop exit fills at open=119
    ]
    st = _run(
        _build_df(rows),
        dict(
            fastLen=2,
            slowLen=3,
            chainer_long_need_confirm=True,
            chainer_short_need_confirm=True,
            chainer_enable_breakeven=True,
            chainer_risk_reward_ratio=0.0,
            chainer_stoploss_atr_mult=0.0,
        ),
    )

    closed = [t for t in st._trades_by_id.values() if t.status == BaseStrategy.TradeStatus.CLOSED]  # noqa: SLF001
    assert len(closed) == 1
    ctx = closed[0]

    assert abs(float(ctx.entry_price) - 100.0) < 1e-9
    assert abs(float(ctx.initial_stop_price) - 90.0) < 1e-9
    assert ctx.breakeven_step == 3
    assert abs(float(ctx.stop_price) - 120.0) < 1e-9


@pytest.mark.parametrize("chainer_long_need_confirm,chainer_short_need_confirm", [(False, False)])
def test_no_confirm_places_orders_immediately(chainer_long_need_confirm, chainer_short_need_confirm):
    # Cross up -> immediate buy order; later cross down -> immediate sell order.
    rows = [
        dict(open=100, high=101, low=99, close=100),  # warmup
        dict(open=100, high=101, low=99, close=100),  # warmup
        dict(open=100, high=101, low=98, close=99),  # keep fast < slow
        dict(open=99, high=105, low=70, close=104),  # cross up -> buy created (keep stop far to avoid stop exit)
        dict(open=104, high=106, low=103, close=105),  # buy fills at open
        dict(open=105, high=106, low=90, close=91),  # cross down -> sell created
        dict(open=91, high=92, low=80, close=85),  # sell fills at open
    ]
    st = _run(
        _build_df(rows),
        dict(
            fastLen=2,
            slowLen=3,
            chainer_long_need_confirm=chainer_long_need_confirm,
            chainer_short_need_confirm=chainer_short_need_confirm,
            chainer_enable_breakeven=False,
            chainer_risk_reward_ratio=0.0,
        ),
    )

    msgs = [m for _, __, m in st.events]
    assert any("创建买入订单" in m for m in msgs)
    assert any("创建平仓订单" in m for m in msgs)
    closed = [t for t in st._trades_by_id.values() if t.status == BaseStrategy.TradeStatus.CLOSED]  # noqa: SLF001
    assert len(closed) == 1


def test_short_entry_confirm_success_then_stop_exit():
    # Short entry: confirm success when close < key_low; stop hit when close >= stop.
    class ShortStrategy(BaseStrategy):
        params = (
            ("name", "SHORT_ENTRY_STOP_TEST"),
            # Disable ATR to avoid minperiod gating; this test uses stoploss_atr_mult=0.
            ("atr", False),
            ("chainer_mode", "SHORT_ONLY"),  # Enable SHORT entries
            ("chainer_long_need_confirm", True),
            ("chainer_short_need_confirm", True),
        )

        def __init__(self):
            super().__init__()
            self.events = []

        def log_info(self, msg):
            self.events.append(("INFO", self.cur_datetime(), msg))

        def log_debug(self, msg):
            self.events.append(("DEBUG", self.cur_datetime(), msg))

        def next(self):
            super().next()
            if self.order is not None:
                return
            if getattr(self.position, "size", 0) == 0 and getattr(self, "_active_trade", None) is None:
                self.enter_trade(
                    trade_key=None,
                    direction="SHORT",
                    key_bar_index=self.bar_idx(),
                    stoploss_atr_mult=0.0,
                    need_confirm=True,
                    enable_breakeven=False,
                    risk_reward_ratio=0.0,
                )

    rows = [
        dict(open=100, high=101, low=99, close=100),  # key bar for short setup
        dict(open=100, high=101, low=90, close=89),  # confirm (close < key_low) places sell(short)
        dict(open=89, high=90, low=80, close=82),  # entry fill at open=89
        dict(open=82, high=105, low=81, close=106),  # stop hit (key_high=101) => close >= stop => cover
        dict(open=106, high=107, low=100, close=101),  # exit fill at open=106
    ]
    cerebro = bt.Cerebro()
    cerebro.addstrategy(ShortStrategy)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    strategies = cerebro.run()
    st = strategies[0]

    closed = [t for t in st._trades_by_id.values() if t.status == BaseStrategy.TradeStatus.CLOSED]  # noqa: SLF001
    assert len(closed) == 1
    ctx = closed[0]
    assert ctx.direction == "SHORT"


def test_short_disabled_raises():
    class ShortDisabledStrategy(BaseStrategy):
        params = (("name", "SHORT_DISABLED_TEST"), ("chainer_mode", "LONG_ONLY"))  # SHORT is disabled in LONG_ONLY mode

        def next(self):
            BaseStrategy.next(self)
            if self.order is not None:
                return
            if getattr(self.position, "size", 0) != 0:
                return
            with pytest.raises(ValueError):
                self.enter_trade(
                    trade_key=None,
                    direction="SHORT",
                    key_bar_index=self.bar_idx(),
                    stoploss_atr_mult=0.0,
                    need_confirm=False,
                    enable_breakeven=False,
                    risk_reward_ratio=0.0,
                )

    rows = [
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=101, low=99, close=100),
    ]
    cerebro = bt.Cerebro()
    cerebro.addstrategy(ShortDisabledStrategy)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    cerebro.run()


def test_stoploss_atr_mult_applies_even_when_cfg_atr_disabled():
    # If ATR is created lazily at enter_trade time, Backtrader won't backfill history,
    # and ATR will be NaN for atrperiod bars => stop won't change.
    # We require ATR to be initialized from __init__ when stoploss_atr_mult != 0.
    class AtrStopStrategy(BaseStrategy):
        params = (
            ("name", "ATR_STOP_MULT_TEST"),
            ("atr", False),  # simulate cfg.atr disabled
            ("atrperiod", 3),
            ("chainer_mode", "LONG_ONLY"),
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
    # key_low=95, ATR(3) should be ~10 => stop should be < 95 when mult=1.0
    assert st.entry_ctx.stoploss_atr_mult == 1.0
    assert st.entry_ctx.initial_stop_price is not None
    assert float(st.entry_ctx.initial_stop_price) < float(st.entry_ctx.key_kline_ref.low)
