from asyncio import Event, Queue
from datetime import datetime

from trader.common.common import sleep
from trader.common.config import Config
from trader.common.logger import Logger
from trader.database.manager import DatabaseManager
from trader.exchange.binance.exchange import BinanceExchange, KLINE_LIMIT_MAX, get_oldest_time
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig
from trader.utils.symbol_interval import SymbolInterval, add_time_duration, get_time_duration

DOWNLOAD_SPACE_TIME = 5
DOWNLOAD_RETRY_MAX = 5
KLINE_REQUEST_LIMIT_MAX = KLINE_LIMIT_MAX


def _compute_limit_for_range(symbol_interval: SymbolInterval, start_time: int, end_time: int) -> int:
    if start_time > end_time:
        return 0
    step = int(get_time_duration(symbol_interval.interval))
    if step <= 0:
        return KLINE_REQUEST_LIMIT_MAX
    needed = int((end_time - start_time) // step) + 1
    return max(1, min(KLINE_REQUEST_LIMIT_MAX, needed))


class UpdateKlinesTask(BaseTask):
    def __init__(
        self,
        tcfg: TaskConfig,
        cfg: Config,
        log: Logger,
        db_manager: DatabaseManager,
        exchange: BinanceExchange,
    ):
        super().__init__(tcfg, cfg, log, db_manager, exchange)

    async def start(self, queue: Queue):
        if not self.exchange:
            self.log.error(f"No config exchange for {self.tcfg.to_dict()}")
            return
        if not self.db_manager:
            self.log.error(f"No config db_uri for {self.tcfg.to_dict()}")
            return

        await super().start(queue)

        collection_name = self.tcfg.symbol_interval.name()

        start_time, end_time = self._determine_time_range()

        self.log.info(
            f"{self.name()} time range: start={datetime.fromtimestamp(start_time)}, end={datetime.fromtimestamp(end_time)}, force_update={self.tcfg.force_update}"
        )

        if self.tcfg.force_update:
            await self._handle_force_update(collection_name, start_time, end_time)
        else:
            await self._handle_normal_update(collection_name, start_time, end_time)

        self.stop()

    def _determine_time_range(self) -> tuple[int, int]:
        start_time = self.tcfg.start_time
        if start_time <= 0:
            start_time = int(get_oldest_time().timestamp())

        end_time = self.tcfg.end_time
        if end_time <= 0:
            end_time = int(datetime.now().timestamp())

        if self.tcfg.limit > 0:
            start_time = add_time_duration(
                end_time,
                self.tcfg.symbol_interval.interval,
                -self.tcfg.limit,
            )

        return start_time, end_time

    async def _handle_force_update(self, collection_name: str, start_time: int, end_time: int):
        deleted = await self.db_manager.kline.delete_klines_in_range(collection_name, start_time, end_time)
        self.log.info(f"{self.name()} force_update: deleted {deleted} records")

        await download_range(
            self.name(),
            self.log,
            self.db_manager,
            collection_name,
            self.exchange,
            self.tcfg.symbol_interval,
            start_time,
            end_time,
            self.quit,
        )

    async def _handle_normal_update(self, collection_name: str, start_time: int, end_time: int):
        db_first = await self.db_manager.kline.get_first_kline(collection_name)
        db_last = await self.db_manager.kline.get_latest_kline(collection_name)

        if db_first is None or db_last is None:
            self.log.info(f"{self.name()} no existing records, download full range")
            await download_range(
                self.name(),
                self.log,
                self.db_manager,
                collection_name,
                self.exchange,
                self.tcfg.symbol_interval,
                start_time,
                end_time,
                self.quit,
            )
            return

        db_first_time = db_first.open_time
        db_last_time = db_last.open_time
        interval = self.tcfg.symbol_interval.interval

        self.log.info(
            f"{self.name()} db range: first={datetime.fromtimestamp(db_first_time)}, last={datetime.fromtimestamp(db_last_time)}"
        )

        # Case 1: end < db_first - download [start, end]
        if end_time < db_first_time:
            self.log.info(f"{self.name()} case: end < db_first, download [start, end]")
            await download_range(
                self.name(),
                self.log,
                self.db_manager,
                collection_name,
                self.exchange,
                self.tcfg.symbol_interval,
                start_time,
                end_time,
                self.quit,
            )
            return

        # Case 2: start < db_first <= end <= db_last - download [start, db_first)
        if start_time < db_first_time <= end_time <= db_last_time:
            range_end = add_time_duration(db_first_time, interval, -1)
            self.log.info(f"{self.name()} case: start < db_first <= end <= db_last, download [start, db_first)")
            await download_range(
                self.name(),
                self.log,
                self.db_manager,
                collection_name,
                self.exchange,
                self.tcfg.symbol_interval,
                start_time,
                range_end,
                self.quit,
            )
            return

        # Case 3: db_first <= start <= end <= db_last - skip
        if db_first_time <= start_time and end_time <= db_last_time:
            self.log.info(f"{self.name()} case: db_first <= start <= end <= db_last, skip download")
            return

        # Case 4: start <= db_last < end - download (db_last, end]
        if start_time >= db_first_time and db_last_time < end_time:
            range_start = add_time_duration(db_last_time, interval, 1)
            self.log.info(f"{self.name()} case: start >= db_first and db_last < end, download (db_last, end]")
            await download_range(
                self.name(),
                self.log,
                self.db_manager,
                collection_name,
                self.exchange,
                self.tcfg.symbol_interval,
                range_start,
                end_time,
                self.quit,
            )
            return

        # Case 5: start < db_first and db_last < end - download two segments
        if start_time < db_first_time and db_last_time < end_time:
            self.log.info(f"{self.name()} case: start < db_first and db_last < end, download two segments")

            # Download [start, db_first)
            range_end = add_time_duration(db_first_time, interval, -1)
            await download_range(
                self.name(),
                self.log,
                self.db_manager,
                collection_name,
                self.exchange,
                self.tcfg.symbol_interval,
                start_time,
                range_end,
                self.quit,
            )

            if self.quit.is_set():
                return

            # Download (db_last, end]
            range_start = add_time_duration(db_last_time, interval, 1)
            await download_range(
                self.name(),
                self.log,
                self.db_manager,
                collection_name,
                self.exchange,
                self.tcfg.symbol_interval,
                range_start,
                end_time,
                self.quit,
            )
            return

        self.log.warning(f"{self.name()} unexpected case: start={start_time}, end={end_time}, db_first={db_first_time}, db_last={db_last_time}")


async def download_range(
    name: str,
    log: Logger,
    db_manager: DatabaseManager,
    col_name: str,
    exchange: BinanceExchange,
    symbol_interval: SymbolInterval,
    start_time: int,
    end_time: int,
    quit: Event,
) -> bool:
    if start_time > end_time:
        log.warning(f"{name} invalid range: start={start_time} > end={end_time}")
        return False

    log.info(
        f"{name} download_range: start={datetime.fromtimestamp(start_time)}, end={datetime.fromtimestamp(end_time)}"
    )

    current_start = start_time
    retry_count = 0
    total_records = 0

    while current_start <= end_time:
        if quit.is_set():
            log.info(f"exit {name}. total={total_records}")
            return False

        batch_limit = _compute_limit_for_range(symbol_interval, current_start, end_time)
        batch_end = min(end_time, add_time_duration(current_start, symbol_interval.interval, batch_limit - 1))
        kls = exchange.get_klines(symbol_interval, current_start, batch_end, limit=batch_limit)

        if kls is None or len(kls) <= 0:
            log.error(f"{name} get klines is empty")
            if retry_count < DOWNLOAD_RETRY_MAX:
                await sleep(log, DOWNLOAD_SPACE_TIME, f"retry {retry_count + 1}/{DOWNLOAD_RETRY_MAX}, {name}")
                retry_count += 1
                continue
            else:
                log.warning(f"exit {name}, max retries reached. total={total_records}")
                return False

        retry_count = 0

        ret = await db_manager.kline.add_klines(col_name, kls, source="exchange")
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

    log.info(f"{name} download_range completed. total={total_records}")
    return True


async def download_range_backward(
    name: str,
    log: Logger,
    db_manager: DatabaseManager,
    col_name: str,
    exchange: BinanceExchange,
    symbol_interval: SymbolInterval,
    start_time: int,
    end_time: int,
    quit: Event,
) -> bool:
    if start_time > end_time:
        log.warning(f"{name} invalid backward range: start={start_time} > end={end_time}")
        return True

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

        batch_limit = _compute_limit_for_range(symbol_interval, start_time, current_end)
        if batch_limit <= 0:
            log.info(f"{name} no remaining candles to download")
            break
        if hasattr(exchange, "get_klines_by_end"):
            kls = exchange.get_klines_by_end(symbol_interval, current_end, limit=batch_limit)
        else:
            kls = exchange.get_klines(symbol_interval, start_time, current_end, limit=batch_limit)

        if kls is None:
            log.error(f"{name} get klines failed")
            if retry_count < DOWNLOAD_RETRY_MAX:
                await sleep(log, DOWNLOAD_SPACE_TIME, f"retry {retry_count + 1}/{DOWNLOAD_RETRY_MAX}, {name}")
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
        ret = await db_manager.kline.add_klines(col_name, kls, source="exchange")
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

    availability = getattr(db_manager, "availability", None)
    if confirmed_boundary and earliest_seen_open_time is not None and availability is not None:
        exchange_name = exchange.name() if hasattr(exchange, "name") else "UNKNOWN"
        log.info(
            f"{name} detected earliest available kline: exchange={exchange_name} symbol_interval={symbol_interval.name()} earliest={datetime.fromtimestamp(earliest_seen_open_time)}"
        )
        await availability.update_earliest_known_open_time(
            exchange_name,
            symbol_interval.symbol(),
            symbol_interval.interval.value,
            earliest_seen_open_time,
            source="backward_fill",
        )

    log.info(f"{name} download_range_backward completed. total={total_records}")
    return True
