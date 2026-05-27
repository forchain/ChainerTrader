import asyncio
import inspect
import os
from asyncio import Queue
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path

from trader.auth.credentials import decrypt_secret, service_key_available
from trader.common.common import sleep
from trader.common.config import Config
from trader.common.log_tag import LogTag
from trader.common.logger import Logger
from trader.common.message import new_add_tasks_msg, new_exit_msg, new_stat_msg
from trader.database.manager import DatabaseManager
from trader.exchange.binance.exchange import BinanceExchange
from trader.exchange.exchange_config import MarginMode
from trader.live.auto_execution import is_real_auto_mode
from trader.statistics.stat import BackTraderStat
from trader.strategy.trader_result import parse_trader_result
from trader.task.backtrader_task import BacktestSampleResult, BackTraderTask, build_backtest_sample_spec, run_backtest_sample
from trader.task.base_task import BaseTask
from trader.task.check_klines_num_task import CheckKlinesNumTask
from trader.task.check_klines_task import CheckKlinesTask
from trader.task.dataset_resolver import DatasetPreparationFailure, DatasetPreparationResult, DatasetResolver
from trader.task.debug_task import DebugTask
from trader.task.import_csv_task import ImportCSVTask
from trader.task.live_startup_self_check import infer_required_margin_mode, task_requires_short_capability
from trader.task.optimization_report import write_optimization_artifacts
from trader.task.optimization_runtime import OptimizationRuntimeStatus, evaluate_abort_reason
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
        self._exchange_by_mode: dict[str, BinanceExchange] = {}
        if getattr(exchange, "margin_mode", None) is not None:
            self._exchange_by_mode[exchange.margin_mode.value] = exchange
        self.log.info("Init TaskManager")
        self.tasks: dict[int, BaseTask] = {}
        self.async_tasks = []
        self.latest_si: SymbolInterval | None = None

    def start(self, taskcs: list[TaskConfig] | None = None):
        self.log.info("TaskManager start")
        if taskcs is None and self.cfg.tasks:
            taskcs = parse_task_config(self.cfg.tasks)
        if taskcs is not None:
            required_margin_mode = infer_required_margin_mode(taskcs)
            if getattr(self.exchange, "margin_mode", None) is not None and required_margin_mode.value != self.exchange.margin_mode.value:
                self.log.info(
                    f"TaskManager mixed-mode detected: required_margin_mode={required_margin_mode.value}, "
                    f"default_exchange_margin_mode={self.exchange.margin_mode.value}. Per-task exchange routing enabled."
                )
        if taskcs:
            if len(taskcs) <= 0:
                return None
            return new_add_tasks_msg(taskcs)
        return None

    def stop(self):
        pass

    async def close(self):
        closing_states = []
        for task in self.tasks.values():
            task.close()
            closing_states.append(task.ts)

        await asyncio.gather(*self.async_tasks)
        await self._persist_task_states(closing_states)

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
        await self._ensure_routed_exchanges(taskcs)

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

        completed_states = []
        for tc in taskcs:
            task = self.get_task(tc.id)
            if task:
                task.stop()
                completed_states.append(task.ts)
                self.tasks.pop(tc.id)

        await self._persist_task_states(completed_states)

        if not self.cfg.is_server():
            self.log.info("Try to actively exit")
            await queue.put(new_exit_msg())

    async def _persist_task_states(self, states: list[TaskState]) -> None:
        if not self.db_manager or not getattr(self.db_manager, "task", None):
            return
        if states:
            await self.db_manager.task.add_tasks(states)

    async def add_task(self, cfg, queue: Queue):
        task = None
        task_exchange = await self._exchange_for_task(cfg)
        if cfg.ttype == TaskType.TRADER:
            task = TraderTask(cfg, self.cfg, self.log, self.db_manager, task_exchange)
        elif cfg.ttype == TaskType.BACK_TRADER:
            task = BackTraderTask(cfg, self.cfg, self.log, self.db_manager, task_exchange)
        elif cfg.ttype == TaskType.UPDATE_KLINES:
            task = UpdateKlinesTask(cfg, self.cfg, self.log, self.db_manager, task_exchange)
        elif cfg.ttype == TaskType.CHECK_KLINES:
            task = CheckKlinesTask(cfg, self.cfg, self.log, self.db_manager, task_exchange)
        elif cfg.ttype == TaskType.IMPORT_CSV:
            task = ImportCSVTask(cfg, self.cfg, self.log, self.db_manager, task_exchange)
        elif cfg.ttype == TaskType.CHECK_KLINES_NUM:
            task = CheckKlinesNumTask(cfg, self.cfg, self.log, self.db_manager, task_exchange)
        elif cfg.ttype == TaskType.DEBUG:
            task = DebugTask(cfg, self.cfg, self.log, self.db_manager)

        if task is None:
            self.log.error(f"Can't add task:{cfg.to_dict()}")
            return
        self.tasks[task.id()] = task

        await task.start(queue)

    async def _exchange_for_task(self, cfg: TaskConfig) -> BinanceExchange:
        if cfg.ttype != TaskType.TRADER:
            return self.exchange
        if not is_real_auto_mode(getattr(cfg, "live_execution_mode", None)):
            return self.exchange
        target_mode = MarginMode.CROSS_MARGIN if task_requires_short_capability(cfg) else MarginMode.SPOT
        if getattr(cfg, "user_id", None) is not None:
            return await self._exchange_for_user_mode(cfg.user_id, target_mode)
        cached = self._exchange_by_mode.get(target_mode.value)
        if cached is not None:
            return cached
        try:
            routed = self._exchange_for_mode(target_mode)
            self.log.info(
                f"TaskManager created routed exchange for mode={target_mode.value} task_id={cfg.id} strategy={cfg.strategy_name()}"
            )
            return routed
        except Exception as exc:
            self.log.warning(
                f"TaskManager failed to create routed exchange for mode={target_mode.value}, falling back to default exchange: {exc}"
            )
            return self.exchange

    async def _exchange_for_user_mode(self, user_id: int, mode: MarginMode) -> BinanceExchange:
        cache_key = f"user:{user_id}:{mode.value}"
        cached = self._exchange_by_mode.get(cache_key)
        if cached is not None:
            return cached
        if not self.db_manager or not getattr(self.db_manager, "exchange_credential", None):
            raise RuntimeError("live trading requires a user exchange credential store")
        service_key = getattr(self.cfg, "secret_key", None)
        if not service_key_available(service_key):
            raise RuntimeError("TRADER_SECRET_KEY is required to start user-owned live trading tasks")
        credential = await self.db_manager.exchange_credential.get_default(user_id, "BINANCE")
        if credential is None:
            raise RuntimeError(f"missing BINANCE API credential for user_id={user_id}")
        base_cfg = getattr(self.exchange, "cfg", None)
        if base_cfg is None:
            raise RuntimeError("default exchange config is required to derive user exchange config")
        payload = base_cfg.model_dump()
        payload["api_key"] = decrypt_secret(service_key, credential.encrypted_api_key)
        payload["api_secret"] = decrypt_secret(service_key, credential.encrypted_api_secret)
        payload["margin_mode"] = mode
        routed = BinanceExchange(type(base_cfg)(**payload), self.log)
        self._exchange_by_mode[cache_key] = routed
        return routed

    async def _ensure_routed_exchanges(self, taskcs: list[TaskConfig]) -> None:
        for tc in taskcs:
            if tc.ttype != TaskType.TRADER:
                continue
            if not is_real_auto_mode(getattr(tc, "live_execution_mode", None)):
                continue
            target_mode = MarginMode.CROSS_MARGIN if task_requires_short_capability(tc) else MarginMode.SPOT
            if getattr(tc, "user_id", None) is not None:
                await self._exchange_for_user_mode(tc.user_id, target_mode)
                continue
            _ = self._exchange_by_mode.get(target_mode.value) or self._exchange_for_mode(target_mode)

    def _exchange_for_mode(self, mode: MarginMode) -> BinanceExchange:
        cached = self._exchange_by_mode.get(mode.value)
        if cached is not None:
            return cached
        base_cfg = getattr(self.exchange, "cfg", None)
        if base_cfg is None or not hasattr(base_cfg, "with_margin_mode"):
            return self.exchange
        cloned_cfg = base_cfg.with_margin_mode(mode)
        routed = BinanceExchange(cloned_cfg, self.log)
        self._exchange_by_mode[mode.value] = routed
        return routed

    async def add_backtrader_task(self, cfgs, queue: Queue):
        runtimes = self._optimization_runtimes(cfgs)
        for runtime in runtimes.values():
            runtime.start()

        failures = await self._prepare_backtest_datasets(cfgs, runtimes)
        failed_task_ids = {failure["task_id"] for failure in failures}
        cfg_by_id = {cfg.id: cfg for cfg in cfgs}
        for failure in failures:
            cfg = cfg_by_id.get(failure["task_id"])
            runtime = runtimes.get(cfg.optimization_run_id) if cfg else None
            if runtime:
                runtime.sample_skipped(
                    failure["task_id"],
                    reason=failure.get("reason", "dataset_failed"),
                    dataset_key=failure.get("dataset_key"),
                    message=failure.get("message"),
                )

        aborted_run_ids = self._abort_unhealthy_runtimes(runtimes)
        for run_id in aborted_run_ids:
            failures.append(
                {
                    "task_id": None,
                    "optimization_run_id": run_id,
                    "dataset_key": None,
                    "reason": "run_aborted",
                    "message": runtimes[run_id].status.get("abort_reason") or "optimization run aborted",
                }
            )
        sample_specs = []
        task_by_id = {}
        for cfg in cfgs:
            if cfg.id in failed_task_ids:
                continue
            if cfg.optimization_run_id in aborted_run_ids:
                continue
            task = BackTraderTask(cfg, self.cfg, self.log, self.db_manager, self.exchange)
            self.tasks[task.id()] = task
            BaseTask.start(task, queue)
            task_by_id[task.id()] = task
            sample_specs.append(build_backtest_sample_spec(self.cfg, cfg))

        sample_records = []
        execution_failures = []
        for sample_spec in sample_specs:
            runtime = runtimes.get(sample_spec.optimization_run_id)
            if runtime:
                runtime.sample_started(sample_spec.task_id)

        sample_results = await self._execute_sample_specs(sample_specs) if sample_specs else []
        for sample_result in sample_results:
            task = task_by_id.get(sample_result.task_id)
            if task is None:
                continue
            runtime = runtimes.get(task.tcfg.optimization_run_id)

            for log_str in sample_result.logs:
                self.log.add_log_buffer(log_str, LogTag.STRATEGY)

            if not sample_result.ok or sample_result.trader_result is None:
                self.log.error(
                    f"Backtest sample failed: task_id={sample_result.task_id}, error={sample_result.error}",
                    LogTag.STRATEGY,
                )
                failure_reason = "sample_timeout" if getattr(sample_result, "timed_out", False) else "execution_failed"
                execution_failures.append(
                    {
                        "task_id": sample_result.task_id,
                        "dataset_key": getattr(task.tcfg.dataset_ref, "dataset_key", None),
                        "reason": failure_reason,
                        "message": sample_result.error or "backtest execution failed",
                    }
                )
                if runtime:
                    if getattr(sample_result, "timed_out", False):
                        runtime.sample_timed_out(
                            sample_result.task_id,
                            message=sample_result.error or "sample execution exceeded timeout budget",
                        )
                    else:
                        runtime.sample_failed(
                            sample_result.task_id,
                            reason="execution_failed",
                            message=sample_result.error or "backtest execution failed",
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
            if runtime:
                runtime.sample_succeeded(sample_result.task_id)

        self._finalize_optimization_runs(cfgs, sample_records, failures + execution_failures)
        for runtime in runtimes.values():
            if runtime.status["stage"] != "aborted":
                runtime.finish()

    def _abort_unhealthy_runtimes(self, runtimes: dict[str, OptimizationRuntimeStatus]) -> set[str]:
        aborted = set()
        for run_id, runtime in runtimes.items():
            reason = evaluate_abort_reason(
                runtime.status,
                max_failure_rate=float(getattr(self.cfg, "optimization_max_failure_rate", 0.9)),
                min_completed_samples=int(getattr(self.cfg, "optimization_min_completed_samples_for_abort", 50)),
                no_progress_timeout_seconds=float(getattr(self.cfg, "optimization_no_progress_timeout_seconds", 180.0)),
                min_runnable_ratio=float(getattr(self.cfg, "optimization_min_runnable_ratio", 0.1)),
                parallelism_collapse_ratio=float(getattr(self.cfg, "optimization_parallelism_collapse_ratio", 0.25)),
                worker_cpu_efficiency_threshold=float(getattr(self.cfg, "optimization_worker_cpu_efficiency_threshold", 0.1)),
            )
            if reason:
                runtime.abort(reason)
                aborted.add(run_id)
        return aborted

    def _optimization_runtimes(self, cfgs: list[TaskConfig]) -> dict[str, OptimizationRuntimeStatus]:
        runtimes = {}
        for run_id in sorted({cfg.optimization_run_id for cfg in cfgs if cfg.optimization_run_id}):
            run_cfgs = [cfg for cfg in cfgs if cfg.optimization_run_id == run_id]
            dataset_keys = {
                (cfg.symbol_interval.name(), cfg.start_time, cfg.end_time) for cfg in run_cfgs if cfg.ttype == TaskType.BACK_TRADER and not cfg.csv
            }
            runtimes[run_id] = OptimizationRuntimeStatus(
                Path.cwd() / "tmp" / "optimization_runs" / run_id,
                run_id,
                total_samples=len(run_cfgs),
                total_datasets=len(dataset_keys),
                configured_workers=self._sample_max_workers(),
            )
        return runtimes

    def _dataset_prepare_max_workers(self) -> int:
        cpu_count = os.cpu_count() or 1
        return max(1, min(4, cpu_count))

    def _sample_max_workers(self) -> int:
        return max(1, os.cpu_count() or 1)

    def _optimization_dataset_prepare_timeout_seconds(self) -> float:
        return float(getattr(self.cfg, "optimization_dataset_prepare_timeout_seconds", 600.0))

    def _optimization_dataset_download_request_budget(self) -> int:
        return int(getattr(self.cfg, "optimization_dataset_download_request_budget", 2))

    def _optimization_sample_timeout_seconds(self) -> float:
        return float(getattr(self.cfg, "optimization_sample_timeout_seconds", 60.0))

    async def _prepare_dataset_job(
        self,
        resolver: DatasetResolver,
        symbol_interval,
        start_time: int,
        end_time: int,
        allow_download: bool,
        max_download_ranges: int | None = None,
        allow_incomplete_coverage: bool = False,
    ):
        prepare_kwargs = {
            "allow_download": allow_download,
            "max_download_ranges": max_download_ranges,
        }
        if "allow_incomplete_coverage" in inspect.signature(resolver.prepare).parameters:
            prepare_kwargs["allow_incomplete_coverage"] = allow_incomplete_coverage
        return await resolver.prepare(
            symbol_interval,
            start_time,
            end_time,
            **prepare_kwargs,
        )

    async def _prepare_backtest_datasets(
        self,
        cfgs: list[TaskConfig],
        runtimes: dict[str, OptimizationRuntimeStatus] | None = None,
    ) -> list[dict]:
        if not cfgs:
            return []

        prepared_results = {}
        failures = []
        dataset_jobs = {}
        dataset_run_ids = {}

        for cfg in cfgs:
            if cfg.ttype != TaskType.BACK_TRADER or cfg.csv:
                continue
            dataset_key = (cfg.symbol_interval.name(), cfg.start_time, cfg.end_time)
            if dataset_key not in dataset_jobs:
                dataset_jobs[dataset_key] = (
                    cfg.symbol_interval,
                    cfg.start_time,
                    cfg.end_time,
                    bool(cfg.auto_download),
                    cfg.optimization_run_id is not None,
                )
            if cfg.optimization_run_id:
                dataset_run_ids.setdefault(dataset_key, set()).add(cfg.optimization_run_id)

        semaphore = asyncio.Semaphore(self._dataset_prepare_max_workers())
        dataset_timeout_seconds = self._optimization_dataset_prepare_timeout_seconds()
        if dataset_jobs:
            self.log.info(
                "Optimization dataset preparation: "
                f"datasets={len(dataset_jobs)} "
                f"max_workers={self._dataset_prepare_max_workers()} "
                f"timeout={dataset_timeout_seconds:.1f}s"
            )

        async def run_job(dataset_key, job):
            async with semaphore:
                resolver = DatasetResolver(self.db_manager, self.exchange, self.log)
                symbol_interval, start_time, end_time, allow_download, allow_incomplete_coverage = job
                status_dataset_key = f"{symbol_interval.name()}|{start_time}|{end_time}"
                self.log.info(
                    f"Dataset preparation started: {status_dataset_key} "
                    f"allow_download={bool(allow_download)} "
                    f"allow_incomplete_coverage={bool(allow_incomplete_coverage)}"
                )
                for run_id in dataset_run_ids.get(dataset_key, set()):
                    runtime = (runtimes or {}).get(run_id)
                    if runtime:
                        runtime.dataset_started(status_dataset_key)
                try:
                    prepare_kwargs = {}
                    if "allow_incomplete_coverage" in inspect.signature(self._prepare_dataset_job).parameters:
                        prepare_kwargs["allow_incomplete_coverage"] = bool(allow_incomplete_coverage)
                    prepared_results[dataset_key] = await asyncio.wait_for(
                        self._prepare_dataset_job(
                            resolver,
                            symbol_interval,
                            start_time,
                            end_time,
                            allow_download,
                            self._optimization_dataset_download_request_budget() if allow_download else None,
                            **prepare_kwargs,
                        ),
                        timeout=dataset_timeout_seconds if allow_download else None,
                    )
                except TimeoutError:
                    prepared_results[dataset_key] = DatasetPreparationResult(
                        ok=False,
                        failure=DatasetPreparationFailure(
                            dataset_key=f"{symbol_interval.name()}|{start_time}|{end_time}",
                            reason="dataset_timeout",
                            message="dataset preparation exceeded optimization timeout budget",
                        ),
                    )
                result = prepared_results[dataset_key]
                if result.ok:
                    self.log.info(f"Dataset preparation finished: {status_dataset_key} status=ok")
                else:
                    reason = result.failure.reason if result.failure else "dataset_failed"
                    self.log.warning(f"Dataset preparation finished: {status_dataset_key} status=failed reason={reason}")
                for run_id in dataset_run_ids.get(dataset_key, set()):
                    runtime = (runtimes or {}).get(run_id)
                    if not runtime:
                        continue
                    if result.ok:
                        runtime.dataset_succeeded(status_dataset_key)
                    elif result.failure and result.failure.reason == "dataset_timeout":
                        runtime.dataset_timed_out(status_dataset_key, message=result.failure.message)
                    else:
                        runtime.dataset_failed(
                            status_dataset_key,
                            reason=result.failure.reason if result.failure else "dataset_failed",
                            message=result.failure.message if result.failure else None,
                        )

        tasks = {asyncio.create_task(run_job(dataset_key, job)): dataset_key for dataset_key, job in dataset_jobs.items()}
        heartbeat_seconds = 15.0
        while tasks:
            done, pending = await asyncio.wait(tasks.keys(), timeout=heartbeat_seconds, return_when=asyncio.FIRST_COMPLETED)
            for finished in done:
                tasks.pop(finished, None)
                finished.result()
            if pending:
                prepared = len(prepared_results)
                total = len(dataset_jobs)
                running = len(pending)
                sample = sorted(
                    (f"{key[0]}|{key[1]}|{key[2]}" for key in list(tasks.values())[:5]),
                )
                suffix = f" examples={sample}" if sample else ""
                self.log.info(f"Dataset preparation progress: prepared={prepared}/{total} running={running}{suffix}")

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
            futures = [(spec, executor.submit(run_backtest_sample, spec)) for spec in sample_specs]
            for spec, future in futures:
                try:
                    results.append(future.result(timeout=self._optimization_sample_timeout_seconds()))
                except FutureTimeoutError:
                    future.cancel()
                    results.append(
                        BacktestSampleResult(
                            ok=False,
                            task_id=spec.task_id,
                            trader_result=None,
                            logs=[],
                            report=None,
                            report_path=None,
                            error="sample execution exceeded timeout budget",
                            timed_out=True,
                        )
                    )
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
                if failure.get("optimization_run_id") == run_id:
                    run_failures.append(failure)
                    continue
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

    def close_task(self, id: int, user_id: int | None = None):
        task = self.get_task(id)
        if task:
            if user_id is not None and getattr(task.ts, "user_id", None) != user_id:
                return False
            task.close()
            return True
        return False

    def del_task(self, id: int, user_id: int | None = None):
        task = self.get_task(id)
        if task:
            if user_id is not None and getattr(task.ts, "user_id", None) != user_id:
                return False
            task.close()
            while self.has_task(id):
                sleep(self.log, 1)

        return self.db_manager.task.del_task(id)

    async def get_task_state(self, id: int, user_id: int | None = None) -> TaskState | None:
        task = self.get_task(id)
        if task:
            if user_id is not None and getattr(task.ts, "user_id", None) != user_id:
                return None
            return task.ts
        if self.db_manager:
            if user_id is not None:
                return await self.db_manager.task.get_task_for_user(id, user_id)
            return await self.db_manager.task.get_task(id)

        return None

    async def get_all_task_state(self, user_id: int | None = None) -> list[TaskState]:
        ret: list[TaskState] = []
        for ts in self.tasks.values():
            if user_id is not None and getattr(ts.ts, "user_id", None) != user_id:
                continue
            ret.append(ts.ts)

        if self.db_manager:
            tss = await self.db_manager.task.get_all_tasks_for_user(user_id) if user_id is not None else await self.db_manager.task.get_all_tasks()
            for ts in tss:
                if self.has_task(ts.id):
                    continue
                ret.append(ts)

        return ret
