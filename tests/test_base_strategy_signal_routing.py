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


def test_short_only_long_signal_exits_active_short_trade():
    class _ShortOnlyExitProbeStrategy(BaseStrategy):
        params = (
            ("name", "SHORT_ONLY_EXIT_PROBE"),
            ("chainer_mode", "SHORT_ONLY"),
            ("chainer_need_confirm", False),
            ("chainer_enable_breakeven", False),
            ("chainer_risk_reward_ratio", 0.0),
        )

        def log_info(self, msg):
            pass

        def log_debug(self, msg):
            pass

        def get_long_signal(self) -> bool:
            return self.bar_idx() == 4

        def get_short_signal(self) -> bool:
            return self.bar_idx() == 2

    rows = [
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=110, low=95, close=100),  # short signal, stop=110
        dict(open=100, high=105, low=94, close=96),  # short entry fills
        dict(open=96, high=104, low=93, close=95),  # long signal requests exit
        dict(open=95, high=96, low=92, close=94),  # exit fills
    ]

    cerebro = bt.Cerebro()
    cerebro.addstrategy(_ShortOnlyExitProbeStrategy)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    st = cerebro.run()[0]

    trades = list(st._trades_by_id.values())  # noqa: SLF001
    assert len(trades) == 1
    assert trades[0].direction == "SHORT"
    assert trades[0].status == BaseStrategy.TradeStatus.CLOSED
    assert trades[0].exit_reason_code == "signal_exit"


def test_both_mode_reverse_signal_force_closes_active_trade_before_opening_replacement():
    class _BothModeReverseSignalProbeStrategy(BaseStrategy):
        params = (
            ("name", "BOTH_MODE_REVERSE_SIGNAL_PROBE"),
            ("chainer_mode", "BOTH"),
            ("chainer_need_confirm", False),
            ("chainer_enable_breakeven", False),
            ("chainer_risk_reward_ratio", 0.0),
        )

        def log_info(self, msg):
            pass

        def log_debug(self, msg):
            pass

        def __init__(self):
            super().__init__()
            self.completed_exit_trade_ids = []

        def notify_order(self, order):
            role = getattr(order, "info", {}).get("chainer_role")
            if order.status == order.Completed and role in {"exit", "stop", "take_profit"}:
                self.completed_exit_trade_ids.append(int(order.tradeid))
            super().notify_order(order)

        def get_long_signal(self) -> bool:
            return self.bar_idx() == 2

        def get_short_signal(self) -> bool:
            return self.bar_idx() == 4

    rows = [
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=101, low=99, close=100),
        dict(open=100, high=105, low=90, close=104),  # long signal, stop=90
        dict(open=104, high=106, low=100, close=105),  # long entry fills
        dict(open=105, high=107, low=100, close=103),  # short signal replaces the long
        dict(open=103, high=104, low=99, close=102),  # long exit fills
        dict(open=102, high=104, low=98, close=100),  # replacement short entry fills
        dict(open=100, high=103, low=97, close=99),
    ]

    cerebro = bt.Cerebro()
    cerebro.addstrategy(_BothModeReverseSignalProbeStrategy)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    st = cerebro.run()[0]

    trades = list(st._trades_by_id.values())  # noqa: SLF001
    assert len(trades) == 2
    assert trades[0].direction == "LONG"
    assert trades[0].status == BaseStrategy.TradeStatus.CLOSED
    assert trades[0].exit_reason_code == "signal_replaced"
    assert trades[0].exit_reason_label == "新交易信号强制平仓"
    assert trades[0].replacement_trade_id == trades[1].trade_id
    assert f"replacement_trade_id={trades[1].trade_id}" in trades[0].exit_reason_detail
    assert trades[1].direction == "SHORT"
    assert trades[1].status == BaseStrategy.TradeStatus.ACTIVE
    assert trades[1].trade_id == 2
    assert st.completed_exit_trade_ids == [trades[0].trade_id]
    assert float(getattr(st.position, "size", 0.0)) < 0.0
