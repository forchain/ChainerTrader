from __future__ import annotations

import asyncio
import copy
import inspect
import os
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Callable

from trader.core.optimization.domain import make_param_id
from trader.task.backtrader_task import (
    BacktestSampleResult,
    backtest_data_start_time,
    build_backtest_sample_spec,
    run_backtest_sample,
)
from trader.task.dataset_resolver import (
    DatasetPreparationFailure,
    DatasetPreparationResult,
    DatasetResolver,
)
from trader.task.task_config import parse_task_config
from trader.task.task_type import TaskType


class ProcessPoolBacktestRunner:
    """Adapter implementing BacktestRunner using DatasetResolver and ProcessPoolExecutor."""

    def __init__(
        self,
        *,
        cfg: Any,
        db_manager: Any,
        exchange: Any,
        log: Any,
        prepare_dataset_job_fn: Callable[..., Any] | None = None,
        sample_max_workers: int | None = None,
        dataset_prepare_max_workers: int | None = None,
        dataset_prepare_timeout_seconds: float | None = None,
        dataset_download_request_budget: int | None = None,
        sample_timeout_seconds: float | None = None,
        process_pool_factory: Any = ProcessPoolExecutor,
        dataset_resolver_cls: Any = DatasetResolver,
    ):
        self.cfg = cfg
        self.db_manager = db_manager
        self.exchange = exchange
        self.log = log
        self._prepare_dataset_job_fn = prepare_dataset_job_fn
        self._sample_max_workers = sample_max_workers
        self._dataset_prepare_max_workers = dataset_prepare_max_workers
        self._dataset_prepare_timeout_seconds = dataset_prepare_timeout_seconds
        self._dataset_download_request_budget = dataset_download_request_budget
        self._sample_timeout_seconds = sample_timeout_seconds
        self._process_pool_factory = process_pool_factory
        self._dataset_resolver_cls = dataset_resolver_cls

    def _effective_prepare_workers(self) -> int:
        if self._dataset_prepare_max_workers is not None:
            return self._dataset_prepare_max_workers
        cpu_count = os.cpu_count() or 1
        return max(1, min(4, cpu_count))

    def _effective_sample_workers(self) -> int:
        if self._sample_max_workers is not None:
            return self._sample_max_workers
        return max(1, os.cpu_count() or 1)

    def _effective_prepare_timeout(self) -> float:
        if self._dataset_prepare_timeout_seconds is not None:
            return self._dataset_prepare_timeout_seconds
        return float(getattr(self.cfg, "optimization_dataset_prepare_timeout_seconds", 600.0))

    def _effective_download_budget(self) -> int:
        if self._dataset_download_request_budget is not None:
            return self._dataset_download_request_budget
        return int(getattr(self.cfg, "optimization_dataset_download_request_budget", 2))

    def _effective_sample_timeout(self) -> float:
        if self._sample_timeout_seconds is not None:
            return self._sample_timeout_seconds
        return float(getattr(self.cfg, "optimization_sample_timeout_seconds", 60.0))

    async def prepare_datasets(self, configs: list[Any], runtimes: dict[str, Any] | None = None) -> list[dict]:
        if not configs:
            return []

        prepared_results: dict[tuple, Any] = {}
        failures: list[dict] = []
        dataset_jobs: dict[tuple, tuple] = {}
        dataset_run_ids: dict[tuple, set[str]] = {}

        for cfg in configs:
            if cfg.ttype != TaskType.BACK_TRADER or cfg.csv:
                continue
            dataset_key = (cfg.symbol_interval.name(), backtest_data_start_time(self.cfg, cfg), cfg.end_time)
            if dataset_key not in dataset_jobs:
                dataset_jobs[dataset_key] = (
                    cfg.symbol_interval,
                    backtest_data_start_time(self.cfg, cfg),
                    cfg.end_time,
                    bool(cfg.auto_download),
                    cfg.optimization_run_id is not None,
                )
            if cfg.optimization_run_id:
                dataset_run_ids.setdefault(dataset_key, set()).add(cfg.optimization_run_id)

        max_workers = self._effective_prepare_workers()
        semaphore = asyncio.Semaphore(max_workers)
        dataset_timeout_seconds = self._effective_prepare_timeout()
        if dataset_jobs and self.log is not None:
            self.log.info(
                "Optimization dataset preparation: "
                f"datasets={len(dataset_jobs)} "
                f"max_workers={max_workers} "
                f"timeout={dataset_timeout_seconds:.1f}s"
            )

        async def default_prepare_job(
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
            return await resolver.prepare(symbol_interval, start_time, end_time, **prepare_kwargs)

        job_runner = self._prepare_dataset_job_fn or default_prepare_job

        async def run_job(dataset_key, job):
            async with semaphore:
                resolver = self._dataset_resolver_cls(self.db_manager, self.exchange, self.log)
                symbol_interval, start_time, end_time, allow_download, allow_incomplete_coverage = job
                status_dataset_key = f"{symbol_interval.name()}|{start_time}|{end_time}"
                if self.log is not None:
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
                    if "allow_incomplete_coverage" in inspect.signature(job_runner).parameters:
                        prepare_kwargs["allow_incomplete_coverage"] = bool(allow_incomplete_coverage)
                    prepared_results[dataset_key] = await asyncio.wait_for(
                        job_runner(
                            resolver,
                            symbol_interval,
                            start_time,
                            end_time,
                            allow_download,
                            self._effective_download_budget() if allow_download else None,
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
                if self.log is not None:
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
            if pending and self.log is not None:
                prepared = len(prepared_results)
                total = len(dataset_jobs)
                running = len(pending)
                sample = sorted(f"{key[0]}|{key[1]}|{key[2]}" for key in list(tasks.values())[:5])
                suffix = f" examples={sample}" if sample else ""
                self.log.info(f"Dataset preparation progress: prepared={prepared}/{total} running={running}{suffix}")

        for cfg in configs:
            if cfg.ttype != TaskType.BACK_TRADER or cfg.csv:
                continue
            dataset_key = (cfg.symbol_interval.name(), backtest_data_start_time(self.cfg, cfg), cfg.end_time)
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

    async def execute_samples(self, sample_specs: list[Any]) -> list[Any]:
        if not sample_specs:
            return []
        return await asyncio.to_thread(self.execute_samples_sync, sample_specs)

    def execute_samples_sync(self, sample_specs: list[Any]) -> list[Any]:
        results = []
        timeout = self._effective_sample_timeout()
        with self._process_pool_factory(max_workers=self._effective_sample_workers()) as executor:
            futures = [(spec, executor.submit(run_backtest_sample, spec)) for spec in sample_specs]
            for spec, future in futures:
                try:
                    results.append(future.result(timeout=timeout))
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

    async def run_symbol_backtest(
        self,
        *,
        template: dict[str, Any],
        symbol: str,
        start_time: str,
        end_time: str,
        optimization_run_id: str,
    ):
        interval = template.get("interval", "1h")
        task_definition = copy.deepcopy(template)
        task_definition["task_type"] = "BACK_TRADER"
        task_definition["symbols"] = symbol
        task_definition["interval"] = interval
        task_definition["start_time"] = start_time
        task_definition["end_time"] = end_time
        task_definition["auto_download"] = True
        task_definition["optimization_run_id"] = optimization_run_id
        task_definition.pop("param_grid", None)
        task_definition.pop("param_combinations", None)

        cfg_obj = parse_task_config(task_definition)[0]
        if cfg_obj.param_id is None:
            cfg_obj.param_id = make_param_id(cfg_obj.strategy_params)
        data_start_time = backtest_data_start_time(self.cfg, cfg_obj)
        resolver = DatasetResolver(self.db_manager, self.exchange, self.log)
        prepare_result = await resolver.prepare(
            cfg_obj.symbol_interval,
            data_start_time,
            cfg_obj.end_time,
            allow_download=True,
        )
        if not prepare_result.ok:
            return cfg_obj, BacktestSampleResult(
                ok=False,
                task_id=cfg_obj.id,
                trader_result=None,
                logs=[],
                report=None,
                report_path=None,
                error=prepare_result.failure.message if prepare_result.failure else "dataset preparation failed",
            )
        spec = build_backtest_sample_spec(self.cfg, cfg_obj)
        loop = asyncio.get_running_loop()
        max_workers = max(1, min(4, os.cpu_count() or 1))
        with ProcessPoolExecutor(max_workers=max_workers) as process_pool:
            result = await loop.run_in_executor(process_pool, run_backtest_sample, spec)
        return cfg_obj, result
