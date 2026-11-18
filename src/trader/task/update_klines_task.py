from asyncio import Event, Queue

from trader.adapters.outbound.binance.exchange import KLINE_LIMIT_MAX, BinanceExchange, get_oldest_time
from trader.adapters.outbound.persistence.manager import DatabaseManager
from trader.common.config import Config
from trader.common.logger import Logger
from trader.core.marketdata.use_cases.update_klines import (
    compute_limit_for_range,
    determine_update_time_range,
    sync_klines,
)
from trader.core.marketdata.use_cases.update_klines import (
    download_range as _download_range,
)
from trader.core.marketdata.use_cases.update_klines import (
    download_range_backward as _download_range_backward,
)
from trader.core.shared.domain import SymbolInterval
from trader.core.task.use_cases.data_tasks import UpdateKlinesTaskRunner
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
        runner = UpdateKlinesTaskRunner(
            kline_repository=self.db_manager.kline,
            market_data_client=self.exchange,
            availability_store=getattr(self.db_manager, "availability", None),
            task_repository=getattr(self.db_manager, "task", None),
            log=self.log,
            oldest_time_ts=int(get_oldest_time().timestamp()),
            range_downloader=download_range,
        )
        await runner.run(self.tcfg, queue=queue, quit_event=self.quit, task_state=self.ts)
        self.stop()

    def _determine_time_range(self) -> tuple[int, int]:
        return determine_update_time_range(
            self.tcfg.symbol_interval,
            start_time=self.tcfg.start_time,
            end_time=self.tcfg.end_time,
            limit=self.tcfg.limit,
            oldest_time_ts=int(get_oldest_time().timestamp()),
        )

    async def _handle_force_update(self, collection_name: str, start_time: int, end_time: int):
        await sync_klines(
            self.name(),
            self.log,
            self.db_manager.kline,
            self.exchange,
            self.tcfg.symbol_interval,
            start_time=start_time,
            end_time=end_time,
            force_update=True,
            quit_event=self.quit,
            availability_store=getattr(self.db_manager, "availability", None),
            range_downloader=download_range,
        )

    async def _handle_normal_update(self, collection_name: str, start_time: int, end_time: int):
        await sync_klines(
            self.name(),
            self.log,
            self.db_manager.kline,
            self.exchange,
            self.tcfg.symbol_interval,
            start_time=start_time,
            end_time=end_time,
            force_update=False,
            quit_event=self.quit,
            availability_store=getattr(self.db_manager, "availability", None),
            range_downloader=download_range,
        )
