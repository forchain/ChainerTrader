"""Kline validation use cases over the kline repository port."""

from __future__ import annotations

import inspect
from asyncio import Event
from dataclasses import dataclass, field

from trader.core.marketdata.domain import aligned_expected_range, detect_missing_ranges
from trader.core.marketdata.interfaces import KlineRepository
from trader.core.shared.domain import SymbolInterval, add_time_duration, get_time_duration


@dataclass(frozen=True)
class CoverageReport:
    """Coverage of one kline range, measured with a single range query."""

    symbol_interval: str
    start_time: int
    end_time: int
    expected_count: int = 0
    present_count: int = 0
    missing_ranges: list[tuple[int, int]] = field(default_factory=list)
    first_open_time: int | None = None
    latest_open_time: int | None = None

    @property
    def missing_count(self) -> int:
        return max(self.expected_count - self.present_count, 0)

    @property
    def complete(self) -> bool:
        return not self.missing_ranges and self.present_count >= self.expected_count


async def _maybe_await(value):
    return await value if inspect.isawaitable(value) else value


async def inspect_coverage(
    kline_repository: KlineRepository,
    symbol_interval: SymbolInterval,
    start_time: int = 0,
    end_time: int = 0,
) -> CoverageReport:
    """Inspect coverage with one range query; never issue per-candle lookups."""
    klines = list(await _maybe_await(kline_repository.get_klines(symbol_interval.name(), start_time, end_time)) or [])
    first_open_time = klines[0].open_time if klines else None
    latest_open_time = klines[-1].open_time if klines else None
    effective_start = start_time or (first_open_time or 0)
    effective_end = end_time or (latest_open_time or 0)
    step = int(get_time_duration(symbol_interval.interval)) or 1

    if not klines:
        expected_count = max(0, (effective_end - effective_start) // step + 1) if effective_start <= effective_end else 0
        return CoverageReport(
            symbol_interval=symbol_interval.name(),
            start_time=effective_start,
            end_time=effective_end,
            expected_count=expected_count,
            present_count=0,
            missing_ranges=[(effective_start, effective_end)] if effective_start <= effective_end else [],
        )

    missing_ranges = detect_missing_ranges(
        symbol_interval,
        effective_start,
        effective_end,
        klines,
        first_available_open_time=first_open_time,
    )
    aligned = aligned_expected_range(effective_start, effective_end, step, first_open_time)
    aligned_start, aligned_end = aligned if aligned is not None else (effective_start, effective_end)
    expected_count = max(0, (aligned_end - aligned_start) // step + 1) if aligned_start <= aligned_end else 0
    present_count = sum(1 for kl in klines if aligned_start <= kl.open_time <= aligned_end)
    return CoverageReport(
        symbol_interval=symbol_interval.name(),
        start_time=effective_start,
        end_time=effective_end,
        expected_count=expected_count,
        present_count=present_count,
        missing_ranges=missing_ranges,
        first_open_time=first_open_time,
        latest_open_time=latest_open_time,
    )


async def check_kline_count(
    kline_repository: KlineRepository,
    symbol_interval: SymbolInterval,
    limit: int,
    quit: Event,
    log,
    name: str,
) -> int:
    first_kl = await kline_repository.get_first_kline(symbol_interval.name())
    if first_kl is None:
        log.error(f"{name} can't find first kline")
        return 0

    latest_kl = await kline_repository.get_latest_kline(symbol_interval.name())
    if latest_kl is None:
        log.error(f"{name} can't find latest kline")
        return 0
    if first_kl.key() == latest_kl.key():
        log.error(f"{name} no need check")
        return 0

    count = 0
    total = limit
    next_time = latest_kl.open_time
    while True:
        if quit.is_set():
            log.info(f"{name} exit. Process:{count}/{total}")
            break
        next_time = add_time_duration(next_time, symbol_interval.interval, -1)
        if next_time > first_kl.open_time:
            kl = await kline_repository.get_kline(symbol_interval.name(), next_time)
            if kl is None:
                log.warning(f"{name} no kline: open_time={next_time}. Process:{count}/{total}")
                break
            count += 1
            if total > 0 and count >= total:
                log.info(f"{name} is completed. Process:{count}/{total}")
                break
        else:
            log.info(f"{name} is all completed. Process:{count}/{total}")
            break
    return count


async def check_kline_continuity(
    kline_repository: KlineRepository,
    symbol_interval: SymbolInterval,
    quit: Event,
    log,
    name: str,
) -> tuple[int, int]:
    first_kl = await kline_repository.get_first_kline(symbol_interval.name())
    if first_kl is None:
        log.error(f"{name} can't find first kline")
        return 0, 0

    latest_kl = await kline_repository.get_latest_kline(symbol_interval.name())
    if latest_kl is None:
        log.error(f"{name} can't find latest kline")
        return 0, 0
    if first_kl.key() == latest_kl.key():
        log.error(f"{name} no need check")
        return 0, 0

    count = 0
    total = 0
    next_time = first_kl.open_time
    while True:
        if quit.is_set():
            break
        total += 1
        next_time = add_time_duration(next_time, symbol_interval.interval, 1)
        if next_time < latest_kl.open_time:
            kl = await kline_repository.get_kline(symbol_interval.name(), next_time)
            if kl is None:
                count += 1
                log.warning(f"{name} no kline: open_time={next_time}")
        else:
            log.info(f"{name} is completed")
            break
    return count, total
