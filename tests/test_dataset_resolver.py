import asyncio
import csv
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _ensure_pymongo_stub():
    if "pymongo" in sys.modules:
        return

    pymongo_module = ModuleType("pymongo")
    pymongo_module.MongoClient = object
    pymongo_module.ASCENDING = 1
    pymongo_module.DESCENDING = -1
    sys.modules["pymongo"] = pymongo_module

    pymongo_synchronous = ModuleType("pymongo.synchronous")
    sys.modules["pymongo.synchronous"] = pymongo_synchronous

    collection_module = ModuleType("pymongo.synchronous.collection")
    collection_module.Collection = object
    sys.modules["pymongo.synchronous.collection"] = collection_module


def _ensure_binance_exchange_stub():
    module_name = "trader.exchange.binance.exchange"
    if module_name in sys.modules:
        return

    binance_module = ModuleType(module_name)
    binance_module.BinanceExchange = object
    binance_module.KLINE_LIMIT_MAX = 1000
    binance_module.get_oldest_time = lambda: None
    sys.modules[module_name] = binance_module


_ensure_pymongo_stub()
_ensure_binance_exchange_stub()

from trader.task.dataset_resolver import DatasetResolver  # noqa: E402
from trader.utils.kline import Kline  # noqa: E402
from trader.utils.symbol_interval import Interval, SymbolInterval  # noqa: E402


class DummyLog:
    def __init__(self):
        self.messages = []

    def info(self, *args, **kwargs):
        self.messages.append(" ".join(str(arg) for arg in args))

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass


def make_kline(open_time: int, price: float = 100.0) -> Kline:
    return Kline(
        open_time=open_time,
        open=price,
        high=price + 1,
        low=price - 1,
        close=price + 0.5,
        close_time=open_time + 3599,
        volume=10,
        vol_quote=20,
        trades=3,
        vol_taker_base=4,
        vol_taker_quote=5,
        ignore=0,
    )


def test_cache_range_does_not_extend_current_day_into_future_candles(monkeypatch):
    resolver = DatasetResolver(db_manager=None, exchange=None, log=DummyLog())
    start_time = 1_700_000_000
    end_time = start_time + 5 * 3600 + 17 * 60
    monkeypatch.setattr("trader.task.dataset_resolver.time.time", lambda: end_time)

    _, cache_end = resolver._cache_range(SymbolInterval("BTC-USDT", Interval.INTERVAL_1h), start_time, end_time)

    assert cache_end == end_time - (end_time % 3600)


def test_prepare_uses_db_and_materializes_cache_without_downloading(tmp_path: Path):
    async def _test():
        start_time = 1_700_000_000
        start_time = start_time - (start_time % 86400)
        end_time = start_time + 2 * 86400
        bars = [
            make_kline(start_time, 100.0),
            make_kline(start_time + 86400, 101.0),
            make_kline(end_time, 102.0),
        ]
        kline_store = SimpleNamespace(get_klines=AsyncMock(return_value=bars))
        db_manager = SimpleNamespace(kline=kline_store)

        async def downloader(*args, **kwargs):
            raise AssertionError("downloader should not be called")

        resolver = DatasetResolver(
            db_manager=db_manager,
            exchange=SimpleNamespace(),
            log=DummyLog(),
            cache_dir=tmp_path,
            range_downloader=downloader,
        )

        result = await resolver.prepare(SymbolInterval("BTC-USDT", Interval.INTERVAL_1d), start_time, end_time)

        assert result.ok is True
        assert result.dataset_ref.start_time == start_time
        assert result.dataset_ref.end_time == end_time
        assert Path(result.dataset_ref.path).exists()
        assert kline_store.get_klines.call_count == 1

        with open(result.dataset_ref.path, "r", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))

        assert len(rows) == 3
        assert rows[0][0] == str(start_time * 1000)

    asyncio.run(_test())


def test_materialize_cache_leaves_no_tmp_staging_file(tmp_path: Path):
    resolver = DatasetResolver(
        db_manager=None,
        exchange=None,
        log=DummyLog(),
        cache_dir=tmp_path,
        range_downloader=None,
    )
    out = tmp_path / "bucket.csv"
    bars = [make_kline(1_700_000_000)]
    resolver._materialize_cache(out, bars)
    assert out.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_materialize_cache_removes_tmp_when_replace_fails(tmp_path: Path, monkeypatch):
    resolver = DatasetResolver(
        db_manager=None,
        exchange=None,
        log=DummyLog(),
        cache_dir=tmp_path,
        range_downloader=None,
    )
    out = tmp_path / "bucket.csv"
    bars = [make_kline(1_700_000_000)]

    real_replace = Path.replace

    def boom(self, target):
        if str(target) == str(out):
            raise OSError("simulated replace failure")
        return real_replace(self, target)

    monkeypatch.setattr(Path, "replace", boom)
    with pytest.raises(OSError, match="simulated replace failure"):
        resolver._materialize_cache(out, bars)
    assert not out.exists()
    assert list(tmp_path.glob("*.tmp")) == []


def test_prepare_does_not_download_internal_source_gap_inside_cached_range(tmp_path: Path):
    async def _test():
        start_time = 1_700_000_000
        start_time = start_time - (start_time % 86400)
        end_time = start_time + 2 * 86400
        source_gap_bars = [
            make_kline(start_time, 100.0),
            make_kline(end_time, 102.0),
        ]
        kline_store = SimpleNamespace(get_klines=AsyncMock(return_value=source_gap_bars))
        availability_store = SimpleNamespace(
            get_earliest_known_open_time=AsyncMock(return_value=None),
            get_cached_open_time_range=AsyncMock(return_value=(start_time, end_time)),
            update_cached_open_time_range=AsyncMock(),
        )

        async def downloader(*args, **kwargs):
            raise AssertionError("downloader should not be called for source gaps inside cached coverage")

        resolver = DatasetResolver(
            db_manager=SimpleNamespace(kline=kline_store, availability=availability_store),
            exchange=SimpleNamespace(name=lambda: "BINANCE"),
            log=DummyLog(),
            cache_dir=tmp_path,
            range_downloader=downloader,
        )

        result = await resolver.prepare(SymbolInterval("BTC-USDT", Interval.INTERVAL_1d), start_time, end_time)

        assert result.ok is True
        assert kline_store.get_klines.call_count == 1
        availability_store.update_cached_open_time_range.assert_not_called()

    asyncio.run(_test())


def test_prepare_redownloads_when_cached_range_has_no_persisted_klines(tmp_path: Path):
    async def _test():
        start_time = 1_700_000_000
        start_time = start_time - (start_time % 86400)
        end_time = start_time + 2 * 86400
        downloaded_bars = [
            make_kline(start_time, 100.0),
            make_kline(start_time + 86400, 101.0),
            make_kline(end_time, 102.0),
        ]
        kline_store = SimpleNamespace(get_klines=AsyncMock(side_effect=[[], downloaded_bars]))
        availability_store = SimpleNamespace(
            get_earliest_known_open_time=AsyncMock(return_value=None),
            get_cached_open_time_range=AsyncMock(return_value=(start_time, end_time)),
            update_cached_open_time_range=AsyncMock(),
        )
        requested_ranges = []

        async def downloader(name, log, db_manager_arg, collection_name, exchange, symbol_interval, range_start, range_end, quit_event):
            requested_ranges.append((collection_name, range_start, range_end))
            return True

        resolver = DatasetResolver(
            db_manager=SimpleNamespace(kline=kline_store, availability=availability_store),
            exchange=SimpleNamespace(name=lambda: "BINANCE"),
            log=DummyLog(),
            cache_dir=tmp_path,
            range_downloader=downloader,
        )

        result = await resolver.prepare(SymbolInterval("BTC-USDT", Interval.INTERVAL_1d), start_time, end_time)

        assert result.ok is True
        assert requested_ranges == [("BTCUSDT-1d", start_time, end_time)]
        availability_store.update_cached_open_time_range.assert_awaited_once_with(
            "BINANCE",
            "BTCUSDT",
            "1d",
            start_time,
            end_time,
            source="dataset_resolver",
        )

    asyncio.run(_test())


def test_prepare_downloads_only_outside_cached_range_and_updates_cache_coverage(tmp_path: Path):
    async def _test():
        start_time = 1_700_000_000
        start_time = start_time - (start_time % 86400)
        cached_start = start_time + 86400
        cached_end = start_time + 2 * 86400
        end_time = start_time + 3 * 86400
        bars_after_download = [
            make_kline(start_time, 99.0),
            make_kline(cached_start, 100.0),
            make_kline(cached_end, 101.0),
            make_kline(end_time, 102.0),
        ]
        kline_store = SimpleNamespace(get_klines=AsyncMock(side_effect=[bars_after_download, bars_after_download]))
        availability_store = SimpleNamespace(
            get_earliest_known_open_time=AsyncMock(return_value=None),
            get_cached_open_time_range=AsyncMock(return_value=(cached_start, cached_end)),
            update_cached_open_time_range=AsyncMock(),
        )
        requested_ranges = []

        async def downloader(name, log, db_manager_arg, collection_name, exchange, symbol_interval, range_start, range_end, quit_event):
            requested_ranges.append((collection_name, range_start, range_end))
            return True

        resolver = DatasetResolver(
            db_manager=SimpleNamespace(kline=kline_store, availability=availability_store),
            exchange=SimpleNamespace(name=lambda: "BINANCE"),
            log=DummyLog(),
            cache_dir=tmp_path,
            range_downloader=downloader,
        )

        result = await resolver.prepare(SymbolInterval("BTC-USDT", Interval.INTERVAL_1d), start_time, end_time)

        assert result.ok is True
        assert requested_ranges == [
            ("BTCUSDT-1d", start_time, start_time),
            ("BTCUSDT-1d", end_time, end_time),
        ]
        availability_store.update_cached_open_time_range.assert_awaited_once_with(
            "BINANCE",
            "BTCUSDT",
            "1d",
            start_time,
            end_time,
            source="dataset_resolver",
        )

    asyncio.run(_test())



def test_prepare_repairs_internal_gap_without_downloading(tmp_path: Path):
    async def _test():
        start_time = 1_700_000_000
        start_time = start_time - (start_time % 86400)
        end_time = start_time + 2 * 86400
        initial_bars = [
            make_kline(start_time, 100.0),
            make_kline(end_time, 102.0),
        ]
        full_bars = [
            make_kline(start_time, 100.0),
            make_kline(start_time + 86400, 101.0),
            make_kline(end_time, 102.0),
        ]
        kline_store = SimpleNamespace(get_klines=AsyncMock(side_effect=[initial_bars, full_bars]))
        db_manager = SimpleNamespace(kline=kline_store)
        requested_ranges = []

        async def downloader(name, log, db_manager_arg, collection_name, exchange, symbol_interval, range_start, range_end, quit_event):
            requested_ranges.append((collection_name, range_start, range_end))
            return True

        resolver = DatasetResolver(
            db_manager=db_manager,
            exchange=SimpleNamespace(),
            log=DummyLog(),
            cache_dir=tmp_path,
            range_downloader=downloader,
        )

        result = await resolver.prepare(SymbolInterval("BTC-USDT", Interval.INTERVAL_1d), start_time, end_time)

        assert result.ok is True
        assert requested_ranges == [("BTCUSDT-1d", start_time + 86400, start_time + 86400)]
        assert kline_store.get_klines.call_count == 2

    asyncio.run(_test())


def test_prepare_allows_incomplete_coverage_when_enabled(tmp_path: Path):
    async def _test():
        start_time = 1_700_000_000
        start_time = start_time - (start_time % 86400)
        end_time = start_time + 2 * 86400
        initial_bars = [
            make_kline(start_time, 100.0),
            make_kline(end_time, 102.0),
        ]
        missing_bar_open = start_time + 86400
        full_bars = [
            make_kline(start_time, 100.0),
            make_kline(missing_bar_open, 101.0),
            make_kline(end_time, 102.0),
        ]
        kline_store = SimpleNamespace(get_klines=AsyncMock(side_effect=[initial_bars, full_bars]))
        db_manager = SimpleNamespace(kline=kline_store)
        requested_ranges = []

        async def downloader(name, log, db_manager_arg, collection_name, exchange, symbol_interval, range_start, range_end, quit_event):
            requested_ranges.append((collection_name, range_start, range_end))
            return True

        resolver = DatasetResolver(
            db_manager=db_manager,
            exchange=SimpleNamespace(),
            log=DummyLog(),
            cache_dir=tmp_path,
            range_downloader=downloader,
        )

        result = await resolver.prepare(
            SymbolInterval("BTC-USDT", Interval.INTERVAL_1d),
            start_time,
            end_time,
            allow_incomplete_coverage=True,
        )

        assert result.ok is True
        assert requested_ranges == [("BTCUSDT-1d", start_time + 86400, start_time + 86400)]
        assert kline_store.get_klines.call_count == 2

    asyncio.run(_test())


def test_prepare_allows_incomplete_coverage_when_downloading_disabled(tmp_path: Path):
    async def _test():
        start_time = 1_700_000_000
        end_time = start_time + 3 * 3600
        bars = [
            make_kline(start_time + 3600, 101.0),
            make_kline(start_time + 2 * 3600, 102.0),
        ]
        kline_store = SimpleNamespace(get_klines=AsyncMock(return_value=bars))

        async def downloader(*args, **kwargs):
            raise AssertionError("downloader should not be called when allow_download is False")

        resolver = DatasetResolver(
            db_manager=SimpleNamespace(kline=kline_store),
            exchange=SimpleNamespace(),
            log=DummyLog(),
            cache_dir=tmp_path,
            range_downloader=downloader,
        )

        result = await resolver.prepare(
            SymbolInterval("BTC-USDT", Interval.INTERVAL_1h),
            start_time,
            end_time,
            allow_download=False,
            allow_incomplete_coverage=True,
        )

        assert result.ok is True
        assert kline_store.get_klines.call_count == 1

    asyncio.run(_test())


def test_prepare_refreshes_disk_cache_when_db_returns_more_rows_than_csv(tmp_path: Path):
    async def _test():
        start_time = 1_700_000_000
        start_time = start_time - (start_time % 86400)
        end_time = start_time + 23 * 3600
        partial_bars = [make_kline(start_time, 100.0)]
        full_bars = [
            make_kline(start_time, 100.0),
            make_kline(start_time + 3600, 101.0),
            make_kline(end_time, 102.0),
        ]
        sym = SymbolInterval("BTC-USDT", Interval.INTERVAL_1h)

        kline_store_1 = SimpleNamespace(get_klines=AsyncMock(return_value=partial_bars))

        async def reject_download(*args, **kwargs):
            raise AssertionError("downloader should not run in first prepare")

        resolver1 = DatasetResolver(
            db_manager=SimpleNamespace(kline=kline_store_1),
            exchange=SimpleNamespace(),
            log=DummyLog(),
            cache_dir=tmp_path,
            range_downloader=reject_download,
        )
        first = await resolver1.prepare(sym, start_time, end_time, allow_download=False, allow_incomplete_coverage=True)
        assert first.ok is True
        csv_path = Path(first.dataset_ref.path)
        assert csv_path.exists()
        with csv_path.open(encoding="utf-8") as handle:
            row_count_after_first = sum(1 for _ in csv.reader(handle))
        assert row_count_after_first == 1

        kline_store_2 = SimpleNamespace(get_klines=AsyncMock(return_value=full_bars))
        resolver2 = DatasetResolver(
            db_manager=SimpleNamespace(kline=kline_store_2),
            exchange=SimpleNamespace(),
            log=DummyLog(),
            cache_dir=tmp_path,
            range_downloader=reject_download,
        )
        second = await resolver2.prepare(sym, start_time, end_time, allow_download=False, allow_incomplete_coverage=True)
        assert second.ok is True
        with csv_path.open(encoding="utf-8") as handle:
            row_count_after_second = sum(1 for _ in csv.reader(handle))
        assert row_count_after_second == 3
        assert kline_store_2.get_klines.await_count >= 1

    asyncio.run(_test())


def test_prepare_reuses_same_dataset_ref_for_duplicate_requests(tmp_path: Path):
    async def _test():
        start_time = 1_700_000_000
        start_time = start_time - (start_time % 86400)
        end_time = start_time + 2 * 86400
        bars = [
            make_kline(start_time, 100.0),
            make_kline(start_time + 86400, 101.0),
            make_kline(end_time, 102.0),
        ]
        kline_store = SimpleNamespace(get_klines=AsyncMock(return_value=bars))
        db_manager = SimpleNamespace(kline=kline_store)

        resolver = DatasetResolver(
            db_manager=db_manager,
            exchange=SimpleNamespace(),
            log=DummyLog(),
            cache_dir=tmp_path,
        )
        symbol_interval = SymbolInterval("BTC-USDT", Interval.INTERVAL_1d)

        first = await resolver.prepare(symbol_interval, start_time, end_time)
        second = await resolver.prepare(symbol_interval, start_time, end_time)

        assert first.ok is True
        assert second.ok is True
        assert first.dataset_ref.path == second.dataset_ref.path
        assert kline_store.get_klines.call_count == 1

    asyncio.run(_test())


def test_prepare_hits_cache_when_end_time_differs_within_same_bar(tmp_path: Path):
    async def _test():
        start_time = 1_700_000_000
        start_time = start_time - (start_time % 86400)
        requested_end_1 = start_time + 2 * 3600 + 13
        requested_end_2 = start_time + 22 * 3600 + 59
        bars = [make_kline(start_time + i * 3600, 100.0 + i) for i in range(24)]
        kline_store = SimpleNamespace(get_klines=AsyncMock(return_value=bars))

        resolver = DatasetResolver(
            db_manager=SimpleNamespace(kline=kline_store),
            exchange=SimpleNamespace(),
            log=DummyLog(),
            cache_dir=tmp_path,
        )

        first = await resolver.prepare(SymbolInterval("BTC-USDT", Interval.INTERVAL_1h), start_time, requested_end_1)
        assert first.ok is True
        assert Path(first.dataset_ref.path).exists()
        assert kline_store.get_klines.call_count == 1

        resolver2 = DatasetResolver(
            db_manager=SimpleNamespace(kline=kline_store),
            exchange=SimpleNamespace(),
            log=DummyLog(),
            cache_dir=tmp_path,
        )
        second = await resolver2.prepare(SymbolInterval("BTC-USDT", Interval.INTERVAL_1h), start_time, requested_end_2)
        assert second.ok is True
        assert second.cache_hit is True
        assert kline_store.get_klines.call_count == 2

    asyncio.run(_test())


def test_prepare_skips_leading_gap_before_first_available_kline(tmp_path: Path):
    async def _test():
        requested_start = 1_700_000_000
        requested_start = requested_start - (requested_start % 86400)
        listed_start = requested_start + 3 * 3600
        end_time = requested_start + 23 * 3600
        bars = [
            make_kline(listed_start, 100.0),
            make_kline(listed_start + 3600, 101.0),
            make_kline(listed_start + 2 * 3600, 102.0),
            make_kline(listed_start + 3 * 3600, 103.0),
            make_kline(listed_start + 4 * 3600, 104.0),
            make_kline(listed_start + 5 * 3600, 105.0),
            make_kline(listed_start + 6 * 3600, 106.0),
            make_kline(listed_start + 7 * 3600, 107.0),
            make_kline(listed_start + 8 * 3600, 108.0),
            make_kline(listed_start + 9 * 3600, 109.0),
            make_kline(listed_start + 10 * 3600, 110.0),
            make_kline(listed_start + 11 * 3600, 111.0),
            make_kline(listed_start + 12 * 3600, 112.0),
            make_kline(listed_start + 13 * 3600, 113.0),
            make_kline(listed_start + 14 * 3600, 114.0),
            make_kline(listed_start + 15 * 3600, 115.0),
            make_kline(listed_start + 16 * 3600, 116.0),
            make_kline(listed_start + 17 * 3600, 117.0),
            make_kline(listed_start + 18 * 3600, 118.0),
            make_kline(listed_start + 19 * 3600, 119.0),
            make_kline(listed_start + 20 * 3600, 120.0),
            make_kline(listed_start + 21 * 3600, 121.0),
            make_kline(listed_start + 22 * 3600, 122.0),
            make_kline(end_time, 102.0),
        ]
        kline_store = SimpleNamespace(
            get_klines=AsyncMock(return_value=bars),
        )
        availability_store = SimpleNamespace(
            get_earliest_known_open_time=AsyncMock(return_value=listed_start),
        )

        async def downloader(*args, **kwargs):
            raise AssertionError("downloader should not be called for pre-listing gap")

        resolver = DatasetResolver(
            db_manager=SimpleNamespace(kline=kline_store, availability=availability_store),
            exchange=SimpleNamespace(),
            log=DummyLog(),
            cache_dir=tmp_path,
            range_downloader=downloader,
        )

        result = await resolver.prepare(SymbolInterval("BTC-USDT", Interval.INTERVAL_1h), requested_start, end_time)

        assert result.ok is True
        assert kline_store.get_klines.call_count == 1
        assert availability_store.get_earliest_known_open_time.call_count == 1

    asyncio.run(_test())


def test_prepare_clamps_requested_start_to_recorded_first_available_kline(tmp_path: Path):
    async def _test():
        requested_start = 1_700_000_000
        requested_start = requested_start - (requested_start % 86400)
        listed_start = requested_start + 3 * 3600
        end_time = requested_start + 23 * 3600
        bars = [
            make_kline(listed_start, 100.0),
            make_kline(listed_start + 3600, 101.0),
            make_kline(listed_start + 2 * 3600, 102.0),
            make_kline(listed_start + 3 * 3600, 103.0),
            make_kline(listed_start + 4 * 3600, 104.0),
            make_kline(listed_start + 5 * 3600, 105.0),
            make_kline(listed_start + 6 * 3600, 106.0),
            make_kline(listed_start + 7 * 3600, 107.0),
            make_kline(listed_start + 8 * 3600, 108.0),
            make_kline(listed_start + 9 * 3600, 109.0),
            make_kline(listed_start + 10 * 3600, 110.0),
            make_kline(listed_start + 11 * 3600, 111.0),
            make_kline(listed_start + 12 * 3600, 112.0),
            make_kline(listed_start + 13 * 3600, 113.0),
            make_kline(listed_start + 14 * 3600, 114.0),
            make_kline(listed_start + 15 * 3600, 115.0),
            make_kline(listed_start + 16 * 3600, 116.0),
            make_kline(listed_start + 17 * 3600, 117.0),
            make_kline(listed_start + 18 * 3600, 118.0),
            make_kline(listed_start + 19 * 3600, 119.0),
            make_kline(listed_start + 20 * 3600, 120.0),
            make_kline(listed_start + 21 * 3600, 121.0),
            make_kline(listed_start + 22 * 3600, 122.0),
            make_kline(end_time, 102.0),
        ]
        kline_store = SimpleNamespace(get_klines=AsyncMock(return_value=bars))

        class AvailabilityStore:
            def __init__(self):
                self.calls = []

            async def get_earliest_known_open_time(self, exchange, symbol, interval):
                self.calls.append((exchange, symbol, interval))
                return listed_start

        availability_store = AvailabilityStore()

        async def downloader(*args, **kwargs):
            raise AssertionError("downloader should not be called before recorded first available kline")

        log = DummyLog()
        resolver = DatasetResolver(
            db_manager=SimpleNamespace(kline=kline_store, availability=availability_store),
            exchange=SimpleNamespace(name=lambda: "BINANCE"),
            log=log,
            cache_dir=tmp_path,
            range_downloader=downloader,
        )

        result = await resolver.prepare(SymbolInterval("BTC-USDT", Interval.INTERVAL_1h), requested_start, end_time)

        assert result.ok is True
        assert result.dataset_ref.start_time == listed_start
        assert kline_store.get_klines.call_args.args == ("BTCUSDT-1h", listed_start, end_time)
        assert availability_store.calls == [("BINANCE", "BTCUSDT", "1h")]
        assert any("update dataset start_time to first available kline" in message for message in log.messages)

    asyncio.run(_test())


def test_prepare_does_not_download_when_requested_range_is_before_recorded_first_available(tmp_path: Path):
    async def _test():
        requested_start = 1_700_000_000
        requested_end = requested_start + 2 * 3600
        listed_start = requested_end + 3600
        kline_store = SimpleNamespace(get_klines=AsyncMock())

        class AvailabilityStore:
            async def get_earliest_known_open_time(self, exchange, symbol, interval):
                return listed_start

        async def downloader(*args, **kwargs):
            raise AssertionError("downloader should not be called when recorded boundary is after request end")

        resolver = DatasetResolver(
            db_manager=SimpleNamespace(kline=kline_store, availability=AvailabilityStore()),
            exchange=SimpleNamespace(name=lambda: "BINANCE"),
            log=DummyLog(),
            cache_dir=tmp_path,
            range_downloader=downloader,
        )

        result = await resolver.prepare(SymbolInterval("BTC-USDT", Interval.INTERVAL_1h), requested_start, requested_end)

        assert result.ok is False
        assert result.failure.reason == "no_data"
        kline_store.get_klines.assert_not_called()

    asyncio.run(_test())


def test_prepare_repairs_trailing_edge_gap_only(tmp_path: Path):
    async def _test():
        start_time = 1_700_000_000
        start_time = start_time - (start_time % 86400)
        mid_time = start_time + 86400
        end_time = start_time + 2 * 86400
        initial_bars = [
            make_kline(start_time, 100.0),
            make_kline(mid_time, 101.0),
        ]
        full_bars = [
            make_kline(start_time, 100.0),
            make_kline(mid_time, 101.0),
            make_kline(mid_time + 86400, 102.0),
            make_kline(end_time, 103.0),
        ]
        requested_ranges = []
        kline_store = SimpleNamespace(get_klines=AsyncMock(side_effect=[initial_bars, full_bars]))

        async def downloader(name, log, db_manager_arg, collection_name, exchange, symbol_interval, range_start, range_end, quit_event):
            requested_ranges.append((collection_name, range_start, range_end))
            return True

        resolver = DatasetResolver(
            db_manager=SimpleNamespace(kline=kline_store),
            exchange=SimpleNamespace(),
            log=DummyLog(),
            cache_dir=tmp_path,
            range_downloader=downloader,
        )

        result = await resolver.prepare(SymbolInterval("BTC-USDT", Interval.INTERVAL_1d), start_time, end_time)

        assert result.ok is True
        assert requested_ranges == [("BTCUSDT-1d", mid_time + 86400, end_time)]
        assert kline_store.get_klines.call_count == 2

    asyncio.run(_test())


def test_aligned_expected_range_falls_back_when_reference_is_after_end(tmp_path: Path):
    resolver = DatasetResolver(
        db_manager=SimpleNamespace(kline=SimpleNamespace(get_klines=AsyncMock(return_value=[]))),
        exchange=SimpleNamespace(),
        log=DummyLog(),
        cache_dir=tmp_path,
    )
    start_time = 1_700_000_000
    end_time = start_time + 10 * 3600
    step = 3600
    aligned = resolver._aligned_expected_range(start_time, end_time, step, reference_open_time=end_time + step)
    assert aligned == (start_time, end_time)


def test_prepare_downloads_earlier_range_when_no_availability_metadata_exists(tmp_path: Path):
    async def _test():
        requested_start = 1_700_000_000
        requested_start = requested_start - (requested_start % 86400)
        known_start = requested_start + 86400
        end_time = requested_start + 2 * 86400
        partial_bars = [
            make_kline(known_start, 100.0),
            make_kline(known_start + 86400, 101.0),
            make_kline(end_time, 102.0),
        ]
        full_bars = [
            make_kline(requested_start, 97.0),
            make_kline(requested_start + 86400, 98.0),
            *partial_bars,
        ]
        requested_ranges = []
        kline_store = SimpleNamespace(get_klines=AsyncMock(side_effect=[partial_bars, full_bars]))
        availability_store = SimpleNamespace(
            get_earliest_known_open_time=AsyncMock(return_value=None),
            get_cached_open_time_range=AsyncMock(return_value=None),
            update_cached_open_time_range=AsyncMock(),
        )

        async def downloader(name, log, db_manager_arg, collection_name, exchange, symbol_interval, range_start, range_end, quit_event):
            requested_ranges.append((collection_name, range_start, range_end))
            return True

        resolver = DatasetResolver(
            db_manager=SimpleNamespace(kline=kline_store, availability=availability_store),
            exchange=SimpleNamespace(),
            log=DummyLog(),
            cache_dir=tmp_path,
            range_downloader=downloader,
        )

        result = await resolver.prepare(SymbolInterval("BTC-USDT", Interval.INTERVAL_1d), requested_start, end_time)

        assert result.ok is True
        assert requested_ranges == [("BTCUSDT-1d", requested_start, end_time)]
        assert availability_store.get_earliest_known_open_time.call_count == 2
        availability_store.update_cached_open_time_range.assert_awaited_once_with(
            "UNKNOWN",
            "BTCUSDT",
            "1d",
            requested_start,
            end_time,
            source="dataset_resolver",
        )

    asyncio.run(_test())


def test_prepare_clamps_missing_download_to_binance_daily_archive_start(tmp_path: Path):
    async def _test():
        requested_start = 1_600_000_000 - (1_600_000_000 % 86400)
        archive_start = 1_700_000_000 - (1_700_000_000 % 86400)
        end_time = archive_start + 2 * 86400
        bars = [make_kline(archive_start), make_kline(archive_start + 86400), make_kline(end_time)]
        requested_ranges = []
        kline_store = SimpleNamespace(get_klines=AsyncMock(side_effect=[[], bars]))
        availability_store = SimpleNamespace(get_earliest_known_open_time=AsyncMock(side_effect=[None, None]))
        exchange = SimpleNamespace(
            get_earliest_daily_archive_open_time=lambda symbol_interval: archive_start,
        )

        async def downloader(name, log, db_manager_arg, collection_name, exchange_arg, symbol_interval, range_start, range_end, quit_event):
            requested_ranges.append((collection_name, range_start, range_end))
            return True

        resolver = DatasetResolver(
            db_manager=SimpleNamespace(kline=kline_store, availability=availability_store),
            exchange=exchange,
            log=DummyLog(),
            cache_dir=tmp_path,
            range_downloader=downloader,
        )

        result = await resolver.prepare(SymbolInterval("BTC-USDT", Interval.INTERVAL_1d), requested_start, end_time)

        assert result.ok is True
        assert requested_ranges == [("BTCUSDT-1d", archive_start, end_time)]

    asyncio.run(_test())


def test_prepare_returns_no_data_without_downloading_when_request_ends_before_binance_daily_archive_start(tmp_path: Path):
    async def _test():
        requested_start = 1_600_000_000 - (1_600_000_000 % 86400)
        requested_end = requested_start + 86400
        archive_start = requested_end + 86400
        kline_store = SimpleNamespace(get_klines=AsyncMock())
        availability_store = SimpleNamespace(get_earliest_known_open_time=AsyncMock(return_value=None))
        exchange = SimpleNamespace(
            get_earliest_daily_archive_open_time=lambda symbol_interval: archive_start,
        )

        async def downloader(*args, **kwargs):
            raise AssertionError("downloader must not run before the archive start")

        resolver = DatasetResolver(
            db_manager=SimpleNamespace(kline=kline_store, availability=availability_store),
            exchange=exchange,
            log=DummyLog(),
            cache_dir=tmp_path,
            range_downloader=downloader,
        )

        result = await resolver.prepare(SymbolInterval("BTC-USDT", Interval.INTERVAL_1d), requested_start, requested_end)

        assert result.ok is False
        assert result.failure.reason == "no_data"
        kline_store.get_klines.assert_not_called()

    asyncio.run(_test())


def test_prepare_uses_cached_exact_boundary_without_querying_binance_daily_archive(tmp_path: Path):
    async def _test():
        start_time = 1_600_000_000 - (1_600_000_000 % 86400)
        exact_start = start_time + 86400
        end_time = exact_start + 86400
        bars = [make_kline(exact_start), make_kline(end_time)]
        kline_store = SimpleNamespace(get_klines=AsyncMock(return_value=bars))
        availability_store = SimpleNamespace(get_earliest_known_open_time=AsyncMock(return_value=exact_start))
        exchange = SimpleNamespace(
            get_earliest_daily_archive_open_time=lambda symbol_interval: (_ for _ in ()).throw(AssertionError("archive lookup must not run")),
        )

        resolver = DatasetResolver(
            db_manager=SimpleNamespace(kline=kline_store, availability=availability_store),
            exchange=exchange,
            log=DummyLog(),
            cache_dir=tmp_path,
        )

        result = await resolver.prepare(SymbolInterval("BTC-USDT", Interval.INTERVAL_1d), start_time, end_time)

        assert result.ok is True

    asyncio.run(_test())


def test_default_downloader_uses_forward_for_internal_gaps_and_backward_for_leading_gaps(tmp_path: Path):
    resolver = DatasetResolver(db_manager=None, exchange=None, log=DummyLog(), cache_dir=tmp_path)

    first_bar = make_kline(1_700_086_400)

    assert resolver._downloader_for_missing_range(1_700_000_000, 1_700_000_000, [first_bar]).__name__ == "download_range_backward"
    assert resolver._downloader_for_missing_range(1_700_172_800, 1_700_172_800, [first_bar]).__name__ == "download_range"


def test_prepare_accepts_complete_daily_coverage_with_interval_offset(tmp_path: Path):
    async def _test():
        requested_start = 1_744_560_000
        requested_start = requested_start - (requested_start % 86400)
        aligned_start = requested_start + 8 * 3600
        end_time = requested_start + 2 * 86400
        bars = [
            make_kline(aligned_start, 100.0),
            make_kline(aligned_start + 86400, 101.0),
        ]
        kline_store = SimpleNamespace(get_klines=AsyncMock(return_value=bars))

        async def downloader(*args, **kwargs):
            raise AssertionError("downloader should not be called for aligned daily coverage")

        resolver = DatasetResolver(
            db_manager=SimpleNamespace(kline=kline_store),
            exchange=SimpleNamespace(),
            log=DummyLog(),
            cache_dir=tmp_path,
            range_downloader=downloader,
        )

        result = await resolver.prepare(SymbolInterval("BTC-USDT", Interval.INTERVAL_1d), requested_start, end_time)

        assert result.ok is True
        assert kline_store.get_klines.call_count == 1

    asyncio.run(_test())


def test_prepare_repairs_only_missing_daily_bar_when_interval_is_offset(tmp_path: Path):
    async def _test():
        requested_start = 1_744_560_000
        requested_start = requested_start - (requested_start % 86400)
        aligned_start = requested_start + 8 * 3600
        missing_bar_open = aligned_start + 86400
        end_time = requested_start + 2 * 86400
        initial_bars = [
            make_kline(aligned_start, 100.0),
            make_kline(aligned_start + 2 * 86400, 102.0),
        ]
        full_bars = [
            make_kline(aligned_start, 100.0),
            make_kline(missing_bar_open, 101.0),
            make_kline(aligned_start + 2 * 86400, 102.0),
        ]
        requested_ranges = []
        kline_store = SimpleNamespace(get_klines=AsyncMock(side_effect=[initial_bars, full_bars]))

        async def downloader(name, log, db_manager_arg, collection_name, exchange, symbol_interval, range_start, range_end, quit_event):
            requested_ranges.append((collection_name, range_start, range_end))
            return True

        resolver = DatasetResolver(
            db_manager=SimpleNamespace(kline=kline_store),
            exchange=SimpleNamespace(),
            log=DummyLog(),
            cache_dir=tmp_path,
            range_downloader=downloader,
        )

        result = await resolver.prepare(SymbolInterval("BTC-USDT", Interval.INTERVAL_1d), requested_start, end_time)

        assert result.ok is True
        assert requested_ranges == [("BTCUSDT-1d", missing_bar_open, missing_bar_open)]
        assert kline_store.get_klines.call_count == 2

    asyncio.run(_test())


def test_prepare_returns_structured_failure_when_gap_download_fails(tmp_path: Path):
    async def _test():
        start_time = 1_700_000_000
        start_time = start_time - (start_time % 86400)
        end_time = start_time + 23 * 3600
        missing_tail_start = start_time + 22 * 3600
        initial_bars = [
            make_kline(start_time, 100.0),
            make_kline(missing_tail_start - 3600, 101.0),
        ]
        kline_store = SimpleNamespace(get_klines=AsyncMock(return_value=initial_bars))
        db_manager = SimpleNamespace(kline=kline_store)

        async def downloader(*args, **kwargs):
            return False

        resolver = DatasetResolver(
            db_manager=db_manager,
            exchange=SimpleNamespace(),
            log=DummyLog(),
            cache_dir=tmp_path,
            range_downloader=downloader,
        )

        result = await resolver.prepare(SymbolInterval("BTC-USDT", Interval.INTERVAL_1h), start_time, end_time)

        assert result.ok is False
        assert result.failure is not None
        assert result.failure.reason == "download_failed"
        assert result.failure.dataset_key == f"BTCUSDT-1h|{start_time}|{end_time}"

    asyncio.run(_test())


def test_prepare_fails_fast_when_missing_ranges_exceed_download_budget(tmp_path: Path):
    async def _test():
        start_time = 1_700_000_000
        start_time = start_time - (start_time % 86400)
        end_time = start_time + 23 * 3600
        leading_first_existing = start_time + 3600
        trailing_last_existing = start_time + 21 * 3600
        initial_bars = [
            make_kline(leading_first_existing, 100.0),
            make_kline(trailing_last_existing, 102.0),
        ]
        kline_store = SimpleNamespace(get_klines=AsyncMock(return_value=initial_bars))
        db_manager = SimpleNamespace(kline=kline_store)

        async def downloader(*args, **kwargs):
            raise AssertionError("downloader should not run after budget is exceeded")

        resolver = DatasetResolver(
            db_manager=db_manager,
            exchange=SimpleNamespace(),
            log=DummyLog(),
            cache_dir=tmp_path,
            range_downloader=downloader,
        )

        result = await resolver.prepare(
            SymbolInterval("BTC-USDT", Interval.INTERVAL_1h),
            start_time,
            end_time,
            max_download_ranges=1,
        )

        assert result.ok is False
        assert result.failure.reason == "download_budget_exceeded"
        assert result.failure.dataset_key == f"BTCUSDT-1h|{start_time}|{end_time}"

    asyncio.run(_test())
