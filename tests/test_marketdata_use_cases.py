import asyncio

from trader.core.marketdata.use_cases.check_klines import check_kline_count
from trader.core.marketdata.use_cases.import_csv import import_csv_klines, parse_csv_kline_rows
from trader.core.marketdata.use_cases.update_klines import download_range
from trader.core.shared.domain import Interval, Kline, SymbolInterval


class FakeLog:
    def info(self, *args, **kwargs):
        pass

    warning = error = debug = info


def make_kline(open_time: int) -> Kline:
    return Kline(open_time, 100.0, 101.0, 99.0, 100.5, open_time + 3599, 1.0, 1.0, 1, 1.0, 1.0)


class FakeKlineRepository:
    def __init__(self, klines):
        self.klines = {kline.open_time: kline for kline in klines}
        self.added = []

    async def get_first_kline(self, name):
        return self.klines[min(self.klines)] if self.klines else None

    async def get_latest_kline(self, name):
        return self.klines[max(self.klines)] if self.klines else None

    async def get_kline(self, name, open_time):
        return self.klines.get(open_time)

    async def add_klines(self, name, klines, raw_payloads=None, source="unknown"):
        self.added.extend(klines)
        return len(klines)


class FakeMarketDataClient:
    def __init__(self, klines):
        self.klines = klines

    def get_klines(self, symbol_interval, start_time=None, end_time=None, limit=500):
        return self.klines


def test_check_kline_count_walks_back_from_latest_to_first():
    interval = Interval.INTERVAL_1h
    base = 1_700_000_000
    repository = FakeKlineRepository([make_kline(base), make_kline(base + 3600), make_kline(base + 7200)])

    count = asyncio.run(
        check_kline_count(repository, SymbolInterval("BTC-USDT", interval), 0, asyncio.Event(), FakeLog(), "check")
    )

    assert count == 1


def test_import_csv_klines_uses_repository_port():
    repository = FakeKlineRepository([])
    rows = [
        ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote", "count", "taker", "taker_quote", "ignore"],
        ["1700000000000", "1", "2", "0.5", "1.5", "10", "1700003599999", "20", "3", "4", "5", "0"],
    ]

    klines = parse_csv_kline_rows(rows)
    added = asyncio.run(import_csv_klines(repository, "BTCUSDT-1h", klines))

    assert added == 1
    assert repository.added[0].open_time == 1_700_000_000


def test_download_range_runs_over_explicit_ports_without_db_manager():
    interval = Interval.INTERVAL_1h
    base = 1_700_000_000
    repository = FakeKlineRepository([])
    client = FakeMarketDataClient([make_kline(base)])

    ok = asyncio.run(
        download_range(
            "update",
            FakeLog(),
            repository,
            "BTCUSDT-1h",
            client,
            SymbolInterval("BTC-USDT", interval),
            base,
            base,
            asyncio.Event(),
        )
    )

    assert ok is True
    assert [kline.open_time for kline in repository.added] == [base]
