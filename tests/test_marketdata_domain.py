from pathlib import Path

import pytest

from trader.core.marketdata.domain import (
    cache_range,
    detect_missing_ranges,
    detect_uncached_ranges,
    kline_times,
    require_ordered_range,
)
from trader.core.marketdata.exceptions import DatasetCoverageError, KlineRangeError
from trader.core.shared.domain import Interval, Kline, SymbolInterval


def make_kline(open_time: int) -> Kline:
    return Kline(open_time, 100.0, 101.0, 99.0, 100.5, open_time + 3599, 1.0, 1.0, 1, 1.0, 1.0)


def test_invalid_kline_range_raises_kline_range_error():
    with pytest.raises(KlineRangeError):
        require_ordered_range(200, 100)


def test_dataset_coverage_error_carries_reason():
    error = DatasetCoverageError("coverage_incomplete", "dataset coverage is incomplete")

    assert error.reason == "coverage_incomplete"
    assert str(error) == "dataset coverage is incomplete"


def test_cache_range_clamps_current_day_bucket_to_now():
    start_time = 1_700_000_000
    end_time = start_time + 5 * 3600 + 17 * 60

    _, cache_end = cache_range(SymbolInterval("BTC-USDT", Interval.INTERVAL_1h), start_time, end_time, now=end_time)

    assert cache_end == end_time - (end_time % 3600)


def test_uncached_ranges_split_leading_and_trailing_gaps_around_cached_range():
    symbol_interval = SymbolInterval("BTC-USDT", Interval.INTERVAL_1h)
    start_time = 1_700_000_000
    cached_start = start_time + 3600
    cached_end = start_time + 4 * 3600
    end_time = start_time + 6 * 3600

    ranges = detect_uncached_ranges(symbol_interval, start_time, end_time, (cached_start, cached_end))

    assert ranges == [(start_time, start_time), (start_time + 5 * 3600, end_time)]


def test_missing_ranges_align_to_first_available_open_time():
    symbol_interval = SymbolInterval("BTC-USDT", Interval.INTERVAL_1d)
    aligned_start = 1_744_560_000 + 8 * 3600
    end_time = aligned_start + 2 * 86400
    klines = [make_kline(aligned_start), make_kline(aligned_start + 2 * 86400)]

    ranges = detect_missing_ranges(
        symbol_interval,
        aligned_start,
        end_time,
        klines,
        first_available_open_time=aligned_start,
    )

    assert ranges == [(aligned_start + 86400, aligned_start + 86400)]


def test_kline_times_rejects_duplicate_and_unordered_open_times():
    assert kline_times([make_kline(20), make_kline(10), make_kline(20)]) == {10, 20}


def test_core_marketdata_has_no_asyncio_run():
    core_root = Path(__file__).resolve().parents[1] / "src" / "trader" / "core" / "marketdata"

    offenders = [str(path) for path in core_root.rglob("*.py") if "asyncio.run" in path.read_text(encoding="utf-8")]

    assert offenders == []


def test_dataset_file_store_adapter_round_trips_klines(tmp_path: Path):
    from trader.adapters.outbound.files.dataset import CsvDatasetFileStore

    path = tmp_path / "dataset.csv"
    klines = [make_kline(1_700_000_000), make_kline(1_700_003_600)]

    store = CsvDatasetFileStore()
    store.write_klines(path, klines)

    assert store.count_klines(path) == 2
    assert store.read_rows(path)[0][0] == str(1_700_000_000 * 1000)
