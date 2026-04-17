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


def test_signal_getters_are_evaluated_once_per_bar_even_during_pending_entry_confirmation():
    class _SnapshotProbeStrategy(BaseStrategy):
        params = (
            ("name", "SNAPSHOT_PROBE"),
            ("chainer_auto_signal", True),
            ("chainer_mode", "LONG_ONLY"),
            ("chainer_enter_need_confirm", True),
            ("chainer_exit_need_confirm", True),
        )

        def __init__(self):
            super().__init__()
            self.long_calls = {}
            self.short_calls = {}

        def log_info(self, msg):
            pass

        def log_debug(self, msg):
            pass

        def _tick(self, bucket):
            bar = self.bar_idx()
            bucket[bar] = bucket.get(bar, 0) + 1

        def get_long_signal(self) -> bool:
            self._tick(self.long_calls)
            return self.bar_idx() == 2

        def get_short_signal(self) -> bool:
            self._tick(self.short_calls)
            return self.bar_idx() == 3

    rows = [dict(open=100, high=101, low=99, close=100) for _ in range(5)]

    cerebro = bt.Cerebro()
    cerebro.addstrategy(_SnapshotProbeStrategy)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    st = cerebro.run()[0]

    assert st.long_calls.get(3) == 1
    assert st.short_calls.get(3) == 1


def test_signal_lifecycle_hook_receives_blocked_mode_event():
    class _LifecycleBlockedProbeStrategy(BaseStrategy):
        params = (
            ("name", "LIFECYCLE_BLOCKED_PROBE"),
            ("chainer_auto_signal", True),
            ("chainer_mode", "LONG_ONLY"),
            ("chainer_enter_need_confirm", False),
        )

        def __init__(self):
            super().__init__()
            self.events = []

        def log_info(self, msg):
            pass

        def log_debug(self, msg):
            pass

        def get_long_signal(self) -> bool:
            return False

        def get_short_signal(self) -> bool:
            return self.bar_idx() == 2

        def get_short_signal_context(self) -> dict:
            return {"signal_bar_index": self.bar_idx(), "kind": "short"}

        def on_signal_lifecycle_event(self, event_type, direction, signal_context=None, **payload):
            self.events.append(
                {
                    "event_type": event_type,
                    "direction": direction,
                    "reason": payload.get("reason"),
                    "signal_context": dict(signal_context or {}),
                }
            )

    rows = [dict(open=100, high=101, low=99, close=100) for _ in range(4)]

    cerebro = bt.Cerebro()
    cerebro.addstrategy(_LifecycleBlockedProbeStrategy)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    st = cerebro.run()[0]

    blocked = [event for event in st.events if event["event_type"] == "blocked" and event["direction"] == "SHORT"]
    assert blocked
    assert blocked[0]["reason"] == "mode"


def test_signal_lifecycle_hook_receives_entry_context_created_event():
    class _LifecycleEntryProbeStrategy(BaseStrategy):
        params = (
            ("name", "LIFECYCLE_ENTRY_PROBE"),
            ("chainer_auto_signal", True),
            ("chainer_mode", "LONG_ONLY"),
            ("chainer_enter_need_confirm", False),
        )

        def __init__(self):
            super().__init__()
            self.events = []

        def log_info(self, msg):
            pass

        def log_debug(self, msg):
            pass

        def get_long_signal(self) -> bool:
            return self.bar_idx() == 2

        def get_short_signal(self) -> bool:
            return False

        def get_long_signal_context(self) -> dict:
            return {"signal_bar_index": self.bar_idx(), "kind": "long"}

        def on_signal_lifecycle_event(self, event_type, direction, signal_context=None, **payload):
            self.events.append(
                {
                    "event_type": event_type,
                    "direction": direction,
                    "trade_id": payload.get("trade_id"),
                    "signal_context": dict(signal_context or {}),
                }
            )

    rows = [dict(open=100, high=101, low=99, close=100) for _ in range(4)]

    cerebro = bt.Cerebro()
    cerebro.addstrategy(_LifecycleEntryProbeStrategy)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    st = cerebro.run()[0]

    created = [event for event in st.events if event["event_type"] == "entry_context_created" and event["direction"] == "LONG"]
    assert created
    assert created[0]["trade_id"] is not None


@pytest.mark.parametrize(
    ("mode", "long_bar", "short_bar"),
    [
        ("LONG_ONLY", None, 2),
        ("SHORT_ONLY", 2, None),
    ],
)
def test_one_way_modes_do_not_open_opposite_direction_entries(mode, long_bar, short_bar):
    class _OneWayModeProbeStrategy(BaseStrategy):
        params = (
            ("name", "ONE_WAY_MODE_PROBE"),
            ("chainer_auto_signal", True),
            ("chainer_enter_need_confirm", False),
            ("long_bar", None),
            ("short_bar", None),
        )

        def log_info(self, msg):
            pass

        def log_debug(self, msg):
            pass

        def get_long_signal(self) -> bool:
            return self.p.long_bar is not None and self.bar_idx() == self.p.long_bar

        def get_short_signal(self) -> bool:
            return self.p.short_bar is not None and self.bar_idx() == self.p.short_bar

    rows = [dict(open=100, high=101, low=99, close=100) for _ in range(4)]

    cerebro = bt.Cerebro()
    cerebro.addstrategy(_OneWayModeProbeStrategy, chainer_mode=mode, long_bar=long_bar, short_bar=short_bar)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    st = cerebro.run()[0]

    assert st._trades_by_id == {}  # noqa: SLF001
    assert float(getattr(st.position, "size", 0.0)) == 0.0


def test_both_mode_opens_short_entry_from_short_signal():
    class _BothModeShortProbeStrategy(BaseStrategy):
        params = (
            ("name", "BOTH_MODE_SHORT_PROBE"),
            ("chainer_auto_signal", True),
            ("chainer_mode", "BOTH"),
            ("chainer_enter_need_confirm", False),
        )

        def log_info(self, msg):
            pass

        def log_debug(self, msg):
            pass

        def get_long_signal(self) -> bool:
            return False

        def get_short_signal(self) -> bool:
            return self.bar_idx() == 2

    rows = [dict(open=100, high=101, low=99, close=100) for _ in range(5)]

    cerebro = bt.Cerebro()
    cerebro.addstrategy(_BothModeShortProbeStrategy)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    st = cerebro.run()[0]

    trades = list(st._trades_by_id.values())  # noqa: SLF001
    assert len(trades) == 1
    assert trades[0].direction == "SHORT"
