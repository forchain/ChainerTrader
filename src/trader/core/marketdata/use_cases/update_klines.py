"""Kline download use cases over repository, availability, and market-data ports."""

from __future__ import annotations

from asyncio import Event
from datetime import datetime
from types import SimpleNamespace
from typing import Callable

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


DEFAULT_OLDEST_TIME_TS = int(datetime.strptime("2000-01-01 00:00:00", "%Y-%m-%d %H:%M:%S").timestamp())


def determine_update_time_range(
    symbol_interval: SymbolInterval,
    *,
    start_time: int = 0,
    end_time: int = 0,
    limit: int = 0,
    now_fn: Callable[[], int] | None = None,
    oldest_time_ts: int = DEFAULT_OLDEST_TIME_TS,
) -> tuple[int, int]:
    resolved_start = int(start_time or 0)
    if resolved_start <= 0:
        resolved_start = int(oldest_time_ts)

    resolved_end = int(end_time or 0)
    if resolved_end <= 0:
        resolved_end = int(now_fn()) if now_fn is not None else int(datetime.now().timestamp())

    if int(limit or 0) > 0:
        resolved_start = add_time_duration(resolved_end, symbol_interval.interval, -int(limit))

    return resolved_start, resolved_end


async def sync_klines(
    name: str,
    log,
    kline_repository: KlineRepository,
    market_data_client: MarketDataClient,
    symbol_interval: SymbolInterval,
    *,
    start_time: int,
    end_time: int,
    force_update: bool = False,
    quit_event: Event | None = None,
    availability_store: AvailabilityStore | None = None,
    range_downloader=download_range,
) -> None:
    quit_flag = quit_event or Event()
    collection_name = symbol_interval.name()
    repo_bundle = SimpleNamespace(kline=kline_repository, availability=availability_store)

    log.info(
        f"{name} time range: start={datetime.fromtimestamp(start_time)}, "
        f"end={datetime.fromtimestamp(end_time)}, force_update={force_update}"
    )

    if force_update:
        deleted = await kline_repository.delete_klines_in_range(collection_name, start_time, end_time)
        log.info(f"{name} force_update: deleted {deleted} records")
        await range_downloader(
            name,
            log,
            repo_bundle,
            collection_name,
            market_data_client,
            symbol_interval,
            start_time,
            end_time,
            quit_flag,
        )
        return

    db_first = await kline_repository.get_first_kline(collection_name)
    db_last = await kline_repository.get_latest_kline(collection_name)
    if db_first is None or db_last is None:
        log.info(f"{name} no existing records, download full range")
        await range_downloader(
            name,
            log,
            repo_bundle,
            collection_name,
            market_data_client,
            symbol_interval,
            start_time,
            end_time,
            quit_flag,
        )
        return

    db_first_time = db_first.open_time
    db_last_time = db_last.open_time
    interval = symbol_interval.interval
    log.info(f"{name} db range: first={datetime.fromtimestamp(db_first_time)}, last={datetime.fromtimestamp(db_last_time)}")

    if end_time < db_first_time:
        log.info(f"{name} case: end < db_first, download [start, end]")
        await range_downloader(
            name, log, repo_bundle, collection_name, market_data_client, symbol_interval, start_time, end_time, quit_flag
        )
        return

    if start_time < db_first_time <= end_time <= db_last_time:
        range_end = add_time_duration(db_first_time, interval, -1)
        log.info(f"{name} case: start < db_first <= end <= db_last, download [start, db_first)")
        await range_downloader(
            name, log, repo_bundle, collection_name, market_data_client, symbol_interval, start_time, range_end, quit_flag
        )
        return

    if db_first_time <= start_time and end_time <= db_last_time:
        log.info(f"{name} case: db_first <= start <= end <= db_last, skip download")
        return

    if start_time >= db_first_time and db_last_time < end_time:
        range_start = add_time_duration(db_last_time, interval, 1)
        log.info(f"{name} case: start >= db_first and db_last < end, download (db_last, end]")
        await range_downloader(
            name, log, repo_bundle, collection_name, market_data_client, symbol_interval, range_start, end_time, quit_flag
        )
        return

    if start_time < db_first_time and db_last_time < end_time:
        log.info(f"{name} case: start < db_first and db_last < end, download two segments")
        range_end = add_time_duration(db_first_time, interval, -1)
        await range_downloader(
            name, log, repo_bundle, collection_name, market_data_client, symbol_interval, start_time, range_end, quit_flag
        )
        if quit_flag.is_set():
            return
        range_start = add_time_duration(db_last_time, interval, 1)
        await range_downloader(
            name, log, repo_bundle, collection_name, market_data_client, symbol_interval, range_start, end_time, quit_flag
        )
        return

    log.warning(f"{name} unexpected case: start={start_time}, end={end_time}, db_first={db_first_time}, db_last={db_last_time}")
