from asyncio import Event, Queue
from datetime import datetime

from trader.adapters.outbound.binance.exchange import KLINE_LIMIT_MAX, BinanceExchange, get_oldest_time
from trader.adapters.outbound.persistence.manager import DatabaseManager
from trader.common.config import Config
from trader.common.logger import Logger
from trader.core.marketdata.use_cases.update_klines import (
    compute_limit_for_range,
)
from trader.core.marketdata.use_cases.update_klines import (
    download_range as _download_range,
)
from trader.core.marketdata.use_cases.update_klines import (
    download_range_backward as _download_range_backward,
)
from trader.core.shared.domain import SymbolInterval, add_time_duration
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig

DOWNLOAD_SPACE_TIME = 5
DOWNLOAD_RETRY_MAX = 5
KLINE_REQUEST_LIMIT_MAX = KLINE_LIMIT_MAX

_compute_limit_for_range = compute_limit_for_range


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
    return await _download_range(
        name,
        log,
        db_manager,
        col_name,
        exchange,
        symbol_interval,
        start_time,
        end_time,
        quit,
        retry_delay_seconds=DOWNLOAD_SPACE_TIME,
        retry_max=DOWNLOAD_RETRY_MAX,
    )


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
    return await _download_range_backward(
        name,
        log,
        db_manager,
        col_name,
        exchange,
        symbol_interval,
        start_time,
        end_time,
        quit,
        retry_delay_seconds=DOWNLOAD_SPACE_TIME,
        retry_max=DOWNLOAD_RETRY_MAX,
    )


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
            f"{self.name()} time range: start={datetime.fromtimestamp(start_time)}, "
            f"end={datetime.fromtimestamp(end_time)}, force_update={self.tcfg.force_update}"
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
