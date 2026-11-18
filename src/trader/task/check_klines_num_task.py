from asyncio import Queue

from trader.adapters.outbound.binance.exchange import BinanceExchange
from trader.adapters.outbound.persistence.manager import DatabaseManager
from trader.common.config import Config
from trader.common.logger import Logger
from trader.core.marketdata.use_cases.check_klines import check_kline_count
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig


class CheckKlinesNumTask(BaseTask):
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
        await check_kline_count(
            self.db_manager.kline,
            self.tcfg.symbol_interval,
            self.tcfg.limit,
            self.quit,
            self.log,
            self.name(),
        )
