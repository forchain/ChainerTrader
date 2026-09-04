import asyncio
import json
import os
import signal
from asyncio import Event
from datetime import datetime

from trader.common import path
from trader.common.common import NAME
from trader.common.config import Config, default
from trader.common.log_tag import LogTag
from trader.common.logger import Logger
from trader.common.message import Message, new_add_tasks_msg, new_exit_msg
from trader.database.manager import DatabaseManager
from trader.exchange.binance.exchange import BinanceExchange
from trader.exchange.exchange_config import MarginMode, parse_exchange_config
from trader.exchange.exchange_type import ExchangeType
from trader.notify.notify_manager import NotifyManager
from trader.statistics.statistics import Statistics
from trader.task.live_startup_self_check import evaluate_live_startup_self_check, infer_required_margin_mode
from trader.task.persisted_live_config_migration import (
    assert_persisted_task_config_json_is_migrated,
    migrate_persisted_live_task_configs,
)
from trader.task.task_config import TaskConfig, apply_persisted_task_runtime_metadata, parse_task_config
from trader.task.task_manager import TaskManager

RECOVERY_TASK_CONCURRENCY = 10


class App:
    def __init__(self, cfg: Config = default()):
        self.cfg = cfg
        self.logger = Logger(cfg)

        self.logger.info(f"Init App {self.name()}")

        self.db_manager = None
        self.exchange = None
        self.tasks_cfg: list[TaskConfig] = []

        if self.cfg.db:
            self.db_manager = DatabaseManager(cfg, self.logger)

        if self.cfg.tasks:
            self.tasks_cfg = parse_task_config(self.cfg.tasks)

        if self.cfg.exchange:
            ex_cfg = parse_exchange_config(self.cfg.exchange)
            if ex_cfg and ex_cfg.ty == ExchangeType.BINANCE:
                required_margin_mode = infer_required_margin_mode(self.tasks_cfg)
                if required_margin_mode == MarginMode.CROSS_MARGIN and ex_cfg.margin_mode == MarginMode.SPOT:
                    ex_cfg = ex_cfg.with_margin_mode(MarginMode.CROSS_MARGIN)
                self.exchange = BinanceExchange(ex_cfg, self.log())

        self.notify_mgr = NotifyManager(cfg, self.logger)

        self.stat = Statistics(self.cfg, self.log(), self.db_manager)
        self.task_manager = TaskManager(self.cfg, self.logger, self.db_manager, self.exchange)

        self.startTime = datetime.now()
        self.queue = None
        self.recovery_task: asyncio.Task | None = None
        self._running_task_configs_to_recover: list[TaskConfig] | None = None

    def name(self):
        return NAME

    def log(self):
        return self.logger.log()

    def get_running_mode(self) -> str:
        if self.cfg.is_server():
            return "server"
        return "CLI"

    def start(self):
        self.logger.info(f"Start {self.name()} App, config:{self.cfg.safe_to_dict()}, running mode:{self.get_running_mode()}", LogTag.PRIVATE)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        async def _run():
            await self.bootstrap_database_for_startup()
            msgs = await self._prepare_start_messages()
            if msgs is None:
                if self.db_manager and getattr(self.db_manager, "started", False):
                    await self.db_manager.stop()
                return False
            quit = asyncio.Event()
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, self.shutdown, quit)
            await self.handler(msgs, quit)
            return True

        try:
            return loop.run_until_complete(_run())
        except asyncio.CancelledError:
            self.logger.debug("All tasks have been cancelled.")
            return False
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
            loop.close()
            self.logger.info(f"{self.name()} tasks exited.")

    async def start_async(self):
        self.logger.info(f"Start {self.name()} App, config:{self.cfg.safe_to_dict()}, running mode:{self.get_running_mode()}", LogTag.PRIVATE)

        await self.bootstrap_database_for_startup()
        result = await self._prepare_start_messages()
        if result is None:
            return False
        self.process(result)
        return True

    def _bootstrap_database_for_startup_sync(self):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.bootstrap_database_for_startup())
        return None

    async def bootstrap_database_for_startup(self):
        if not self.db_manager:
            return None
        if not getattr(self.db_manager, "started", False):
            await self.db_manager.start()
        if self.cfg.is_server() or not self.tasks_cfg:
            return None
        startup_admin = await self.db_manager.get_startup_admin()
        if startup_admin is None:
            raise RuntimeError("startup tasks require an administrator account")
        for taskc in self.tasks_cfg:
            taskc.user_id = startup_admin.id
        return startup_admin.id

    async def _prepare_start_messages(self) -> list[Message] | None:
        if not self.cfg.is_server():
            if self.cfg.tasks is None:
                self.logger.warning("No tasks can be executed")
                return None

        self.notify_mgr.start()

        if self.exchange:
            self.exchange.start()

        msgs: list[Message] = []
        if self.task_manager:
            if self.cfg.is_server():
                startup_taskcs = []
            else:
                startup_taskcs = await self._startup_task_configs_to_start()
                if self.exchange and startup_taskcs:
                    self.startup_self_check = evaluate_live_startup_self_check(self.exchange, startup_taskcs)
                    self.logger.info(f"Startup self-check: {self.startup_self_check.summary()}", LogTag.PRIVATE)
                    if not self.startup_self_check.passed:
                        self.logger.warning(f"Startup self-check details: {self.startup_self_check.to_dict()}", LogTag.PRIVATE)
            if not self.cfg.is_server():
                try:
                    msg = self.task_manager.start(startup_taskcs)
                except TypeError:
                    msg = self.task_manager.start()
                if msg:
                    msgs.append(msg)
                elif self.cfg.tasks and not self.cfg.is_server():
                    self.logger.warning("No valid tasks can be executed")
                    return None

        return msgs

    async def _load_running_task_configs(self) -> list[TaskConfig]:
        if not self.db_manager or not getattr(self.db_manager, "task", None):
            return []
        task_repo = self.db_manager.task
        if not hasattr(task_repo, "get_all_tasks"):
            return []

        states = await task_repo.get_all_tasks()
        taskcs = []
        recovery_errors: list[RuntimeError] = []
        for state in states:
            if getattr(getattr(state, "state", None), "name", None) != "RUNNING":
                continue
            saved_config = {}
            try:
                config_json = getattr(state, "config_json", None)
                if not config_json:
                    raise RuntimeError(f"persisted running task({getattr(state, 'id', 'unknown')}) is missing config_json")
                saved_config = self._first_task_config(config_json)
                assert_persisted_task_config_json_is_migrated(config_json)
                recovered = parse_task_config(config_json)
            except Exception as exc:
                task_kind = "live task" if self._is_persisted_live_task_config(saved_config) else "running task"
                if str(exc).startswith("persisted running task("):
                    message = str(exc)
                else:
                    message = f"persisted {task_kind}({getattr(state, 'id', 'unknown')}) recovery failed: {exc}"
                error = RuntimeError(message)
                recovery_errors.append(error)
                self.logger.error(message)
                continue
            for taskc in recovered:
                taskc.id = int(getattr(state, "id", taskc.id) or taskc.id)
                if getattr(state, "user_id", None) is not None:
                    taskc.user_id = state.user_id
                if saved_config.get("run_id"):
                    taskc.run_id = saved_config["run_id"]
                apply_persisted_task_runtime_metadata(taskc, saved_config)
            taskcs.extend(recovered)

        if taskcs:
            self.logger.info(f"Recovered {len(taskcs)} running task config(s) from persisted state")
        elif recovery_errors:
            raise recovery_errors[0]
        return taskcs

    async def _running_task_configs_for_recovery(self) -> list[TaskConfig]:
        if self._running_task_configs_to_recover is None:
            self._running_task_configs_to_recover = await self._load_running_task_configs()
        return self._running_task_configs_to_recover

    async def _startup_task_configs_to_start(self) -> list[TaskConfig]:
        if not self.cfg.is_server() or not self.tasks_cfg:
            return self.tasks_cfg

        running_taskcs = await self._running_task_configs_for_recovery()
        if not running_taskcs:
            return self.tasks_cfg

        self.logger.info(
            f"Skip {len(self.tasks_cfg)} startup task config(s) because {len(running_taskcs)} running task(s) are pending recovery"
        )
        return []

    def _schedule_recovery_tasks(self) -> None:
        if not self.cfg.is_server():
            return
        if self.recovery_task is not None:
            return
        self.recovery_task = asyncio.create_task(self._recover_running_tasks_in_background())
        self.recovery_task.add_done_callback(self._on_recovery_task_done)

    def _on_recovery_task_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        try:
            task.result()
        except Exception:
            self.log().exception("Running task recovery failed")

    async def _recover_running_tasks_in_background(self) -> None:
        if not self.queue or not self.task_manager:
            return

        taskcs = await self._running_task_configs_for_recovery()
        if not taskcs:
            return

        semaphore = asyncio.Semaphore(RECOVERY_TASK_CONCURRENCY)

        async def _recover(taskc: TaskConfig):
            async with semaphore:
                await self.task_manager.recover_task(taskc, self.queue)

        await asyncio.gather(*[asyncio.create_task(_recover(taskc)) for taskc in taskcs])

    @staticmethod
    def _first_task_config(config_json: str) -> dict:
        try:
            payload = json.loads(config_json or "[]")
        except (TypeError, json.JSONDecodeError):
            return {}
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            return payload[0]
        return {}

    @staticmethod
    def _is_persisted_live_task_config(saved_config: dict) -> bool:
        return str(saved_config.get("task_type") or "").strip().upper() == "TRADER"

    def stop(self):
        self.stat.report()

        if self.task_manager:
            self.task_manager.stop()

        if self.exchange:
            self.exchange.stop()

        elapsed = datetime.now() - self.startTime
        self.logger.info(f"Stop {self.name()} App, elapsed time:{elapsed}")

    def version(self):
        return version()

    def info(self):
        return {
            "name": self.name(),
            "version": self.version(),
            "commission": self.cfg.commission,
            "period": self.cfg.period,
            "mode": self.get_running_mode(),
        }

    def config(self):
        return self.cfg

    def process(self, msgs: list[Message]):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        quit = asyncio.Event()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self.shutdown, quit)
        try:
            loop.run_until_complete(self.handler(msgs, quit))
        except asyncio.CancelledError:
            self.logger.debug("All tasks have been cancelled.")
        finally:
            loop.run_until_complete(loop.shutdown_asyncgens())
            loop.run_until_complete(loop.shutdown_default_executor())
            loop.close()
            self.logger.info(f"{self.name()} tasks exited.")

    def _mark_handler_ready(self):
        pass

    def shutdown(self, quit: Event):
        self.logger.info(f"Received shutdown signal, stopping {self.name()}...")
        self.exit_handle(quit)

    async def handler(self, msgs: list[Message], quit: Event):
        startup_admin_id = None
        if self.db_manager:
            if not getattr(self.db_manager, "started", False):
                await self.db_manager.start()
            if (not self.cfg.is_server() and self.tasks_cfg) or any(msg.is_add_tasks() for msg in msgs):
                startup_admin = await self.db_manager.get_startup_admin()
                if startup_admin is None:
                    raise RuntimeError("startup tasks require an administrator account")
                startup_admin_id = startup_admin.id
                if not self.cfg.is_server():
                    for taskc in self.tasks_cfg:
                        taskc.user_id = startup_admin_id

        queue = asyncio.Queue()
        self.queue = queue

        for msg in msgs:
            if startup_admin_id is not None and msg.is_add_tasks():
                for taskc in msg.get_data():
                    if getattr(taskc, "user_id", None) is None:
                        taskc.user_id = startup_admin_id
            await queue.put(msg)

        self.logger.info(f"{self.name()} enter handler: init messages={len(msgs)}")
        self._mark_handler_ready()
        self._schedule_recovery_tasks()

        try:
            while True:
                msg: Message = await queue.get()
                self.logger.debug(f"Processing message: {msg.name()}")
                if msg.is_exit():
                    self.logger.info("Received exit message, shutting down...")
                    break
                elif msg.is_stat():
                    self.stat.handler(msg)
                    self.notify_mgr.handler(msg)

                elif msg.is_add_tasks():
                    self.task_manager.add_tasks(msg.get_data(), queue)

                queue.task_done()

            await self.task_manager.close()
        finally:
            if self.recovery_task and not self.recovery_task.done():
                self.recovery_task.cancel()
                try:
                    await self.recovery_task
                except asyncio.CancelledError:
                    pass
            if self.db_manager:
                await self.db_manager.stop()

        self.logger.info(f"{self.name()} exit handler")

    def exit_handle(self, quit: Event):
        quit.set()
        self.send_exit_msg()

    def send_exit_msg(self):
        if self.queue:
            try:
                self.queue.put_nowait(new_exit_msg())
            except asyncio.QueueFull:
                self.logger.error("QueueFull")

    def send_add_tasks_msg(self, tasks_cfg: str, user_id: int | None = None):
        taskcs: list[TaskConfig] = []
        if tasks_cfg:
            taskcs = parse_task_config(tasks_cfg)
        if user_id is not None:
            for taskc in taskcs:
                taskc.user_id = user_id

        if len(taskcs) <= 0:
            return {
                "result": "fail",
                "error": "The input parameter is empty",
            }

        msg = new_add_tasks_msg(taskcs)

        self.queue.put_nowait(msg)

        ids = []
        for tc in taskcs:
            ids.append(tc.to_dict())
        return {"result": "success", "tasks": ids}

    async def migrate_persisted_live_task_configs(self):
        if not self.db_manager:
            raise RuntimeError("database configuration is required for persisted live config migration")

        started_here = False
        if not getattr(self.db_manager, "started", False):
            await self.db_manager.start()
            started_here = True

        try:
            task_repo = getattr(self.db_manager, "task", None)
            if task_repo is None or not hasattr(task_repo, "get_all_tasks") or not hasattr(task_repo, "add_tasks"):
                raise RuntimeError("task persistence is unavailable for persisted live config migration")
            return await migrate_persisted_live_task_configs(task_repo)
        finally:
            if started_here:
                await self.db_manager.stop()


def version():
    filePath = os.path.join(path.GetTraderDir(), "VERSION")

    with open(filePath, "r", encoding="utf-8") as file:
        content = file.read()
        return content
