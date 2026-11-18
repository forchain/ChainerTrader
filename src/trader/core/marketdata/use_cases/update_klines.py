"""Kline download use cases over repository, availability, and market-data ports."""

from __future__ import annotations

from asyncio import Event
from datetime import datetime

from trader.common.common import sleep
from trader.core.marketdata.domain import require_ordered_range
from trader.core.marketdata.exceptions import KlineRangeError
from trader.core.marketdata.interfaces import AvailabilityStore, KlineRepository, MarketDataClient
from trader.core.shared.domain import SymbolInterval, add_time_duration, get_time_duration

DOWNLOAD_SPACE_TIME = 5
DOWNLOAD_RETRY_MAX = 5
KLINE_REQUEST_LIMIT_MAX = 1000


def compute_limit_for_range(symbol_interval: SymbolInterval, start_time: int, end_time: int) -> int:
    if start_time > end_time:
        return 0
    step = int(get_time_duration(symbol_interval.interval))
    if step <= 0:
        return KLINE_REQUEST_LIMIT_MAX
    needed = int((end_time - start_time) // step) + 1
    return max(1, min(KLINE_REQUEST_LIMIT_MAX, needed))


def _repository_bundle(repository) -> tuple[KlineRepository, AvailabilityStore | None]:
    kline_repository = getattr(repository, "kline", repository)
    availability_store = getattr(repository, "availability", None)
    return kline_repository, availability_store


async def download_range(
    name: str,
    log,
    repository,
    col_name: str,
    market_data_client: MarketDataClient,
    symbol_interval: SymbolInterval,
    start_time: int,
    end_time: int,
    quit: Event,
    *,
    retry_delay_seconds: float = DOWNLOAD_SPACE_TIME,
    retry_max: int = DOWNLOAD_RETRY_MAX,
) -> bool:
    try:
        require_ordered_range(start_time, end_time)
    except KlineRangeError:
        log.warning(f"{name} invalid range: start={start_time} > end={end_time}")
        return False

    kline_repository, availability_store = _repository_bundle(repository)

    log.info(f"{name} download_range: start={datetime.fromtimestamp(start_time)}, end={datetime.fromtimestamp(end_time)}")

    current_start = start_time
    retry_count = 0
    total_records = 0

    while current_start <= end_time:
        if quit.is_set():
            log.info(f"exit {name}. total={total_records}")
            return False

        batch_limit = compute_limit_for_range(symbol_interval, current_start, end_time)
        batch_end = min(end_time, add_time_duration(current_start, symbol_interval.interval, batch_limit - 1))
        kls = market_data_client.get_klines(symbol_interval, current_start, batch_end, limit=batch_limit)

        if kls is None or len(kls) <= 0:
            log.error(f"{name} get klines is empty")
            if retry_count < retry_max:
                await sleep(log, retry_delay_seconds, f"retry {retry_count + 1}/{retry_max}, {name}")
                retry_count += 1
                continue
            log.warning(f"exit {name}, max retries reached. total={total_records}")
            return False

        retry_count = 0

        ret = await kline_repository.add_klines(col_name, kls, source="exchange")
        total_records += ret

        if ret != len(kls):
            log.warning(f"{name} add klines to DB: {col_name} ({symbol_interval.name()}) {ret} != {len(kls)}")
        else:
            log.info(f"{name} add klines to DB: {col_name} ({symbol_interval.name()}) {ret}/{total_records}")

        last_kline = kls[-1]
        next_start = add_time_duration(last_kline.open_time, symbol_interval.interval, 1)

        if next_start <= current_start:
            log.warning(f"{name} no progress, breaking loop")
            break

        current_start = next_start
        await sleep(log, 0.1)

    if total_records > 0:
        await update_cached_open_time_range(
            availability_store,
            market_data_client,
            symbol_interval,
            start_time,
            end_time,
            source="download_range",
        )
    log.info(f"{name} download_range completed. total={total_records}")
    return True


async def download_range_backward(
    name: str,
    log,
    repository,
    col_name: str,
    market_data_client: MarketDataClient,
    symbol_interval: SymbolInterval,
    start_time: int,
    end_time: int,
    quit: Event,
    *,
    retry_delay_seconds: float = DOWNLOAD_SPACE_TIME,
    retry_max: int = DOWNLOAD_RETRY_MAX,
) -> bool:
    if start_time > end_time:
        log.warning(f"{name} invalid backward range: start={start_time} > end={end_time}")
        return True

    kline_repository, availability_store = _repository_bundle(repository)

    log.info(
        f"{name} download_range_backward: start={datetime.fromtimestamp(start_time)}, end={datetime.fromtimestamp(end_time)}"
    )

    current_end = end_time
    retry_count = 0
    total_records = 0
    earliest_seen_open_time = None
    confirmed_boundary = False

    while current_end >= start_time:
        if quit.is_set():
            log.info(f"exit {name}. total={total_records}")
            return False

        batch_limit = compute_limit_for_range(symbol_interval, start_time, current_end)
        if batch_limit <= 0:
            log.info(f"{name} no remaining candles to download")
            break
        if hasattr(market_data_client, "get_klines_by_end"):
            kls = market_data_client.get_klines_by_end(symbol_interval, current_end, limit=batch_limit)
        else:
            kls = market_data_client.get_klines(symbol_interval, start_time, current_end, limit=batch_limit)

        if kls is None:
            log.error(f"{name} get klines failed")
            if retry_count < retry_max:
                await sleep(log, retry_delay_seconds, f"retry {retry_count + 1}/{retry_max}, {name}")
                retry_count += 1
                continue
            log.warning(f"exit {name}, max retries reached. total={total_records}")
            return False

        if len(kls) <= 0:
            if earliest_seen_open_time is None:
                # We have proven that there are no klines at or before current_end. Record a conservative boundary
                # so downstream dataset coverage checks won't treat pre-listing time as "missing".
                earliest_seen_open_time = add_time_duration(current_end, symbol_interval.interval, 1)
                confirmed_boundary = True
            else:
                confirmed_boundary = True
            break

        retry_count = 0
        ret = await kline_repository.add_klines(col_name, kls, source="exchange")
        total_records += ret

        batch_first_open_time = kls[0].open_time
        if earliest_seen_open_time is None or batch_first_open_time < earliest_seen_open_time:
            earliest_seen_open_time = batch_first_open_time

        if ret != len(kls):
            log.warning(f"{name} add klines to DB: {col_name} ({symbol_interval.name()}) {ret} != {len(kls)}")
        else:
            log.info(f"{name} add klines to DB: {col_name} ({symbol_interval.name()}) {ret}/{total_records}")

        prev_end = add_time_duration(batch_first_open_time, symbol_interval.interval, -1)
        if prev_end >= current_end:
            log.warning(f"{name} no backward progress, breaking loop")
            break

        current_end = prev_end
        if current_end < start_time:
            break
        await sleep(log, 0.1)

    if confirmed_boundary and earliest_seen_open_time is not None and availability_store is not None:
        exchange_name = _market_data_client_name(market_data_client)
        log.info(
            f"{name} detected earliest available kline: exchange={exchange_name} "
            f"symbol_interval={symbol_interval.name()} earliest={datetime.fromtimestamp(earliest_seen_open_time)}"
        )
        await availability_store.update_earliest_known_open_time(
            exchange_name,
            symbol_interval.symbol(),
            symbol_interval.interval.value,
            earliest_seen_open_time,
            source="backward_fill",
        )

    if total_records > 0:
        await update_cached_open_time_range(
            availability_store,
            market_data_client,
            symbol_interval,
            start_time,
            end_time,
            source="download_range_backward",
        )
    log.info(f"{name} download_range_backward completed. total={total_records}")
    return True


async def update_cached_open_time_range(
    availability_store: AvailabilityStore | None,
    market_data_client: MarketDataClient | None,
    symbol_interval: SymbolInterval,
    start_time: int,
    end_time: int,
    source: str,
) -> None:
    if availability_store is None or not hasattr(availability_store, "update_cached_open_time_range"):
        return
    await availability_store.update_cached_open_time_range(
        _market_data_client_name(market_data_client),
        symbol_interval.symbol(),
        symbol_interval.interval.value,
        start_time,
        end_time,
        source=source,
    )


def _market_data_client_name(market_data_client: MarketDataClient | None) -> str:
    if market_data_client is not None and hasattr(market_data_client, "name"):
        return market_data_client.name()
    return "UNKNOWN"
