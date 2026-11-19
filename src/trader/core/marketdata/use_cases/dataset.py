"""Dataset preparation use case over kline, availability, market-data, and file ports."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Awaitable, Callable

from trader.core.marketdata.domain import (
    DatasetPreparationResult,
    DatasetRef,
    aligned_expected_range,
    build_dataset_key,
    build_dataset_ref,
    cache_range,
    detect_missing_ranges,
    detect_uncached_ranges,
    prepare_failure,
)
from trader.core.marketdata.interfaces import AvailabilityStore, DatasetFileStore, KlineRepository, MarketDataClient
from trader.core.marketdata.use_cases.update_klines import download_range, download_range_backward
from trader.core.shared.domain import Kline, SymbolInterval

RangeDownloader = Callable[..., Awaitable[bool]]


class DatasetResolver:
    def __init__(
        self,
        db_manager=None,
        exchange=None,
        log=None,
        cache_dir: str | Path | None = None,
        range_downloader: RangeDownloader | None = None,
        *,
        kline_repository: KlineRepository | None = None,
        availability_store: AvailabilityStore | None = None,
        market_data_client: MarketDataClient | None = None,
        file_store: DatasetFileStore | None = None,
    ):
        self.kline_repository = kline_repository if kline_repository is not None else getattr(db_manager, "kline", None)
        self.availability_store = (
            availability_store if availability_store is not None else getattr(db_manager, "availability", None)
        )
        self.market_data_client = market_data_client if market_data_client is not None else exchange
        self.log = log
        self.cache_dir = Path(cache_dir) if cache_dir is not None else None
        self.file_store = file_store
        self._download_context = SimpleNamespace(kline=self.kline_repository, availability=self.availability_store)
        self._custom_range_downloader = range_downloader is not None
        self.range_downloader = range_downloader or download_range
        self.backward_range_downloader = range_downloader or download_range_backward
        self._prepared: dict[str, DatasetPreparationResult] = {}

    def _log_prepare_result(
        self,
        symbol_interval: SymbolInterval,
        start_time: int,
        end_time: int,
        result,
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
            "dataset preparation finished: "
            f"dataset={dataset_key} symbol_interval={symbol_interval.name()} range={start_dt}..{end_dt} "
            f"status={status} reason={reason} cache_hit={cache_hit} elapsed={elapsed_seconds:.3f}s"
        )

    async def prepare(
        self,
        symbol_interval: SymbolInterval,
        start_time: int,
        end_time: int,
        allow_download: bool = True,
        max_download_ranges: int | None = None,
        allow_incomplete_coverage: bool = False,
        force_sync: bool = False,
    ):
        started_at = time.perf_counter()
        cache_start, cache_end = self._cache_range(symbol_interval, start_time, end_time)
        first_available_open_time = None
        cached_open_time_range = None
        supports_cached_range = False
        if self.kline_repository is not None:
            first_available_open_time = await self._get_first_available_open_time(symbol_interval)
            supports_cached_range = self._supports_cached_open_time_range()
            if supports_cached_range:
                cached_open_time_range = await self._get_cached_open_time_range(symbol_interval)
        if first_available_open_time is None:
            archive_start = await self._get_daily_archive_start_time(symbol_interval)
            if archive_start is not None and cache_start < archive_start:
                self.log.info(
                    "update dataset start_time to Binance daily archive boundary: "
                    f"symbol_interval={symbol_interval.name()} requested_start={datetime.fromtimestamp(cache_start)} "
                    f"archive_start={datetime.fromtimestamp(archive_start)}"
                )
                cache_start = archive_start
        if first_available_open_time is not None and cache_start < first_available_open_time:
            self.log.info(
                "update dataset start_time to first available kline: "
                f"symbol_interval={symbol_interval.name()} requested_start={datetime.fromtimestamp(cache_start)} "
                f"first_available={datetime.fromtimestamp(first_available_open_time)}"
            )
            cache_start = first_available_open_time
        dataset_key = self._build_dataset_key(symbol_interval, cache_start, cache_end)
        if dataset_key in self._prepared and not force_sync:
            result = self._prepared[dataset_key]
            self._log_prepare_result(symbol_interval, start_time, end_time, result, time.perf_counter() - started_at)
            return result

        if self.kline_repository is None:
            result = self._failure(dataset_key, "db_unavailable", "database manager is required for dataset preparation")
            self._prepared[dataset_key] = result
            self._log_prepare_result(symbol_interval, start_time, end_time, result, time.perf_counter() - started_at)
            return result

        if cache_start > end_time:
            result = self._failure(dataset_key, "no_data", "requested range is before first available kline")
            self._prepared[dataset_key] = result
            self._log_prepare_result(symbol_interval, start_time, end_time, result, time.perf_counter() - started_at)
            return result

        dataset_ref = self._build_dataset_ref(symbol_interval, cache_start, cache_end)
        klines = list(await self.kline_repository.get_klines(symbol_interval.name(), cache_start, cache_end) or [])
        if force_sync:
            # A forced sync re-downloads the whole requested range, ignoring cached coverage.
            missing_ranges = [(cache_start, cache_end)]
        elif supports_cached_range:
            missing_ranges = self._detect_uncached_ranges(
                symbol_interval,
                cache_start,
                cache_end,
                cached_open_time_range,
            )
            if not missing_ranges and not klines:
                self.log.warning(
                    "cached dataset coverage has no persisted klines; treating cache metadata as stale: "
                    f"symbol_interval={symbol_interval.name()} range={datetime.fromtimestamp(cache_start)}.."
                    f"{datetime.fromtimestamp(cache_end)}"
                )
                missing_ranges = [(cache_start, cache_end)]
        else:
            missing_ranges = self._detect_missing_ranges(
                symbol_interval,
                start_time,
                end_time,
                klines,
                first_available_open_time=first_available_open_time,
            )
            if missing_ranges:
                # Compatibility fallback for DB adapters that do not persist cache coverage.
                missing_ranges = self._detect_missing_ranges(
                    symbol_interval,
                    cache_start,
                    cache_end,
                    klines,
                    first_available_open_time=first_available_open_time,
                )

        coverage_relaxed = False
        if missing_ranges:
            did_download = False
            if not allow_download or self.market_data_client is None:
                if not allow_incomplete_coverage:
                    result = self._failure(dataset_key, "coverage_incomplete", "dataset coverage is incomplete and downloading is disabled")
                    self._prepared[dataset_key] = result
                    self._log_prepare_result(symbol_interval, start_time, end_time, result, time.perf_counter() - started_at)
                    return result
                preview = ", ".join(f"[{a},{b}]" for a, b in missing_ranges[:3])
                suffix = f" remaining_missing_ranges={len(missing_ranges)} preview={preview}" if missing_ranges else ""
                self.log.warning(f"dataset coverage incomplete but downloading disabled and allowed: dataset={dataset_key}.{suffix}")
                missing_ranges = []
                coverage_relaxed = True
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
                downloader = self._downloader_for_missing_range(range_start, range_end, klines)
                success = await downloader(
                    "dataset-resolver",
                    self.log,
                    self._download_context,
                    symbol_interval.name(),
                    self.market_data_client,
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
                klines = list(await self.kline_repository.get_klines(symbol_interval.name(), cache_start, cache_end) or [])
                first_available_open_time = await self._get_first_available_open_time(symbol_interval)
                if supports_cached_range:
                    if klines:
                        await self._update_cached_open_time_range(symbol_interval, cache_start, cache_end)
                        missing_ranges = []
                    else:
                        missing_ranges = [(cache_start, cache_end)]
                else:
                    missing_ranges = self._detect_missing_ranges(
                        symbol_interval,
                        cache_start,
                        end_time,
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

        cache_path = Path(dataset_ref.path) if dataset_ref.path else None
        if (
            self.cache_dir is not None
            and self.file_store is not None
            and cache_path is not None
            and cache_path.exists()
            and not missing_ranges
            and not coverage_relaxed
            and len(klines) == self._count_csv_data_rows(cache_path)
        ):
            result = self._result_ok(dataset_ref, cache_hit=True)
            self._prepared[dataset_key] = result
            self._log_prepare_result(symbol_interval, start_time, end_time, result, time.perf_counter() - started_at)
            return result

        if not klines:
            result = self._failure(dataset_key, "no_data", "no kline data available for dataset")
            self._prepared[dataset_key] = result
            self._log_prepare_result(symbol_interval, start_time, end_time, result, time.perf_counter() - started_at)
            return result

        if self.cache_dir is not None:
            self._materialize_cache(cache_path, klines)

        result = self._result_ok(dataset_ref, cache_hit=False)
        self._prepared[dataset_key] = result
        self._log_prepare_result(symbol_interval, start_time, end_time, result, time.perf_counter() - started_at)
        return result

    def _downloader_for_missing_range(self, range_start: int, range_end: int, klines: list[Kline]) -> RangeDownloader:
        if self._custom_range_downloader:
            return self.range_downloader
        first_existing = klines[0].open_time if klines else None
        if first_existing is None or range_end < first_existing:
            return self.backward_range_downloader
        return self.range_downloader

    def _build_dataset_key(self, symbol_interval: SymbolInterval, start_time: int, end_time: int) -> str:
        return build_dataset_key(symbol_interval, start_time, end_time)

    def _build_dataset_ref(self, symbol_interval: SymbolInterval, start_time: int, end_time: int) -> DatasetRef:
        return build_dataset_ref(symbol_interval, start_time, end_time, self.cache_dir)

    def _cache_range(self, symbol_interval: SymbolInterval, start_time: int, end_time: int) -> tuple[int, int]:
        return cache_range(symbol_interval, start_time, end_time, now=int(time.time()))

    async def _get_first_available_open_time(self, symbol_interval: SymbolInterval) -> int | None:
        if self.availability_store is None or not hasattr(self.availability_store, "get_earliest_known_open_time"):
            return None
        return await self.availability_store.get_earliest_known_open_time(
            self._exchange_name(),
            symbol_interval.symbol(),
            symbol_interval.interval.value,
        )

    async def _get_daily_archive_start_time(self, symbol_interval: SymbolInterval) -> int | None:
        lookup = getattr(self.market_data_client, "get_earliest_daily_archive_open_time", None)
        if lookup is None:
            return None
        try:
            return await asyncio.to_thread(lookup, symbol_interval)
        except Exception as exc:
            self.log.warning(
                "Binance daily archive lookup failed; falling back to reverse kline discovery: "
                f"symbol_interval={symbol_interval.name()} error={exc}"
            )
            return None

    def _supports_cached_open_time_range(self) -> bool:
        return self.availability_store is not None and hasattr(self.availability_store, "get_cached_open_time_range")

    async def _get_cached_open_time_range(self, symbol_interval: SymbolInterval) -> tuple[int, int] | None:
        if not self._supports_cached_open_time_range():
            return None
        return await self.availability_store.get_cached_open_time_range(
            self._exchange_name(),
            symbol_interval.symbol(),
            symbol_interval.interval.value,
        )

    async def _update_cached_open_time_range(self, symbol_interval: SymbolInterval, start_time: int, end_time: int) -> None:
        if self.availability_store is None or not hasattr(self.availability_store, "update_cached_open_time_range"):
            return
        await self.availability_store.update_cached_open_time_range(
            self._exchange_name(),
            symbol_interval.symbol(),
            symbol_interval.interval.value,
            start_time,
            end_time,
            source="dataset_resolver",
        )

    def _exchange_name(self) -> str:
        if self.market_data_client is not None and hasattr(self.market_data_client, "name"):
            return self.market_data_client.name()
        return "UNKNOWN"

    def _detect_uncached_ranges(
        self,
        symbol_interval: SymbolInterval,
        start_time: int,
        end_time: int,
        cached_open_time_range: tuple[int, int] | None,
    ) -> list[tuple[int, int]]:
        return detect_uncached_ranges(symbol_interval, start_time, end_time, cached_open_time_range)

    def _detect_missing_ranges(
        self,
        symbol_interval: SymbolInterval,
        start_time: int,
        end_time: int,
        klines: list[Kline],
        first_available_open_time: int | None = None,
    ) -> list[tuple[int, int]]:
        return detect_missing_ranges(symbol_interval, start_time, end_time, klines, first_available_open_time)

    def _aligned_expected_range(
        self,
        start_time: int,
        end_time: int,
        step: int,
        reference_open_time: int | None,
    ) -> tuple[int, int] | None:
        return aligned_expected_range(start_time, end_time, step, reference_open_time)

    def _materialize_cache(self, output_path: Path, klines: list[Kline]):
        if self.file_store is None:
            return
        self.file_store.write_klines(output_path, klines)

    def _count_csv_data_rows(self, path: Path) -> int:
        if self.file_store is None:
            return -1
        return self.file_store.count_klines(path)

    def _failure(self, dataset_key: str, reason: str, message: str):
        return prepare_failure(dataset_key, reason, message)

    @staticmethod
    def _result_ok(dataset_ref: DatasetRef, *, cache_hit: bool) -> DatasetPreparationResult:
        return DatasetPreparationResult(ok=True, dataset_ref=dataset_ref, cache_hit=cache_hit)
