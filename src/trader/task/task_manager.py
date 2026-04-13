import asyncio
from asyncio import Queue
from concurrent.futures import ProcessPoolExecutor
import os
from pathlib import Path

from trader.common.common import sleep
from trader.common.config import Config
from trader.common.log_tag import LogTag
from trader.common.logger import Logger
from trader.common.message import new_add_tasks_msg, new_exit_msg, new_stat_msg
from trader.database.manager import DatabaseManager
from trader.exchange.binance.exchange import BinanceExchange
from trader.statistics.stat import BackTraderStat
from trader.strategy.trader_result import parse_trader_result
from trader.task.backtrader_task import BackTraderTask, build_backtest_sample_spec, run_backtest_sample
from trader.task.base_task import BaseTask
from trader.task.check_klines_num_task import CheckKlinesNumTask
from trader.task.check_klines_task import CheckKlinesTask
from trader.task.debug_task import DebugTask
from trader.task.dataset_resolver import DatasetResolver
from trader.task.import_csv_task import ImportCSVTask
from trader.task.optimization_report import write_optimization_artifacts
from trader.task.task_config import TaskConfig, parse_task_config
from trader.task.task_type import TaskType
from trader.task.trader_task import TraderTask
from trader.task.update_klines_task import UpdateKlinesTask
from trader.utils.symbol_interval import SymbolInterval
from trader.utils.task_state import TaskState


class TaskManager:
    def __init__(
        self,
        cfg: Config,
        log: Logger,
        db_manager: DatabaseManager,
        exchange: BinanceExchange,
    ):
        self.log = log
        self.cfg = cfg
        self.db_manager = db_manager
        self.exchange = exchange
        self.log.info("Init TaskManager")
        self.tasks: dict[int, BaseTask] = {}
        self.async_tasks = []
        self.latest_si: SymbolInterval | None = None

    def start(self):
        self.log.info("TaskManager start")
        if self.cfg.tasks:
            taskcs = parse_task_config(self.cfg.tasks)
            if len(taskcs) <= 0:
                return None
            return new_add_tasks_msg(taskcs)
        return None

    def stop(self):
        pass

    async def close(self):
        for ts in self.tasks.values():
            ts.close()

        await asyncio.gather(*self.async_tasks)

    def add_tasks(self, taskcs: list[TaskConfig], queue: Queue):

        def on_done(t):
            exc = t.exception()
            if exc:
                self.log.error(f"Exception:{exc}")

        task = asyncio.create_task(self.do_add_tasks(taskcs, queue))
        task.add_done_callback(on_done)
        self.async_tasks.append(task)

    async def do_add_tasks(self, taskcs: list[TaskConfig], queue: Queue):
        if len(taskcs) <= 0:
            self.log.error("Empty task config for add")
            return

        self.log.info(f"Try to add tasks:{len(taskcs)}")

        async_tasks = []
        bttaskcs = []
        for taskc in taskcs:
            if taskc.free < 0:
                taskc.free = self.cfg.cash

            if taskc.ttype == TaskType.BACK_TRADER:
                bttaskcs.append(taskc)
            if taskc.symbol_interval:
                self.latest_si = taskc.symbol_interval

        if len(bttaskcs) > 0:
            async_tasks.append(asyncio.create_task(self.add_backtrader_task(bttaskcs, queue)))

        for taskc in taskcs:
            if taskc.ttype == TaskType.BACK_TRADER:
                continue
            async_tasks.append(asyncio.create_task(self.add_task(taskc, queue)))

        self.log.info(f"All tasks are created to running:{len(async_tasks)}")
        await asyncio.gather(*async_tasks)

        for tc in taskcs:
            task = self.get_task(tc.id)
            if task:
                task.stop()
                self.tasks.pop(tc.id)

        if not self.cfg.is_server():
            self.log.info("Try to actively exit")
            await queue.put(new_exit_msg())

    async def add_task(self, cfg, queue: Queue):
        task = None
        if cfg.ttype == TaskType.TRADER:
            task = TraderTask(cfg, self.cfg, self.log, self.db_manager, self.exchange)
        elif cfg.ttype == TaskType.BACK_TRADER:
            task = BackTraderTask(cfg, self.cfg, self.log, self.db_manager, self.exchange)
        elif cfg.ttype == TaskType.UPDATE_KLINES:
            task = UpdateKlinesTask(cfg, self.cfg, self.log, self.db_manager, self.exchange)
        elif cfg.ttype == TaskType.CHECK_KLINES:
            task = CheckKlinesTask(cfg, self.cfg, self.log, self.db_manager, self.exchange)
        elif cfg.ttype == TaskType.IMPORT_CSV:
            task = ImportCSVTask(cfg, self.cfg, self.log, self.db_manager, self.exchange)
        elif cfg.ttype == TaskType.CHECK_KLINES_NUM:
            task = CheckKlinesNumTask(cfg, self.cfg, self.log, self.db_manager, self.exchange)
        elif cfg.ttype == TaskType.DEBUG:
            task = DebugTask(cfg, self.cfg, self.log, self.db_manager)

        if task is None:
            self.log.error(f"Can't add task:{cfg.to_dict()}")
            return
        self.tasks[task.id()] = task

        await task.start(queue)

    async def add_backtrader_task(self, cfgs, queue: Queue):
        failures = await self._prepare_backtest_datasets(cfgs)
        failed_task_ids = {failure["task_id"] for failure in failures}
        sample_specs = []
        task_by_id = {}
        for cfg in cfgs:
            if cfg.id in failed_task_ids:
                continue
            task = BackTraderTask(cfg, self.cfg, self.log, self.db_manager, self.exchange)
            self.tasks[task.id()] = task
            BaseTask.start(task, queue)
            task_by_id[task.id()] = task
            sample_specs.append(build_backtest_sample_spec(self.cfg, cfg))

        sample_records = []
        execution_failures = []
        sample_results = await self._execute_sample_specs(sample_specs)
        for sample_result in sample_results:
            task = task_by_id.get(sample_result.task_id)
            if task is None:
                continue

            for log_str in sample_result.logs:
                self.log.add_log_buffer(log_str, LogTag.STRATEGY)

            if not sample_result.ok or sample_result.trader_result is None:
                self.log.error(
                    f"Backtest sample failed: task_id={sample_result.task_id}, error={sample_result.error}",
                    LogTag.STRATEGY,
                )
                execution_failures.append(
                    {
                        "task_id": sample_result.task_id,
                        "dataset_key": getattr(task.tcfg.dataset_ref, "dataset_key", None),
                        "reason": "execution_failed",
                        "message": sample_result.error or "backtest execution failed",
                    }
                )
                continue

            task.ts.tret = parse_trader_result(sample_result.trader_result)
            msg = new_stat_msg(
                BackTraderStat(task.tcfg.strategy_name(), task.tcfg.symbol_interval.name(), task.ts),
                task.id(),
            )
            self.log.info(f"Relay process queue message:{msg.name()}", LogTag.STRATEGY)
            await queue.put(msg)
            sample_records.append(
                {
                    "task_id": sample_result.task_id,
                    "report": sample_result.report,
                    "report_path": sample_result.report_path,
                }
            )

        self._finalize_optimization_runs(cfgs, sample_records, failures + execution_failures)

    def _dataset_prepare_max_workers(self) -> int:
        cpu_count = os.cpu_count() or 1
        return max(1, min(4, cpu_count))

    def _sample_max_workers(self) -> int:
        return max(1, os.cpu_count() or 1)

    def _prepare_dataset_job_sync(self, resolver: DatasetResolver, symbol_interval, start_time: int, end_time: int, allow_download: bool):
        return asyncio.run(
            resolver.prepare(
                symbol_interval,
                start_time,
                end_time,
                allow_download=allow_download,
            )
        )

    async def _prepare_dataset_job(self, resolver: DatasetResolver, symbol_interval, start_time: int, end_time: int, allow_download: bool):
        return await asyncio.to_thread(
            self._prepare_dataset_job_sync,
            resolver,
            symbol_interval,
            start_time,
            end_time,
            allow_download,
        )

    async def _prepare_backtest_datasets(self, cfgs: list[TaskConfig]) -> list[dict]:
        if not cfgs:
            return []

        prepared_results = {}
        failures = []
        dataset_jobs = {}

        for cfg in cfgs:
            if cfg.ttype != TaskType.BACK_TRADER or cfg.csv:
                continue
            dataset_key = (cfg.symbol_interval.name(), cfg.start_time, cfg.end_time)
            if dataset_key not in dataset_jobs:
                dataset_jobs[dataset_key] = (
                    cfg.symbol_interval,
                    cfg.start_time,
                    cfg.end_time,
                    cfg.auto_download or cfg.optimization_run_id is not None,
                )

        semaphore = asyncio.Semaphore(self._dataset_prepare_max_workers())

        async def run_job(dataset_key, job):
            async with semaphore:
                resolver = DatasetResolver(self.db_manager, self.exchange, self.log)
                symbol_interval, start_time, end_time, allow_download = job
                prepared_results[dataset_key] = await self._prepare_dataset_job(
                    resolver,
                    symbol_interval,
                    start_time,
                    end_time,
                    allow_download,
                )

        await asyncio.gather(*(run_job(dataset_key, job) for dataset_key, job in dataset_jobs.items()))

        for cfg in cfgs:
            if cfg.ttype != TaskType.BACK_TRADER or cfg.csv:
                continue
            dataset_key = (cfg.symbol_interval.name(), cfg.start_time, cfg.end_time)
            result = prepared_results[dataset_key]
            if result.ok:
                cfg.dataset_ref = result.dataset_ref
                continue

            failures.append(
                {
                    "task_id": cfg.id,
                    "dataset_key": result.failure.dataset_key,
                    "reason": result.failure.reason,
                    "message": result.failure.message,
                }
            )

        return failures

    async def _execute_sample_specs(self, sample_specs):
        if not sample_specs:
            return []
        return await asyncio.to_thread(self._execute_sample_specs_sync, sample_specs)

    def _execute_sample_specs_sync(self, sample_specs):
        results = []
        with ProcessPoolExecutor(max_workers=self._sample_max_workers()) as executor:
            futures = [executor.submit(run_backtest_sample, spec) for spec in sample_specs]
            for future in futures:
                results.append(future.result())
        return results

    def _finalize_optimization_runs(self, cfgs: list[TaskConfig], sample_records: list[dict], failures: list[dict]):
        task_by_id = {cfg.id: cfg for cfg in cfgs}
        run_ids = sorted({cfg.optimization_run_id for cfg in cfgs if cfg.optimization_run_id})
        if not run_ids:
            return

        for run_id in run_ids:
            run_reports = []
            for record in sample_records:
                report = record.get("report")
                if not report or report.get("optimization_run_id") != run_id:
                    continue
                enriched_report = dict(report)
                if record.get("report_path"):
                    enriched_report["report_path"] = record["report_path"]
                run_reports.append(enriched_report)

            run_failures = []
            for failure in failures:
                task = task_by_id.get(failure.get("task_id"))
                if task and task.optimization_run_id == run_id:
                    run_failures.append(failure)

            write_optimization_artifacts(Path.cwd(), run_id, run_reports, run_failures)

    def get_task(self, id: int) -> BaseTask | None:
        if id in self.tasks:
            return self.tasks[id]
        return None

    def has_task(self, id: int) -> bool:
        return self.get_task(id) is not None

    def remove_task(self, id: int) -> BaseTask | None:
        if id in self.tasks:
            ret: BaseTask = self.tasks.pop(id)
            if ret:
                self.log.info(f"Remove task:id={id}")
                return ret
        return None

    def close_task(self, id: int):
        task = self.get_task(id)
        if task:
            task.close()
            return True
        return False

    def del_task(self, id: int):
        task = self.get_task(id)
        if task:
            task.close()
            while self.has_task(id):
                sleep(self.log, 1)

        return self.db_manager.task.del_task(id)

    def get_task_state(self, id: int) -> TaskState | None:
        task = self.get_task(id)
        if task:
            return task.ts
        if self.db_manager:
            return self.db_manager.task.get_task(id)

        return None

    def get_all_task_state(self) -> list[TaskState]:
        ret: list[TaskState] = []
        for ts in self.tasks.values():
            ret.append(ts.ts)

        if self.db_manager:
            tss = self.db_manager.task.get_all_tasks()
            for ts in tss:
                if self.has_task(ts.id):
                    continue
                ret.append(ts)

        return ret
