import asyncio
from asyncio import Event

import pytest

from trader.core.marketdata.use_cases.check_klines import check_kline_count
from trader.core.shared.domain import Interval, Kline, SymbolInterval

BASE = 1_700_000_000 - (1_700_000_000 % 3600)


@pytest.fixture
def anyio_backend():
    return "asyncio"


class DummyLog:
    def info(self, *args, **kwargs):
        pass

    warning = error = debug = info


def make_kline(open_time: int) -> Kline:
    return Kline(
        open_time=open_time,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        close_time=open_time + 3599,
        volume=10,
        vol_quote=20,
        trades=3,
        vol_taker_base=4,
        vol_taker_quote=5,
        ignore=0,
    )


class RecordingKlineStore:
    """Kline repository double that records the candles it was asked for."""

    def __init__(self, klines):
        self.klines = {kline.open_time: kline for kline in klines}
        self.requested_open_times: list[int] = []

    async def get_first_kline(self, _name):
        return self.klines[min(self.klines)] if self.klines else None

    async def get_latest_kline(self, _name):
        return self.klines[max(self.klines)] if self.klines else None

    async def get_kline(self, _name, open_time):
        self.requested_open_times.append(open_time)
        return self.klines.get(open_time)


def _hourly_klines(count: int) -> list[Kline]:
    return [make_kline(BASE + index * 3600) for index in range(count)]


def test_limit_zero_checks_back_to_first_available_kline():
    store = RecordingKlineStore(_hourly_klines(3))

    count = asyncio.run(
        check_kline_count(store, SymbolInterval("BTC-USDT", Interval.INTERVAL_1h), 0, Event(), DummyLog(), "check")
    )

    # The walk-back stops at the first available kline.
    assert count == 1
    assert store.requested_open_times == [BASE + 3600]


def test_limit_counts_at_most_limit_candles_back_from_latest():
    store = RecordingKlineStore(_hourly_klines(5))

    count = asyncio.run(
        check_kline_count(store, SymbolInterval("BTC-USDT", Interval.INTERVAL_1h), 2, Event(), DummyLog(), "check")
    )

    assert count == 2
    assert store.requested_open_times == [BASE + 3 * 3600, BASE + 2 * 3600]
