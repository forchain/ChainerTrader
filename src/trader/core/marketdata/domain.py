"""Market-data domain values and pure coverage rules.

Availability/cached-range and dataset-coverage rules live here so they can be
tested without a database, filesystem, network, or event loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from trader.core.marketdata.exceptions import DatasetCoverageError, KlineRangeError
from trader.core.shared.domain import Kline, SymbolInterval, get_time_duration


@dataclass(frozen=True)
class AvailabilityState:
    exchange: str
    symbol: str
    interval: str
    earliest_known_open_time: int | None
    cached_start_open_time: int | None
    cached_end_open_time: int | None
    updated_at: int
    source: str


@dataclass(frozen=True)
class DatasetRef:
    dataset_key: str
    symbol: str
    interval: str
    start_time: int
    end_time: int
    source_type: str = "db"
    path: str | None = None


@dataclass(frozen=True)
class DatasetPreparationFailure:
    dataset_key: str
    reason: str
    message: str


@dataclass(frozen=True)
class DatasetPreparationResult:
    ok: bool
    dataset_ref: DatasetRef | None = None
    failure: DatasetPreparationFailure | None = None
    cache_hit: bool = False


def require_ordered_range(start_time: int, end_time: int) -> None:
    if start_time > end_time:
        raise KlineRangeError(f"invalid kline range: start_time={start_time} > end_time={end_time}")


def cache_range(symbol_interval: SymbolInterval, start_time: int, end_time: int, now: int) -> tuple[int, int]:
    step = int(get_time_duration(symbol_interval.interval))
    if step <= 0 or start_time > end_time:
        return start_time, end_time

    # Historical requests can reuse a full day cache bucket. Cap the current
    # day's bucket at now so an exchange is never asked for future candles.
    day_seconds = 86400
    day_start = start_time - (start_time % day_seconds)
    day_end = ((end_time // day_seconds) + 1) * day_seconds - 1
    cache_end = min(day_end, int(now))
    aligned = aligned_expected_range(day_start, cache_end, step, reference_open_time=0)
    if aligned is None:
        return day_start, cache_end
    return aligned


def reference_open_time(klines: list[Kline], first_available_open_time: int | None) -> int | None:
    if first_available_open_time is not None:
        # Guard against corrupted availability entries that are later than the requested end_time.
        return first_available_open_time
    if klines:
        return klines[0].open_time
    return None


def aligned_expected_range(
    start_time: int,
    end_time: int,
    step: int,
    reference_open_time: int | None,
) -> tuple[int, int] | None:
    if start_time > end_time:
        return None
    if reference_open_time is None:
        return (start_time, end_time)
    if reference_open_time > end_time:
        return (start_time, end_time)

    start_remainder = (start_time - reference_open_time) % step
    aligned_start = start_time if start_remainder == 0 else start_time + (step - start_remainder)
    aligned_end = end_time - ((end_time - reference_open_time) % step)

    if aligned_start > end_time or aligned_end < aligned_start:
        return None

    return aligned_start, aligned_end


def detect_uncached_ranges(
    symbol_interval: SymbolInterval,
    start_time: int,
    end_time: int,
    cached_open_time_range: tuple[int, int] | None,
) -> list[tuple[int, int]]:
    if start_time > end_time:
        return []
    if cached_open_time_range is None:
        return [(start_time, end_time)]

    cached_start, cached_end = cached_open_time_range
    if cached_start > cached_end:
        return [(start_time, end_time)]

    step = int(get_time_duration(symbol_interval.interval))
    if step <= 0:
        step = 1

    missing_ranges: list[tuple[int, int]] = []
    if start_time < cached_start:
        leading_end = min(end_time, cached_start - step)
        if start_time <= leading_end:
            missing_ranges.append((start_time, leading_end))
    if cached_end < end_time:
        trailing_start = max(start_time, cached_end + step)
        if trailing_start <= end_time:
            missing_ranges.append((trailing_start, end_time))
    return missing_ranges


def kline_times(klines: list[Kline]) -> set[int]:
    return {int(kline.open_time) for kline in klines}


def detect_missing_ranges(
    symbol_interval: SymbolInterval,
    start_time: int,
    end_time: int,
    klines: list[Kline],
    first_available_open_time: int | None = None,
) -> list[tuple[int, int]]:
    step = get_time_duration(symbol_interval.interval)
    reference = reference_open_time(klines, first_available_open_time)
    expected_range = aligned_expected_range(start_time, end_time, step, reference)
    if expected_range is not None and first_available_open_time is not None:
        aligned_start, aligned_end = expected_range
        if aligned_start < first_available_open_time:
            expected_range = (first_available_open_time, aligned_end)

    if not klines:
        if expected_range is None:
            return [(start_time, end_time)] if start_time <= end_time else []
        aligned_start, aligned_end = expected_range
        return [(aligned_start, aligned_end)] if aligned_start <= aligned_end else []

    if expected_range is None:
        return []

    effective_start, effective_end = expected_range
    if effective_start > effective_end:
        return []

    existing_times = {open_time for open_time in kline_times(klines) if effective_start <= open_time <= effective_end}
    missing_ranges: list[tuple[int, int]] = []
    current_start: int | None = None
    current_end: int | None = None

    for expected_time in range(effective_start, effective_end + 1, step):
        if expected_time in existing_times:
            if current_start is not None and current_end is not None:
                missing_ranges.append((current_start, current_end))
                current_start = None
                current_end = None
            continue
        if current_start is None:
            current_start = expected_time
        current_end = expected_time

    if current_start is not None and current_end is not None:
        missing_ranges.append((current_start, current_end))

    return missing_ranges


def build_dataset_key(symbol_interval: SymbolInterval, start_time: int, end_time: int) -> str:
    return f"{symbol_interval.name()}|{start_time}|{end_time}"


def build_dataset_ref(
    symbol_interval: SymbolInterval,
    start_time: int,
    end_time: int,
    cache_dir: Path | None,
) -> DatasetRef:
    dataset_key = build_dataset_key(symbol_interval, start_time, end_time)
    filename = f"{symbol_interval.symbol()}-{symbol_interval.interval.value}-{start_time}-{end_time}.csv"
    return DatasetRef(
        dataset_key=dataset_key,
        symbol=symbol_interval.symbol(),
        interval=symbol_interval.interval.value,
        start_time=start_time,
        end_time=end_time,
        source_type="db",
        path=str(cache_dir / filename) if cache_dir is not None else None,
    )


def prepare_failure(dataset_key: str, reason: str, message: str) -> DatasetPreparationResult:
    error = DatasetCoverageError(reason, message)
    return DatasetPreparationResult(
        ok=False,
        failure=DatasetPreparationFailure(dataset_key=dataset_key, reason=error.reason, message=str(error)),
    )
