import os
from asyncio import Queue
from pathlib import Path

from trader.adapters.outbound.binance.exchange import BinanceExchange
from trader.adapters.outbound.files.dataset import CsvDatasetFileStore
from trader.adapters.outbound.persistence.manager import DatabaseManager
from trader.common import path
from trader.core.marketdata.use_cases.import_csv import import_csv_klines, parse_csv_kline_rows, validate_kline_interval
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

        data_file = self.tcfg.csv
        if not os.path.isabs(self.tcfg.csv):
            data_file = os.path.join(path.GetDataDir(), self.tcfg.csv)

        kls = parse_csv_kline_rows(CsvDatasetFileStore().read_rows(Path(data_file)))

        if len(kls) <= 0:
            self.log.error(f"No kline in {data_file}")
            return
        self.log.info(f"Read klines ({len(kls)}) from {data_file}")
        if not validate_kline_interval(kls, self.tcfg.symbol_interval):
            self.log.error(f"{self.name()} kline interval is not {self.tcfg.symbol_interval.interval.name}")
            return

        ret = await import_csv_klines(self.db_manager.kline, self.tcfg.symbol_interval.name(), kls)
        if ret != len(kls):
            self.log.warning(f"{self.name()} add klines to DB: {ret} != {len(kls)}")
        else:
            self.log.info(f"{self.name()} add klines to DB: {ret}")
