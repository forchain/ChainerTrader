from __future__ import annotations

import asyncio
import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from trader.common import path
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
    path: str


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
        self.cache_dir = Path(cache_dir or Path(path.GetProjectDir()) / ".cache" / "backtest_datasets")
        self.range_downloader = range_downloader or download_range_backward
        self._prepared: dict[str, DatasetPreparationResult] = {}

    async def prepare(
        self,
        symbol_interval: SymbolInterval,
        start_time: int,
        end_time: int,
        allow_download: bool = True,
        max_download_ranges: int | None = None,
    ) -> DatasetPreparationResult:
        dataset_key = self._build_dataset_key(symbol_interval, start_time, end_time)
        if dataset_key in self._prepared:
            return self._prepared[dataset_key]

        dataset_ref = self._build_dataset_ref(symbol_interval, start_time, end_time)
        if Path(dataset_ref.path).exists():
            result = DatasetPreparationResult(ok=True, dataset_ref=dataset_ref, cache_hit=True)
            self._prepared[dataset_key] = result
            return result

        if self.db_manager is None or getattr(self.db_manager, "kline", None) is None:
            result = self._failure(dataset_key, "db_unavailable", "database manager is required for dataset preparation")
            self._prepared[dataset_key] = result
            return result

        klines = list(self.db_manager.kline.get_klines(symbol_interval.name(), start_time, end_time) or [])
        first_available_open_time = self._get_first_available_open_time(symbol_interval)
        missing_ranges = self._detect_missing_ranges(
            symbol_interval,
            start_time,
            end_time,
            klines,
            first_available_open_time=first_available_open_time,
        )

        if missing_ranges:
            if not allow_download or self.exchange is None:
                result = self._failure(dataset_key, "coverage_incomplete", "dataset coverage is incomplete and downloading is disabled")
                self._prepared[dataset_key] = result
                return result
            if max_download_ranges is not None and len(missing_ranges) > max_download_ranges:
                result = self._failure(
                    dataset_key,
                    "download_budget_exceeded",
                    f"dataset needs {len(missing_ranges)} download ranges, exceeding budget {max_download_ranges}",
                )
                self._prepared[dataset_key] = result
                return result

            for range_start, range_end in missing_ranges:
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
                    return result

            klines = list(self.db_manager.kline.get_klines(symbol_interval.name(), start_time, end_time) or [])
            first_available_open_time = self._get_first_available_open_time(symbol_interval)
            missing_ranges = self._detect_missing_ranges(
                symbol_interval,
                start_time,
                end_time,
                klines,
                first_available_open_time=first_available_open_time,
            )
            if missing_ranges:
                result = self._failure(dataset_key, "coverage_incomplete", "dataset is still incomplete after refill")
                self._prepared[dataset_key] = result
                return result

        if not klines:
            result = self._failure(dataset_key, "no_data", "no kline data available for dataset")
            self._prepared[dataset_key] = result
            return result

        self._materialize_cache(Path(dataset_ref.path), klines)
        result = DatasetPreparationResult(ok=True, dataset_ref=dataset_ref, cache_hit=False)
        self._prepared[dataset_key] = result
        return result

    def _build_dataset_key(self, symbol_interval: SymbolInterval, start_time: int, end_time: int) -> str:
        return f"{symbol_interval.name()}|{start_time}|{end_time}"

    def _build_dataset_ref(self, symbol_interval: SymbolInterval, start_time: int, end_time: int) -> DatasetRef:
        dataset_key = self._build_dataset_key(symbol_interval, start_time, end_time)
        filename = f"{symbol_interval.symbol()}-{symbol_interval.interval.value}-{start_time}-{end_time}.csv"
        return DatasetRef(
            dataset_key=dataset_key,
            symbol=symbol_interval.symbol(),
            interval=symbol_interval.interval.value,
            start_time=start_time,
            end_time=end_time,
            path=str(self.cache_dir / filename),
        )

    def _get_first_available_open_time(self, symbol_interval: SymbolInterval) -> int | None:
        availability_store = getattr(self.db_manager, "availability", None)
        if availability_store is None or not hasattr(availability_store, "get_earliest_known_open_time"):
            return None
        exchange_name = self.exchange.name() if self.exchange is not None and hasattr(self.exchange, "name") else "UNKNOWN"
        return availability_store.get_earliest_known_open_time(
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

        existing = {kl.open_time for kl in klines}
        missing_ranges: list[tuple[int, int]] = []
        range_start = None
        if aligned_range is None:
            return []
        effective_start, effective_end = aligned_range

        ts = effective_start

        while ts <= effective_end:
            if ts not in existing:
                if range_start is None:
                    range_start = ts
            elif range_start is not None:
                missing_ranges.append((range_start, ts - step))
                range_start = None
            ts += step

        if range_start is not None:
            missing_ranges.append((range_start, effective_end))

        return missing_ranges

    def _reference_open_time(self, klines: list[Kline], first_available_open_time: int | None) -> int | None:
        if first_available_open_time is not None:
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

        start_remainder = (start_time - reference_open_time) % step
        aligned_start = start_time if start_remainder == 0 else start_time + (step - start_remainder)
        aligned_end = end_time - ((end_time - reference_open_time) % step)

        if aligned_start > end_time or aligned_end < aligned_start:
            return None

        return aligned_start, aligned_end

    def _materialize_cache(self, output_path: Path, klines: list[Kline]):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            for kl in klines:
                writer.writerow(
                    [
                        kl.open_time * 1000,
                        kl.open,
                        kl.high,
                        kl.low,
                        kl.close,
                        kl.volume,
                        kl.close_time * 1000,
                        kl.vol_quote,
                        kl.trades,
                        kl.vol_taker_base,
                        kl.vol_taker_quote,
                        kl.ignore,
                    ]
                )

    def _failure(self, dataset_key: str, reason: str, message: str) -> DatasetPreparationResult:
        return DatasetPreparationResult(
            ok=False,
            failure=DatasetPreparationFailure(
                dataset_key=dataset_key,
                reason=reason,
                message=message,
            ),
        )
