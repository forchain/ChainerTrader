from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Awaitable, Callable

from trader.task.update_klines_task import download_range_backward
from trader.utils.kline import Kline
from trader.utils.symbol_interval import SymbolInterval, get_time_duration


RangeDownloader = Callable[..., Awaitable[bool]]


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


class DatasetResolver:
    def __init__(
        self,
        db_manager,
        exchange,
        log,
        cache_dir: str | Path | None = None,
        range_downloader: RangeDownloader | None = None,
    ):
        self.db_manager = db_manager
        self.exchange = exchange
        self.log = log
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.range_downloader = range_downloader or download_range_backward
        self._prepared: dict[str, DatasetPreparationResult] = {}

    def _log_prepare_result(
        self,
        symbol_interval: SymbolInterval,
        start_time: int,
        end_time: int,
        result: DatasetPreparationResult,
        elapsed_seconds: float,
    ) -> None:
        try:
            start_dt = datetime.fromtimestamp(start_time).isoformat(sep=" ", timespec="seconds")
            end_dt = datetime.fromtimestamp(end_time).isoformat(sep=" ", timespec="seconds")
        except (OverflowError, OSError, ValueError):
            start_dt = str(start_time)
            end_dt = str(end_time)
        status = "ok" if result.ok else "failed"
        reason = result.failure.reason if result.failure else None
        cache_hit = bool(getattr(result, "cache_hit", False))
        dataset_key = (
            result.dataset_ref.dataset_key
            if result.dataset_ref
            else (result.failure.dataset_key if result.failure else self._build_dataset_key(symbol_interval, start_time, end_time))
        )
        self.log.info(
            f"dataset preparation finished: dataset={dataset_key} symbol_interval={symbol_interval.name()} range={start_dt}..{end_dt} status={status} reason={reason} cache_hit={cache_hit} elapsed={elapsed_seconds:.3f}s"
        )

    async def prepare(
        self,
        symbol_interval: SymbolInterval,
        start_time: int,
        end_time: int,
        allow_download: bool = True,
        max_download_ranges: int | None = None,
        allow_incomplete_coverage: bool = False,
    ) -> DatasetPreparationResult:
        started_at = time.perf_counter()
        cache_start, cache_end = self._cache_range(symbol_interval, start_time, end_time)
        first_available_open_time = None
        if self.db_manager is not None:
            first_available_open_time = await self._get_first_available_open_time(symbol_interval)
        if first_available_open_time is not None and cache_start < first_available_open_time:
            self.log.info(
                f"update dataset start_time to first available kline: symbol_interval={symbol_interval.name()} requested_start={datetime.fromtimestamp(cache_start)} first_available={datetime.fromtimestamp(first_available_open_time)}"
            )
            cache_start = first_available_open_time
        dataset_key = self._build_dataset_key(symbol_interval, cache_start, cache_end)
        if dataset_key in self._prepared:
            result = self._prepared[dataset_key]
            self._log_prepare_result(symbol_interval, start_time, end_time, result, time.perf_counter() - started_at)
            return result

        if self.db_manager is None or getattr(self.db_manager, "kline", None) is None:
            result = self._failure(dataset_key, "db_unavailable", "database manager is required for dataset preparation")
            self._prepared[dataset_key] = result
            self._log_prepare_result(symbol_interval, start_time, end_time, result, time.perf_counter() - started_at)
            return result

        if cache_start > cache_end:
            result = self._failure(dataset_key, "no_data", "requested range is before first available kline")
            self._prepared[dataset_key] = result
            self._log_prepare_result(symbol_interval, start_time, end_time, result, time.perf_counter() - started_at)
            return result

        klines = list(await self.db_manager.kline.get_klines(symbol_interval.name(), cache_start, cache_end) or [])
        missing_ranges = self._detect_missing_ranges(
            symbol_interval,
            cache_start,
            cache_end,
            klines,
            first_available_open_time=first_available_open_time,
        )

        if missing_ranges:
            did_download = False
            if not allow_download or self.exchange is None:
                if not allow_incomplete_coverage:
                    result = self._failure(dataset_key, "coverage_incomplete", "dataset coverage is incomplete and downloading is disabled")
                    self._prepared[dataset_key] = result
                    self._log_prepare_result(symbol_interval, start_time, end_time, result, time.perf_counter() - started_at)
                    return result
                preview = ", ".join(f"[{a},{b}]" for a, b in missing_ranges[:3])
                suffix = f" remaining_missing_ranges={len(missing_ranges)} preview={preview}" if missing_ranges else ""
                self.log.warning(f"dataset coverage incomplete but downloading disabled and allowed: dataset={dataset_key}.{suffix}")
                missing_ranges = []
            if max_download_ranges is not None and len(missing_ranges) > max_download_ranges:
                result = self._failure(
                    dataset_key,
                    "download_budget_exceeded",
                    f"dataset needs {len(missing_ranges)} download ranges, exceeding budget {max_download_ranges}",
                )
                self._prepared[dataset_key] = result
                self._log_prepare_result(symbol_interval, start_time, end_time, result, time.perf_counter() - started_at)
                return result

            for range_start, range_end in missing_ranges:
                did_download = True
                success = await self.range_downloader(
                    "dataset-resolver",
                    self.log,
                    self.db_manager,
                    symbol_interval.name(),
                    self.exchange,
                    symbol_interval,
                    range_start,
                    range_end,
                    asyncio.Event(),
                )
                if not success:
                    result = self._failure(dataset_key, "download_failed", f"failed to download missing range [{range_start}, {range_end}]")
                    self._prepared[dataset_key] = result
                    self._log_prepare_result(symbol_interval, start_time, end_time, result, time.perf_counter() - started_at)
                    return result

            if did_download:
                klines = list(await self.db_manager.kline.get_klines(symbol_interval.name(), cache_start, cache_end) or [])
                first_available_open_time = await self._get_first_available_open_time(symbol_interval)
                missing_ranges = self._detect_missing_ranges(
                    symbol_interval,
                    cache_start,
                    cache_end,
                    klines,
                    first_available_open_time=first_available_open_time,
                )
                if missing_ranges:
                    preview = ", ".join(f"[{a},{b}]" for a, b in missing_ranges[:3])
                    suffix = f" remaining_missing_ranges={len(missing_ranges)} preview={preview}" if missing_ranges else ""
                    if not allow_incomplete_coverage:
                        result = self._failure(dataset_key, "coverage_incomplete", f"dataset is still incomplete after refill.{suffix}")
                        self._prepared[dataset_key] = result
                        self._log_prepare_result(symbol_interval, start_time, end_time, result, time.perf_counter() - started_at)
                        return result
                    self.log.warning(f"dataset coverage incomplete but allowed: dataset={dataset_key}.{suffix}")

        if not klines:
            result = self._failure(dataset_key, "no_data", "no kline data available for dataset")
            self._prepared[dataset_key] = result
            self._log_prepare_result(symbol_interval, start_time, end_time, result, time.perf_counter() - started_at)
            return result

        dataset_ref = self._build_dataset_ref(symbol_interval, cache_start, cache_end)
        result = DatasetPreparationResult(ok=True, dataset_ref=dataset_ref, cache_hit=False)
        self._prepared[dataset_key] = result
        self._log_prepare_result(symbol_interval, start_time, end_time, result, time.perf_counter() - started_at)
        return result

    def _build_dataset_key(self, symbol_interval: SymbolInterval, start_time: int, end_time: int) -> str:
        return f"{symbol_interval.name()}|{start_time}|{end_time}"

    def _build_dataset_ref(self, symbol_interval: SymbolInterval, start_time: int, end_time: int) -> DatasetRef:
        dataset_key = self._build_dataset_key(symbol_interval, start_time, end_time)
        return DatasetRef(
            dataset_key=dataset_key,
            symbol=symbol_interval.symbol(),
            interval=symbol_interval.interval.value,
            start_time=start_time,
            end_time=end_time,
            source_type="db",
        )

    def _cache_range(self, symbol_interval: SymbolInterval, start_time: int, end_time: int) -> tuple[int, int]:
        step = int(get_time_duration(symbol_interval.interval))
        if step <= 0 or start_time > end_time:
            return start_time, end_time

        # Normalize to the strategy interval so second-level end time changes inside the same candle
        # do not produce a different dataset identity or extra database work.
        aligned_end = end_time - ((end_time - start_time) % step)
        return start_time, max(start_time, aligned_end)

    async def _get_first_available_open_time(self, symbol_interval: SymbolInterval) -> int | None:
        availability_store = getattr(self.db_manager, "availability", None)
        if availability_store is None or not hasattr(availability_store, "get_earliest_known_open_time"):
            return None
        exchange_name = self.exchange.name() if self.exchange is not None and hasattr(self.exchange, "name") else "UNKNOWN"
        return await availability_store.get_earliest_known_open_time(
            exchange_name,
            symbol_interval.symbol(),
            symbol_interval.interval.value,
        )

    def _detect_missing_ranges(
        self,
        symbol_interval: SymbolInterval,
        start_time: int,
        end_time: int,
        klines: list[Kline],
        first_available_open_time: int | None = None,
    ) -> list[tuple[int, int]]:
        step = get_time_duration(symbol_interval.interval)
        reference_open_time = self._reference_open_time(klines, first_available_open_time)
        aligned_range = self._aligned_expected_range(start_time, end_time, step, reference_open_time)
        if aligned_range is not None and first_available_open_time is not None:
            aligned_start, aligned_end = aligned_range
            if aligned_start < first_available_open_time:
                aligned_range = (first_available_open_time, aligned_end)

        if not klines:
            if aligned_range is None:
                return [(start_time, end_time)] if start_time <= end_time else []
            aligned_start, aligned_end = aligned_range
            return [(aligned_start, aligned_end)] if aligned_start <= aligned_end else []

        if aligned_range is None:
            return []

        effective_start, effective_end = aligned_range
        if effective_start > effective_end:
            return []

        # Fill policy: only patch the leading and trailing edges of the requested window.
        # Internal gaps are treated as acceptable holes and will not trigger downloads.
        first_existing = klines[0].open_time
        last_existing = klines[-1].open_time

        missing_ranges: list[tuple[int, int]] = []

        if effective_start < first_existing:
            missing_end = first_existing - step
            if effective_start <= missing_end:
                missing_ranges.append((effective_start, missing_end))

        if last_existing < effective_end:
            missing_start = last_existing + step
            if missing_start <= effective_end:
                missing_ranges.append((missing_start, effective_end))

        return missing_ranges

    def _reference_open_time(self, klines: list[Kline], first_available_open_time: int | None) -> int | None:
        if first_available_open_time is not None:
            # Guard against corrupted availability entries that are later than the requested end_time.
            return first_available_open_time
        if klines:
            return klines[0].open_time
        return None

    def _aligned_expected_range(
        self,
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

    def _failure(self, dataset_key: str, reason: str, message: str) -> DatasetPreparationResult:
        return DatasetPreparationResult(
            ok=False,
            failure=DatasetPreparationFailure(
                dataset_key=dataset_key,
                reason=reason,
                message=message,
            ),
        )
