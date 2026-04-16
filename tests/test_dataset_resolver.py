import asyncio
import csv
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock


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
    binance_module.get_oldest_time = lambda: None
    sys.modules[module_name] = binance_module


_ensure_pymongo_stub()
_ensure_binance_exchange_stub()

from trader.task.dataset_resolver import DatasetResolver  # noqa: E402
from trader.utils.kline import Kline  # noqa: E402
from trader.utils.symbol_interval import Interval, SymbolInterval  # noqa: E402


class DummyLog:
    def info(self, *args, **kwargs):
        pass

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


def test_prepare_uses_db_and_materializes_cache_without_downloading(tmp_path: Path):
    async def _test():
        start_time = 1_700_000_000
        end_time = start_time + 2 * 3600
        bars = [
            make_kline(start_time, 100.0),
            make_kline(start_time + 3600, 101.0),
            make_kline(end_time, 102.0),
        ]
        kline_store = SimpleNamespace(get_klines=MagicMock(return_value=bars))
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

        result = await resolver.prepare(SymbolInterval("BTC-USDT", Interval.INTERVAL_1h), start_time, end_time)

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


def test_prepare_detects_internal_gap_and_repairs_before_export(tmp_path: Path):
    async def _test():
        start_time = 1_700_000_000
        end_time = start_time + 2 * 3600
        gap_time = start_time + 3600
        initial_bars = [
            make_kline(start_time, 100.0),
            make_kline(end_time, 102.0),
        ]
        full_bars = [
            make_kline(start_time, 100.0),
            make_kline(gap_time, 101.0),
            make_kline(end_time, 102.0),
        ]
        kline_store = SimpleNamespace(get_klines=MagicMock(side_effect=[initial_bars, full_bars]))
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

        result = await resolver.prepare(SymbolInterval("BTC-USDT", Interval.INTERVAL_1h), start_time, end_time)

        assert result.ok is True
        assert requested_ranges == [("BTCUSDT-1h", gap_time, gap_time)]
        assert kline_store.get_klines.call_count == 2

    asyncio.run(_test())


def test_prepare_reuses_same_dataset_ref_for_duplicate_requests(tmp_path: Path):
    async def _test():
        start_time = 1_700_000_000
        end_time = start_time + 3600
        bars = [
            make_kline(start_time, 100.0),
            make_kline(end_time, 101.0),
        ]
        kline_store = SimpleNamespace(get_klines=MagicMock(return_value=bars))
        db_manager = SimpleNamespace(kline=kline_store)

        resolver = DatasetResolver(
            db_manager=db_manager,
            exchange=SimpleNamespace(),
            log=DummyLog(),
            cache_dir=tmp_path,
        )
        symbol_interval = SymbolInterval("BTC-USDT", Interval.INTERVAL_1h)

        first = await resolver.prepare(symbol_interval, start_time, end_time)
        second = await resolver.prepare(symbol_interval, start_time, end_time)

        assert first.ok is True
        assert second.ok is True
        assert first.dataset_ref.path == second.dataset_ref.path
        assert kline_store.get_klines.call_count == 1

    asyncio.run(_test())


def test_prepare_skips_leading_gap_before_first_available_kline(tmp_path: Path):
    async def _test():
        requested_start = 1_700_000_000
        listed_start = requested_start + 3 * 3600
        end_time = listed_start + 2 * 3600
        bars = [
            make_kline(listed_start, 100.0),
            make_kline(listed_start + 3600, 101.0),
            make_kline(end_time, 102.0),
        ]
        kline_store = SimpleNamespace(
            get_klines=MagicMock(return_value=bars),
        )
        availability_store = SimpleNamespace(
            get_earliest_known_open_time=MagicMock(return_value=listed_start),
        )
        db_manager = SimpleNamespace(kline=kline_store)

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


def test_prepare_downloads_earlier_range_when_no_availability_metadata_exists(tmp_path: Path):
    async def _test():
        requested_start = 1_700_000_000
        known_start = requested_start + 3 * 3600
        end_time = known_start + 2 * 3600
        partial_bars = [
            make_kline(known_start, 100.0),
            make_kline(known_start + 3600, 101.0),
            make_kline(end_time, 102.0),
        ]
        full_bars = [
            make_kline(requested_start, 97.0),
            make_kline(requested_start + 3600, 98.0),
            make_kline(requested_start + 2 * 3600, 99.0),
            *partial_bars,
        ]
        requested_ranges = []
        kline_store = SimpleNamespace(get_klines=MagicMock(side_effect=[partial_bars, full_bars]))
        availability_store = SimpleNamespace(get_earliest_known_open_time=MagicMock(return_value=None))

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

        result = await resolver.prepare(SymbolInterval("BTC-USDT", Interval.INTERVAL_1h), requested_start, end_time)

        assert result.ok is True
        assert requested_ranges == [("BTCUSDT-1h", requested_start, known_start - 3600)]
        assert availability_store.get_earliest_known_open_time.call_count == 2

    asyncio.run(_test())


def test_prepare_accepts_complete_daily_coverage_with_interval_offset(tmp_path: Path):
    async def _test():
        requested_start = 1_744_560_000
        aligned_start = requested_start + 8 * 3600
        end_time = requested_start + 2 * 86400
        bars = [
            make_kline(aligned_start, 100.0),
            make_kline(aligned_start + 86400, 101.0),
        ]
        kline_store = SimpleNamespace(get_klines=MagicMock(return_value=bars))

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
        aligned_start = requested_start + 8 * 3600
        missing_bar_open = aligned_start + 86400
        end_time = requested_start + 3 * 86400
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
        kline_store = SimpleNamespace(get_klines=MagicMock(side_effect=[initial_bars, full_bars]))

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
        end_time = start_time + 2 * 3600
        initial_bars = [
            make_kline(start_time, 100.0),
            make_kline(end_time, 102.0),
        ]
        kline_store = SimpleNamespace(get_klines=MagicMock(return_value=initial_bars))
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
        assert result.failure.dataset_key == "BTCUSDT-1h|1700000000|1700007200"

    asyncio.run(_test())


def test_prepare_fails_fast_when_missing_ranges_exceed_download_budget(tmp_path: Path):
    async def _test():
        start_time = 1_700_000_000
        end_time = start_time + 4 * 3600
        initial_bars = [
            make_kline(start_time, 100.0),
            make_kline(start_time + 2 * 3600, 102.0),
            make_kline(end_time, 104.0),
        ]
        kline_store = SimpleNamespace(get_klines=MagicMock(return_value=initial_bars))
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
        assert result.failure.dataset_key == "BTCUSDT-1h|1700000000|1700014400"

    asyncio.run(_test())
