"""Managed task handle base: lifecycle state, quit signal, and repository persistence."""

from __future__ import annotations

import asyncio
from asyncio import Event, Queue
from datetime import datetime

from trader.core.exchange.interfaces import ExchangeClient
from trader.core.shared.config import Config
from trader.core.shared.interfaces import LoggerPort
from trader.core.task.config import TaskConfig
from trader.core.task.config_codec import TaskConfigCodec
from trader.core.task.domain import TaskStateType
from trader.core.task.interfaces import TaskRepository, TaskRunner


class ManagedTask:
    """Base handle for a running task: owns its state snapshot and quit signal."""

    def __init__(
        self,
        tcfg: TaskConfig,
        cfg: Config,
        log: LoggerPort,
        task_repository: TaskRepository | None = None,
        exchange: ExchangeClient | None = None,
    ):
        self.log = log
        self.cfg = cfg
        # Accept either a task repository or a database manager exposing ``.task``.
        self.task_repository = getattr(task_repository, "task", task_repository)
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

    async def start(self, queue: Queue | None):
        self.start_time = datetime.now()
        self.log.info(f"Start {self.name()}")
        self.ts.state = TaskStateType.RUNNING
        await self._persist_state()

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

    async def _persist_state(self):
        if self.task_repository is None:
            return
        await self.task_repository.add_tasks([self.ts])


class RunnerTaskHandle(ManagedTask):
    """Managed task handle that delegates execution to an injected TaskRunner."""

    def __init__(
        self,
        *,
        runner: TaskRunner,
        tcfg: TaskConfig,
        cfg: Config,
        log: LoggerPort,
        task_repository: TaskRepository | None = None,
        exchange: ExchangeClient | None = None,
        include_symbol_in_name: bool = True,
    ):
        super().__init__(tcfg, cfg, log, task_repository, exchange)
        self._runner = runner
        self._include_symbol_in_name = include_symbol_in_name

    def name(self):
        if self._include_symbol_in_name:
            return super().name()
        return f"{self.tcfg.id}.{self.type().name}"

    async def start(self, queue: Queue | None):
        await super().start(queue)
        await self._runner.run(self.tcfg, queue=queue, quit_event=self.quit, task_state=self.ts)
        self.stop()
