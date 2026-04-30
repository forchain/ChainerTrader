from types import SimpleNamespace

from backtrader import num2date

from trader.live.feed import LiveKlineDataFeed
from trader.live.market_data import normalize_binance_kline_message
from trader.utils.kline import Kline

BASE = 1_714_281_600


def _kline(open_time=BASE, close=101.0):
    return Kline(open_time, 100.0, 102.0, 99.0, close, open_time + 59, 12.5, 1262.5, 42, 6.0, 606.0)


def _start(feed):
    feed.setenvironment(SimpleNamespace(_tradingcal=None))
    feed._start()


def _update(open_time=BASE, closed=True):
    return normalize_binance_kline_message(
        {
            "e": "kline",
            "E": (open_time + 5) * 1000,
            "s": "BTCUSDT",
            "k": {
                "t": open_time * 1000,
                "T": (open_time + 59) * 1000 + 999,
                "s": "BTCUSDT",
                "i": "1m",
                "o": "100.0",
                "c": "101.0",
                "h": "102.0",
                "l": "99.0",
                "v": "12.5",
                "n": 42,
                "x": closed,
            },
        }
    )


def test_live_kline_feed_declares_live_mode():
    feed = LiveKlineDataFeed()

    assert feed.islive() is True
    assert feed.haslivedata() is False


def test_live_kline_feed_loads_one_closed_kline_into_backtrader_lines():
    feed = LiveKlineDataFeed()
    _start(feed)
    feed.put_kline(_kline())

    assert feed.load() is True
    assert int(num2date(feed.lines.datetime[0]).timestamp()) == BASE
    assert feed.lines.open[0] == 100.0
    assert feed.lines.high[0] == 102.0
    assert feed.lines.low[0] == 99.0
    assert feed.lines.close[0] == 101.0
    assert feed.lines.volume[0] == 12.5


def test_live_kline_feed_returns_none_when_alive_without_data_and_false_after_stop():
    feed = LiveKlineDataFeed(qcheck=0.001)
    _start(feed)

    assert feed.load() is None

    feed.stop()

    assert feed.load() is False


def test_live_kline_feed_accepts_only_unique_closed_updates():
    feed = LiveKlineDataFeed()
    _start(feed)

    assert feed.put_update(_update(closed=False)) is False
    assert feed.put_update(_update(closed=True)) is True
    assert feed.put_update(_update(closed=True)) is False
    assert feed.put_update(_update(open_time=BASE + 60, closed=True)) is True

    assert feed.load() is True
    assert int(num2date(feed.lines.datetime[0]).timestamp()) == BASE
    assert feed.load() is True
    assert int(num2date(feed.lines.datetime[0]).timestamp()) == BASE + 60


def test_live_kline_feed_marks_bars_queued_after_live_marker_as_live_before_marker_is_consumed():
    feed = LiveKlineDataFeed()
    _start(feed)

    assert feed.put_kline(_kline(BASE, close=101.0)) is True
    feed.mark_live()
    assert feed.put_kline(_kline(BASE + 60, close=102.0)) is True

    assert feed.load() is True
    assert feed.current_bar_is_live() is False
    assert feed.load() is True

    assert feed.current_bar_is_live() is True
    assert feed.lines.close[0] == 102.0
