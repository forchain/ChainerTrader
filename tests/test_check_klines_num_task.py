from asyncio import Queue
from types import SimpleNamespace

import pytest

from trader.common.config import Config
from trader.common.logger import Logger
from trader.task.check_klines_num_task import CheckKlinesNumTask
from trader.task.task_config import TaskConfig
from trader.task.task_type import TaskType
from trader.utils.kline import Kline
from trader.utils.symbol_interval import Interval, SymbolInterval

BASE = 1_700_000_000 - (1_700_000_000 % 3600)


@pytest.fixture
def anyio_backend():
    return "asyncio"


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


class KlineStore:
    def __init__(self, first: Kline, latest: Kline):
        self.first = first
        self.latest = latest

    async def get_first_kline(self, _name):
        return self.first

    async def get_latest_kline(self, _name):
        return self.latest


def _task(limit: int) -> CheckKlinesNumTask:
    cfg = Config(tasks="[]")
    tcfg = TaskConfig(
        1,
        TaskType.CHECK_KLINES_NUM,
        SymbolInterval("BTC-USDT", Interval.INTERVAL_1h),
        limit=limit,
    )
    latest = make_kline(BASE + 500 * 3600)
    return CheckKlinesNumTask(tcfg, cfg, Logger(cfg), SimpleNamespace(kline=KlineStore(make_kline(BASE), latest)), None)


@pytest.mark.anyio
async def test_limit_zero_checks_back_to_first_available_kline(monkeypatch):
    calls = []

    async def fake_inspect(self, symbol_interval, start_time, end_time):
        calls.append((start_time, end_time))
        return SimpleNamespace(missing_ranges=[], present_count=0, expected_count=0)

    monkeypatch.setattr("trader.task.check_klines_num_task.DatasetResolver.inspect_coverage", fake_inspect)

    task = _task(limit=0)
    await task.start(Queue())

    assert calls == [(BASE, BASE + 500 * 3600)]


@pytest.mark.anyio
async def test_limit_counts_exactly_limit_candles_including_latest(monkeypatch):
    calls = []

    async def fake_inspect(self, symbol_interval, start_time, end_time):
        calls.append((start_time, end_time))
        return SimpleNamespace(missing_ranges=[], present_count=0, expected_count=0)

    monkeypatch.setattr("trader.task.check_klines_num_task.DatasetResolver.inspect_coverage", fake_inspect)

    task = _task(limit=100)
    await task.start(Queue())

    assert calls == [(BASE + 500 * 3600 - 99 * 3600, BASE + 500 * 3600)]
