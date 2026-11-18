"""Kline validation use cases over the kline repository port."""

from __future__ import annotations

from asyncio import Event

from trader.core.marketdata.interfaces import KlineRepository
from trader.core.shared.domain import SymbolInterval, add_time_duration


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
