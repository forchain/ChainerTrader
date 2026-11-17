import asyncio
from asyncio import Event, Queue
from datetime import datetime

from trader.common.config import Config
from trader.common.logger import Logger
from trader.database.manager import DatabaseManager
from trader.exchange.binance.exchange import BinanceExchange
from trader.task.task_config import TaskConfig
from trader.task.task_config_codec import TaskConfigCodec
from trader.utils.task_state import TaskStateType


class BaseTask:
    def __init__(
        self,
        tcfg: TaskConfig,
        cfg: Config,
        log: Logger,
        db_manager: DatabaseManager = None,
        exchange: BinanceExchange = None,
    ):
        self.log = log
        self.cfg = cfg
        self.db_manager = db_manager
        self.exchange = exchange
        self.tcfg = tcfg
        self.log.info(f"Init {self.name()}")
        self.start_time = datetime.now()
        self.quit: Event = asyncio.Event()

        self.ts = TaskConfigCodec.to_task_state(
            tcfg,
            name=self.name(),
            start_time=self.start_time,
            commission=self.cfg.commission,
            initial_cash=cfg.cash if tcfg.free < 0 else tcfg.free,
        )

    def start(self, queue: Queue):
        self.start_time = datetime.now()
        self.log.info(f"Start {self.name()}")
        self.ts.state = TaskStateType.RUNNING
        return self._persist_state()

    def stop(self):
        if not self.ts.is_running():
            return
        self.ts.state = TaskStateType.DONE
        self.close()
        elapsed = datetime.now() - self.start_time
        self.log.info(f"Stop {self.name()}, elapsed time:{elapsed}")

    def name(self):
        return f"{self.tcfg.id}.{self.type().name}.{self.tcfg.symbol_interval.name()}"

    def type(self):
        return self.tcfg.ttype

    def id(self) -> int:
        return self.tcfg.id

    def close(self):
        self.quit.set()

    def _persist_state(self):
        task_store = getattr(self.db_manager, "task", None)
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if task_store is None:
            if loop is not None:
                return asyncio.sleep(0)
            return

        async def _save():
            await task_store.add_tasks([self.ts])

        if loop is None:
            asyncio.run(_save())
        else:
            return loop.create_task(_save())
