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
            "stop_price": stop_price,
            "signal_bar_index": bar_idx,
        }
        return True

    def get_short_signal(self) -> bool:
        bar_idx = self.bar_idx()
        stop_price = self._manual_short_bars.get(bar_idx)
        if stop_price is None:
            return False
        self._short_signal_meta = {
            "stop_price": stop_price,
            "signal_bar_index": bar_idx,
        }
        return True


def _run_doc_probe(rows):
    cerebro = bt.Cerebro()
    cerebro.addstrategy(_DocExecutionProbeStrategy)
    data_feed = bt.feeds.PandasData(dataname=_build_df(rows), datetime="datetime")
    cerebro.adddata(data_feed)
    cerebro.broker.setcash(100000.0)
    cerebro.broker.setcommission(commission=0.0)
    strategies = cerebro.run()
    return strategies[0]


def test_doc_trade_logic_enters_on_signal_bar_close_and_uses_signal_stop_price():
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
    assert abs(float(first.initial_stop_price) - 90.0) < 1e-9


def test_next_day_macd_follow_through_rule_matches_document_direction():
    assert MacdTripleDivergenceStrategy._next_day_macd_follow_through_ok("LONG", -100.0, -80.0)
    assert MacdTripleDivergenceStrategy._next_day_macd_follow_through_ok("LONG", -10.0, 5.0)
    assert not MacdTripleDivergenceStrategy._next_day_macd_follow_through_ok("LONG", -50.0, -55.0)

    assert MacdTripleDivergenceStrategy._next_day_macd_follow_through_ok("SHORT", 100.0, 80.0)
    assert MacdTripleDivergenceStrategy._next_day_macd_follow_through_ok("SHORT", 10.0, -5.0)
    assert not MacdTripleDivergenceStrategy._next_day_macd_follow_through_ok("SHORT", 50.0, 55.0)
