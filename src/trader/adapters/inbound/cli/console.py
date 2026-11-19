from __future__ import annotations

import asyncio
import signal
from asyncio import Event
from datetime import datetime
from typing import Any

from trader.core.shared.domain import NAME
from trader.core.shared.logging import LogTag
from trader.core.shared.messages import Message, new_exit_msg
from trader.core.task.use_cases.startup_self_check import evaluate_live_startup_self_check


class ConsoleRunner:
    """Thin CLI inbound adapter driving console-mode one-shot startup execution (ADR-0002)."""

    def __init__(self, container: Any):
        self.container = container
        self.cfg = container.cfg
        self.logger = container.logger
        self.db_manager = container.db_manager
        self.exchange = container.exchange
        self.tasks_cfg = list(getattr(container, "tasks_cfg", []) or [])
        self.notify_mgr = container.notify_mgr
        self.stat = container.stat
        self.task_manager = container.task_manager
        self.queue: asyncio.Queue | None = None
        self.started_at = datetime.now()

    def run(self) -> bool:
        self.logger.info(
            f"Start {NAME} App, config:{self.cfg.safe_to_dict() if hasattr(self.cfg, 'safe_to_dict') else self.cfg}, running mode:CLI",
            LogTag.PRIVATE,
        )
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        async def _execute() -> bool:
            await self._bootstrap_database()
            msgs = await self._prepare_start_messages()
            if msgs is None:
                if self.db_manager and getattr(self.db_manager, "started", False):
                    await self.db_manager.stop()
                return False
            quit_event = asyncio.Event()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, self.shutdown, quit_event)
                except NotImplementedError:
                    pass
            await self.handle_messages(msgs, quit_event)
            return True

        completed = False
        try:
            completed = loop.run_until_complete(_execute())
        except asyncio.CancelledError:
            self.logger.debug("All tasks have been cancelled.")
            completed = False
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
            loop.close()
            if completed:
                self.stop()
            self.logger.info(f"{NAME} tasks exited.")
        return completed

    async def _bootstrap_database(self) -> None:
        if not self.db_manager:
            return
        if not getattr(self.db_manager, "started", False):
            await self.db_manager.start()
            bootstrap_fn = getattr(self.container, "bootstrap_admin_fn", None)
            if callable(bootstrap_fn):
                res = bootstrap_fn()
                if asyncio.iscoroutine(res):
                    await res
        if not self.tasks_cfg:
            return
        startup_admin = await self.db_manager.get_startup_admin()
        if startup_admin is None:
            raise RuntimeError("startup tasks require an administrator account")
        for taskc in self.tasks_cfg:
            taskc.user_id = startup_admin.id

    async def _prepare_start_messages(self) -> list[Message] | None:
        if getattr(self.cfg, "tasks", None) is None:
            self.logger.warning("No tasks can be executed")
            return None

        self.notify_mgr.start()
        if self.exchange:
            self.exchange.start()

        msgs: list[Message] = []
        if self.task_manager:
            if self.exchange and self.tasks_cfg:
                self_check = evaluate_live_startup_self_check(
                    self.exchange, self.tasks_cfg, strategy_loader=self.container.strategy_loader
                )
                self.logger.info(f"Startup self-check: {self_check.summary()}", LogTag.PRIVATE)
                if not self_check.passed:
                    self.logger.warning(f"Startup self-check details: {self_check.to_dict()}", LogTag.PRIVATE)
            try:
                msg = self.task_manager.start(self.tasks_cfg)
            except TypeError:
                msg = self.task_manager.start()
            if msg:
                msgs.append(msg)
            elif getattr(self.cfg, "tasks", None):
                self.logger.warning("No valid tasks can be executed")
                return None
        return msgs

    async def handle_messages(self, msgs: list[Message], quit_event: Event) -> None:
        queue: asyncio.Queue = asyncio.Queue()
        self.queue = queue

        startup_admin_id = None
        if self.db_manager and (self.tasks_cfg or any(msg.is_add_tasks() for msg in msgs)):
            startup_admin = await self.db_manager.get_startup_admin()
            if startup_admin is None:
                raise RuntimeError("startup tasks require an administrator account")
            startup_admin_id = startup_admin.id
            for taskc in self.tasks_cfg:
                taskc.user_id = startup_admin_id

        for msg in msgs:
            if startup_admin_id is not None and msg.is_add_tasks():
                for taskc in msg.get_data():
                    if getattr(taskc, "user_id", None) is None:
                        taskc.user_id = startup_admin_id
            await queue.put(msg)

        self.logger.info(f"{NAME} enter handler: init messages={len(msgs)}")
        try:
            while True:
                msg: Message = await queue.get()
                self.logger.debug(f"Processing message: {msg.name()}")
                if msg.is_exit():
                    self.logger.info("Received exit message, shutting down...")
                    break
                if msg.is_stat():
                    self.stat.handler(msg)
                    self.notify_mgr.handler(msg)
                elif msg.is_add_tasks():
                    self.task_manager.add_tasks(msg.get_data(), queue)
                queue.task_done()
            await self.task_manager.close()
        finally:
            if self.db_manager:
                await self.db_manager.stop()

        self.logger.info(f"{NAME} exit handler")

    def shutdown(self, quit_event: Event) -> None:
        self.logger.info(f"Received shutdown signal, stopping {NAME}...")
        quit_event.set()
        if self.queue:
            try:
                self.queue.put_nowait(new_exit_msg())
            except asyncio.QueueFull:
                self.logger.error("QueueFull")

    def stop(self) -> None:
        self.stat.report()
        if self.task_manager:
            self.task_manager.stop()
        if self.exchange:
            self.exchange.stop()
        elapsed = datetime.now() - self.started_at
        self.logger.info(f"Stop {NAME} App, elapsed time:{elapsed}")


def run_console(container: Any) -> bool:
    return ConsoleRunner(container).run()
