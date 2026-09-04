import datetime as dt

import backtrader as bt
import pandas as pd

from trader.strategy.macd_triple_divergence import MacdTripleDivergenceStrategy


def _build_df(rows):
    base = dt.datetime(2024, 1, 1, 0, 0, 0)
    data = []
    for i, r in enumerate(rows):
        data.append(
            dict(
                datetime=base + dt.timedelta(days=i),
                open=float(r["open"]),
                high=float(r["high"]),
                low=float(r["low"]),
                close=float(r["close"]),
                volume=float(r.get("volume", 1.0)),
            )
        )
    return pd.DataFrame(data)


class _DocExecutionProbeStrategy(MacdTripleDivergenceStrategy):
    params = (
        ("macd_stop_enabled", False),
        ("chainer_risk_reward_ratio", 0.0),
    )

    def __init__(self):
        super().__init__()
        self._manual_long_bars = {42: 90.0}
        self._manual_short_bars = {44: 120.0}

    def log_info(self, msg):
        pass

    def log_debug(self, msg):
        pass

    def get_long_signal(self) -> bool:
        bar_idx = self.bar_idx()
        stop_price = self._manual_long_bars.get(bar_idx)
        if stop_price is None:
            return False
        self._long_signal_meta = {
            "suggested_stop_price": stop_price,
            "signal_bar_index": bar_idx,
        }
        return True

    def get_short_signal(self) -> bool:
        bar_idx = self.bar_idx()
        stop_price = self._manual_short_bars.get(bar_idx)
        if stop_price is None:
            return False
        self._short_signal_meta = {
            "suggested_stop_price": stop_price,
            "signal_bar_index": bar_idx,
        }
        return True

    def get_long_signal_context(self) -> dict:
        return dict(self._long_signal_meta or {})

    def get_short_signal_context(self) -> dict:
        return dict(self._short_signal_meta or {})


def _run_doc_probe(rows):
    cerebro = bt.Cerebro()
    cerebro.addstrategy(_DocExecutionProbeStrategy)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    strategies = cerebro.run()
    return strategies[0]


def test_signal_context_preserves_suggested_stop_price_without_overriding_framework_stop():
    rows = [dict(open=100, high=101, low=99, close=100) for _ in range(40)] + [
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=106, low=98, close=105),
        dict(open=112, high=114, low=108, close=110),
        dict(open=109, high=110, low=104, close=106),
        dict(open=95, high=96, low=90, close=92),
    ]
    st = _run_doc_probe(rows)

    closed = [t for t in st._trades_by_id.values() if t.entry_price is not None]  # noqa: SLF001
    assert len(closed) >= 1
    first = closed[0]

    assert abs(float(first.entry_price) - 105.0) < 1e-9
    assert abs(float(first.initial_stop_price) - 98.0) < 1e-9
    assert getattr(first, "signal_metadata", None) == {
        "suggested_stop_price": 90.0,
        "signal_bar_index": 42,
    }


def test_framework_atr_stop_can_diverge_even_when_strategy_suggests_its_own_stop():
    class _AtrCoexistProbe(MacdTripleDivergenceStrategy):
        params = (
            ("chainer_stoploss_atr_mult", 1.0),
            ("chainer_atr_period", 3),
            ("macd_stop_enabled", False),
            ("chainer_risk_reward_ratio", 0.0),
            ("chainer_enable_breakeven", False),
        )

        def __init__(self):
            super().__init__()
            self._long_signal_meta = {}

        def log_info(self, msg):
            pass

        def log_debug(self, msg):
            pass

        def get_long_signal(self) -> bool:
            if self.bar_idx() != 42:
                return False
            self._long_signal_meta = {
                "suggested_stop_price": 90.0,
                "signal_bar_index": self.bar_idx(),
            }
            return True

        def get_short_signal(self) -> bool:
            return False

    rows = [dict(open=100, high=101, low=99, close=100) for _ in range(38)] + [
        dict(open=100, high=103, low=98, close=101),
        dict(open=101, high=104, low=99, close=102),
        dict(open=102, high=104, low=100, close=101),
        dict(open=101, high=103, low=99, close=100),
        dict(open=100, high=106, low=98, close=105),
        dict(open=112, high=114, low=108, close=110),
    ]

    cerebro = bt.Cerebro()
    cerebro.addstrategy(_AtrCoexistProbe)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    st = cerebro.run()[0]

    closed = [t for t in st._trades_by_id.values() if t.entry_price is not None]  # noqa: SLF001
    assert len(closed) == 1
    trade = closed[0]
    assert float(trade.initial_stop_price) != 90.0
    assert float(trade.initial_stop_price) < 98.0
    assert float(trade.signal_metadata["suggested_stop_price"]) == 90.0


def test_next_day_macd_follow_through_rule_matches_document_direction():
    assert MacdTripleDivergenceStrategy._next_day_macd_follow_through_ok("LONG", -100.0, -80.0)
    assert MacdTripleDivergenceStrategy._next_day_macd_follow_through_ok("LONG", -10.0, 5.0)
    assert not MacdTripleDivergenceStrategy._next_day_macd_follow_through_ok("LONG", -50.0, -55.0)

    assert MacdTripleDivergenceStrategy._next_day_macd_follow_through_ok("SHORT", 100.0, 80.0)
    assert MacdTripleDivergenceStrategy._next_day_macd_follow_through_ok("SHORT", 10.0, -5.0)
    assert not MacdTripleDivergenceStrategy._next_day_macd_follow_through_ok("SHORT", 50.0, 55.0)


def test_strategy_private_exit_can_close_trade_without_framework_breakeven_or_tp():
    class _PrivateExitProbe(MacdTripleDivergenceStrategy):
        params = (
            ("macd_stop_enabled", True),
            ("chainer_risk_reward_ratio", 0.0),
            ("chainer_enable_breakeven", False),
        )

        def __init__(self):
            super().__init__()
            self._long_signal_meta = {}

        def log_info(self, msg):
            pass

        def log_debug(self, msg):
            pass

        def get_long_signal(self) -> bool:
            if self.bar_idx() != 42:
                return False
            self._long_signal_meta = {
                "suggested_stop_price": 80.0,
                "signal_bar_index": self.bar_idx(),
            }
            return True

        def get_short_signal(self) -> bool:
            return False

        def _check_macd_stop_loss(self) -> bool:
            return self.bar_idx() == 43

    rows = [dict(open=100, high=101, low=99, close=100) for _ in range(40)] + [
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=106, low=98, close=105),
        dict(open=112, high=114, low=108, close=110),
        dict(open=109, high=110, low=104, close=106),
    ]

    cerebro = bt.Cerebro()
    cerebro.addstrategy(_PrivateExitProbe)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    st = cerebro.run()[0]

    closed = [t for t in st._trades_by_id.values() if t.entry_price is not None]  # noqa: SLF001
    assert len(closed) == 1
    trade = closed[0]
    assert float(trade.initial_stop_price) == 98.0
    assert float(trade.signal_metadata["suggested_stop_price"]) == 80.0
    assert trade.exit_price is not None
    assert float(trade.exit_price) == 110.0
    assert trade.exit_reason_code == "strategy_stop"
    assert trade.exit_reason_label == "策略止损逻辑退出"


def test_framework_stop_remains_active_alongside_strategy_private_exit():
    class _CoexistExitProbe(MacdTripleDivergenceStrategy):
        params = (
            ("macd_stop_enabled", True),
            ("chainer_risk_reward_ratio", 0.0),
            ("chainer_enable_breakeven", False),
        )

        def __init__(self):
            super().__init__()
            self._long_signal_meta = {}

        def log_info(self, msg):
            pass

        def log_debug(self, msg):
            pass

        def get_long_signal(self) -> bool:
            if self.bar_idx() != 42:
                return False
            self._long_signal_meta = {
                "suggested_stop_price": 90.0,
                "signal_bar_index": self.bar_idx(),
            }
            return True

        def get_short_signal(self) -> bool:
            return False

        def _check_macd_stop_loss(self) -> bool:
            return self.bar_idx() >= 44

    rows = [dict(open=100, high=101, low=99, close=100) for _ in range(40)] + [
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=106, low=98, close=105),
        dict(open=112, high=114, low=108, close=110),
        dict(open=109, high=110, low=89, close=106),
        dict(open=95, high=96, low=94, close=95),
    ]

    cerebro = bt.Cerebro()
    cerebro.addstrategy(_CoexistExitProbe)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    st = cerebro.run()[0]

    closed = [t for t in st._trades_by_id.values() if t.entry_price is not None]  # noqa: SLF001
    assert len(closed) == 1
    trade = closed[0]
    assert float(trade.initial_stop_price) == 98.0
    assert float(trade.signal_metadata["suggested_stop_price"]) == 90.0
    assert trade.exit_price is not None
    assert abs(float(trade.exit_price) - 98.0) < 1e-9
    assert trade.exit_reason_code == "framework_stop"
    assert trade.exit_reason_label == "框架止损退出"
    assert float(trade.stop_multiple_r) == -1.0


def test_framework_take_profit_exit_is_recorded_with_risk_reward_reason():
    class _TakeProfitProbe(MacdTripleDivergenceStrategy):
        params = (
            ("macd_stop_enabled", False),
            ("chainer_risk_reward_ratio", 1.0),
            ("chainer_enable_breakeven", False),
        )

        def __init__(self):
            super().__init__()
            self._long_signal_meta = {}

        def log_info(self, msg):
            pass

        def log_debug(self, msg):
            pass

        def get_long_signal(self) -> bool:
            if self.bar_idx() != 42:
                return False
            self._long_signal_meta = {
                "suggested_stop_price": 95.0,
                "signal_bar_index": self.bar_idx(),
            }
            return True

        def get_short_signal(self) -> bool:
            return False

    rows = [dict(open=100, high=101, low=99, close=100) for _ in range(40)] + [
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=106, low=98, close=105),
        dict(open=105, high=110, low=104, close=109),
        dict(open=109, high=116, low=108, close=115),
    ]

    cerebro = bt.Cerebro()
    cerebro.addstrategy(_TakeProfitProbe)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    st = cerebro.run()[0]

    closed = [t for t in st._trades_by_id.values() if t.entry_price is not None]  # noqa: SLF001
    assert len(closed) == 1
    trade = closed[0]
    assert trade.exit_reason_code == "risk_reward_take_profit"
    assert trade.exit_reason_label == "达到预设风险收益比退出"
    assert float(trade.exit_risk_reward_ratio) == 1.0


def test_strategy_immediate_exit_race_is_classified_and_not_unclassified():
    class _ExitRaceProbe(MacdTripleDivergenceStrategy):
        params = (
            ("macd_stop_enabled", True),
            ("chainer_risk_reward_ratio", 1.0),
            ("chainer_enable_breakeven", False),
            ("chainer_stoploss_atr_mult", 0.0),
        )

        def __init__(self):
            super().__init__()
            self._long_signal_meta = {}

        def log_info(self, msg):
            pass

        def log_debug(self, msg):
            pass

        def get_long_signal(self) -> bool:
            if self.bar_idx() != 42:
                return False
            self._long_signal_meta = {
                "suggested_stop_price": 80.0,
                "signal_bar_index": self.bar_idx(),
            }
            return True

        def get_short_signal(self) -> bool:
            return False

        def _check_macd_stop_loss(self) -> bool:
            return self.bar_idx() == 43

    rows = [dict(open=100, high=101, low=99, close=100) for _ in range(40)] + [
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=106, low=98, close=105),
        dict(open=110, high=112, low=108, close=109),
        dict(open=95, high=96, low=90, close=92),
        dict(open=92, high=93, low=91, close=92),
    ]

    cerebro = bt.Cerebro()
    cerebro.addstrategy(_ExitRaceProbe)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    st = cerebro.run()[0]

    closed = [t for t in st._trades_by_id.values() if t.entry_price is not None]  # noqa: SLF001
    assert len(closed) == 1
    trade = closed[0]
    assert trade.exit_reason_code in {"strategy_stop", "framework_stop"}
    assert trade.exit_reason_label in {"策略止损逻辑退出", "框架止损退出"}


def test_long_only_short_signal_does_not_raise_or_open_short_trade():
    class _LongOnlyShortSignalProbe(MacdTripleDivergenceStrategy):
        params = (
            ("chainer_mode", "LONG_ONLY"),
            ("macd_stop_enabled", False),
            ("chainer_risk_reward_ratio", 0.0),
        )

        def __init__(self):
            super().__init__()
            self._short_signal_meta = {}

        def log_info(self, msg):
            pass

        def log_debug(self, msg):
            pass

        def get_long_signal(self) -> bool:
            return False

        def get_short_signal(self) -> bool:
            if self.bar_idx() != 42:
                return False
            self._short_signal_meta = {
                "suggested_stop_price": 120.0,
                "signal_bar_index": self.bar_idx(),
            }
            return True

        def get_short_signal_context(self) -> dict:
            return dict(self._short_signal_meta or {})

    rows = [dict(open=100, high=101, low=99, close=100) for _ in range(45)]

    cerebro = bt.Cerebro()
    cerebro.addstrategy(_LongOnlyShortSignalProbe)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    st = cerebro.run()[0]

    assert st._trades_by_id == {}  # noqa: SLF001
    assert float(getattr(st.position, "size", 0.0)) == 0.0
