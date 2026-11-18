from asyncio import Queue
from datetime import datetime

from trader.common.config import Config
from trader.common.logger import Logger
from trader.database.manager import DatabaseManager
from trader.exchange.binance.exchange import BinanceExchange
from trader.task.base_task import BaseTask
from trader.task.dataset_resolver import DatasetResolver
from trader.task.task_config import TaskConfig


class CheckKlinesTask(BaseTask):
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
        if not self.db_manager:
            self.log.error(f"No config db_uri for {self.tcfg.to_dict()}")
            return

        await super().start(queue)

        self.log.info(f"Start {self.name()}")

        first_kl = await self.db_manager.kline.get_first_kline(self.tcfg.symbol_interval.name())
        if first_kl is None:
            self.log.error(f"{self.name()} can't find first kline")
            return

        latest_kl = await self.db_manager.kline.get_latest_kline(self.tcfg.symbol_interval.name())
        if latest_kl is None:
            self.log.error(f"{self.name()} can't find latest kline")
            return
        if first_kl.key() == latest_kl.key():
            self.log.error(f"{self.name()} no need check")
            return

        report = await DatasetResolver(self.db_manager, self.exchange, self.log).inspect_coverage(
            self.tcfg.symbol_interval,
            first_kl.open_time,
            latest_kl.open_time,
        )
        for range_start, range_end in report.missing_ranges:
            self.log.warning(
                f"{self.name()} no kline range: "
                f"{datetime.fromtimestamp(range_start)}..{datetime.fromtimestamp(range_end)}"
            )
        self.log.info(f"{self.name()} process result:{report.missing_count}/{report.expected_count}")
