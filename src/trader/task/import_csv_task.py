from asyncio import Queue

from trader.adapters.outbound.binance.exchange import BinanceExchange
from trader.adapters.outbound.files.dataset import CsvDatasetFileStore
from trader.adapters.outbound.persistence.manager import DatabaseManager
from trader.common import path
from trader.core.task.use_cases.data_tasks import ImportCsvTaskRunner
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig


class ImportCSVTask(BaseTask):
    def __init__(
        self,
        tcfg: TaskConfig,
        cfg,
        log,
        db_manager: DatabaseManager,
        exchange: BinanceExchange,
    ):
        super().__init__(tcfg, cfg, log, db_manager, exchange)

    async def start(self, queue: Queue):
        if not self.tcfg.csv:
            self.log.error(f"No config data_file for {self.tcfg.to_dict()}")
            return
        if not self.db_manager:
            self.log.error(f"No config db_uri for {self.tcfg.to_dict()}")
            return

        await super().start(queue)
        runner = ImportCsvTaskRunner(
            kline_repository=self.db_manager.kline,
            file_store=CsvDatasetFileStore(),
            task_repository=getattr(self.db_manager, "task", None),
            data_dir=path.GetDataDir(),
            log=self.log,
        )
        await runner.run(self.tcfg, queue=queue, task_state=self.ts)
