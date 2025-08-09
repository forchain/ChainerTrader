from asyncio import Event, Queue
from datetime import datetime
from logging import Logger

from pymongo.synchronous.collection import Collection

from trader.app.database_manager import DatabaseManager
from trader.exchange.binance.exchange import BinanceExchange
from trader.common.common import sleep
from trader.common.config import Config
from trader.task.base_task import BaseTask
from trader.task.task_config import TaskConfig
from trader.utils.symbol_interval import SymbolInterval, add_time_duration

DOWLOAD_SPACE_TIME = 5


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

    async def start(self, queue: Queue, quit: Event):
        if not self.exchange:
            self.log.error(f"No config exchange for {self.tcfg.to_dict()}")
            return
        if not self.db_manager:
            self.log.error(f"No config db_uri for {self.tcfg.to_dict()}")
            return

        super().start(queue, quit)

        self.collection = self.db_manager.get_collection(self.cfg.db_name, self.tcfg.symbol_interval.name())
        start_time = self.tcfg.start_time
        if self.tcfg.limit > 0:
            if self.tcfg.end_time > 0:
                start_time = add_time_duration(
                    self.tcfg.end_time,
                    self.tcfg.symbol_interval.interval,
                    -self.tcfg.limit,
                )
            else:
                latest_kline = self.db_manager.get_latest_kline(self.collection)
                if latest_kline:
                    start_time = add_time_duration(
                        latest_kline.open_time,
                        self.tcfg.symbol_interval.interval,
                        -self.tcfg.limit,
                    )
                else:
                    start_time = add_time_duration(
                        int(datetime.now().timestamp()),
                        self.tcfg.symbol_interval.interval,
                        -self.tcfg.limit,
                    )

        await download(
            self.name(),
            self.log,
            self.db_manager,
            self.collection,
            self.exchange,
            self.tcfg.symbol_interval,
            start_time,
            quit,
        )

        self.stop()


async def download(
    name,
    log: Logger,
    db_manager: DatabaseManager,
    collection: Collection,
    exchange: BinanceExchange,
    symbol_interval: SymbolInterval,
    start_time: int,
    quit: Event,
):
    update_completed = False
    max_try = 5
    total_records = 0
    while not update_completed:
        if quit.is_set():
            log.info(f"exit {name}. total={total_records}")
            return False

        latest_kline = db_manager.get_latest_kline(collection)
        if latest_kline is None:
            kls = exchange.get_klines_by_start(symbol_interval, start_time)
        else:
            next_time = add_time_duration(latest_kline.open_time, symbol_interval.interval, 1)
            if next_time < int(datetime.now().timestamp()):
                kls = exchange.get_klines_by_start(symbol_interval, next_time)
            else:
                update_completed = True
                log.info(f"{name} update klines to DB is completed. total={total_records}")
                continue
        if kls is None or len(kls) <= 0:
            log.error(f"{name} get klines is empty")
            if max_try > 0:
                await sleep(log, DOWLOAD_SPACE_TIME, f"next try {max_try}, {name}")
                max_try -= 1
                continue
            else:
                log.warning(f"exit {name}, because get empty klines. total={total_records}")
                return False

        ret = db_manager.add_klines(collection, kls)
        total_records += ret

        if ret != len(kls):
            log.warning(f"{name} add klines to DB: {ret} != {len(kls)}")
        else:
            log.info(f"{name} add klines to DB: {ret}/{total_records}")

        # await sleep(log,DOWLOAD_SPACE_TIME,name)

    return True


async def download_test(
    name,
    log: Logger,
    db_manager: DatabaseManager,
    collection: Collection,
    exchange: BinanceExchange,
    symbol_interval: SymbolInterval,
    quit: Event,
):
    update_completed = False
    while not update_completed:
        if quit.is_set():
            log.info(f"exit {name}")
            return False

        await sleep(log, DOWLOAD_SPACE_TIME, name)

    return True
