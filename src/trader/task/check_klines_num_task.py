from asyncio import Queue

from trader.adapters.outbound.binance.exchange import BinanceExchange
from trader.adapters.outbound.persistence.manager import DatabaseManager
from trader.common.config import Config
from trader.common.logger import Logger
from trader.core.task.use_cases.data_tasks import CheckKlinesNumTaskRunner
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
        runner = CheckKlinesNumTaskRunner(
            kline_repository=self.db_manager.kline,
            task_repository=getattr(self.db_manager, "task", None),
            log=self.log,
        )
        await runner.run(self.tcfg, queue=queue, quit_event=self.quit, task_state=self.ts)
