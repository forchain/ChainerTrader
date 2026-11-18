from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from trader.core.optimization.domain import evaluate_abort_reason
from trader.core.optimization.interfaces import BacktestRunner, RankingReportStore


class RunParameterOptimizationUseCase:
    """Coordinate dataset preparation, parallel backtest sample execution, abort checks, and ranking artifacts."""

    def __init__(
        self,
        *,
        backtest_runner: BacktestRunner,
        report_store: RankingReportStore,
        runtime_factory: Callable[[str, list[Any], int], Any] | None = None,
        max_workers: int = 1,
        abort_thresholds: dict[str, Any] | None = None,
    ):
        self.backtest_runner = backtest_runner
        self.report_store = report_store
        self.runtime_factory = runtime_factory
        self.max_workers = max_workers
        self.abort_thresholds = dict(abort_thresholds or {})

    async def execute(
        self,
        configs: list[Any],
        *,
        sample_spec_builder: Callable[[Any], Any],
        on_regular_task: Callable[[Any], Awaitable[None]] | None = None,
        on_sample_task_registered: Callable[[Any], Awaitable[None]] | None = None,
        on_sample_result: Callable[[Any, Any], Awaitable[None]] | None = None,
        on_sample_failure: Callable[[Any, Any], Awaitable[None]] | None = None,
        finalize_cb: Callable[[list[Any], list[dict], list[dict]], None] | None = None,
    ) -> dict[str, Any]:
        runtimes: dict[str, Any] = {}
        run_ids = sorted({cfg.optimization_run_id for cfg in configs if getattr(cfg, "optimization_run_id", None)})
        if self.runtime_factory is not None:
            for run_id in run_ids:
                run_cfgs = [cfg for cfg in configs if cfg.optimization_run_id == run_id]
                runtime = self.runtime_factory(run_id, run_cfgs, self.max_workers)
                runtimes[run_id] = runtime
                runtime.start()

        failures = list(await self.backtest_runner.prepare_datasets(configs, runtimes))
        failed_task_ids = {failure["task_id"] for failure in failures}
        cfg_by_id = {cfg.id: cfg for cfg in configs}
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
        active_configs: dict[int, Any] = {}
        for cfg in configs:
            if cfg.id in failed_task_ids:
                continue
            if getattr(cfg, "optimization_run_id", None) in aborted_run_ids:
                continue
            active_configs[cfg.id] = cfg
            if getattr(cfg, "optimization_run_id", None):
                if on_sample_task_registered is not None:
                    await on_sample_task_registered(cfg)
                sample_specs.append(sample_spec_builder(cfg))
                continue
            if on_regular_task is not None:
                await on_regular_task(cfg)

        for sample_spec in sample_specs:
            runtime = runtimes.get(getattr(sample_spec, "optimization_run_id", None))
            if runtime:
                runtime.sample_started(sample_spec.task_id)

        sample_records = []
        execution_failures = []
        sample_results = await self.backtest_runner.execute_samples(sample_specs) if sample_specs else []
        for sample_result in sample_results:
            cfg = active_configs.get(sample_result.task_id)
            if cfg is None:
                continue
            runtime = runtimes.get(getattr(cfg, "optimization_run_id", None))

            if not sample_result.ok or sample_result.trader_result is None:
                if on_sample_failure is not None:
                    await on_sample_failure(cfg, sample_result)
                failure_reason = "sample_timeout" if getattr(sample_result, "timed_out", False) else "execution_failed"
                execution_failures.append(
                    {
                        "task_id": sample_result.task_id,
                        "dataset_key": getattr(getattr(cfg, "dataset_ref", None), "dataset_key", None),
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

            if on_sample_result is not None:
                await on_sample_result(cfg, sample_result)
            sample_records.append(
                {
                    "task_id": sample_result.task_id,
                    "report": sample_result.report,
                    "report_path": sample_result.report_path,
                }
            )
            if runtime:
                runtime.sample_succeeded(sample_result.task_id)

        if finalize_cb is not None:
            finalize_cb(configs, sample_records, failures + execution_failures)
        else:
            self.finalize_runs(configs, sample_records, failures + execution_failures)
        for runtime in runtimes.values():
            if runtime.status["stage"] != "aborted":
                runtime.finish()

        return {
            "sample_records": sample_records,
            "failures": failures + execution_failures,
            "aborted_run_ids": aborted_run_ids,
        }

    def finalize_runs(self, configs: list[Any], sample_records: list[dict], failures: list[dict]) -> None:
        task_by_id = {cfg.id: cfg for cfg in configs}
        run_ids = sorted({cfg.optimization_run_id for cfg in configs if getattr(cfg, "optimization_run_id", None)})
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

            self.report_store.write_artifacts(run_id, run_reports, run_failures)

    def _abort_unhealthy_runtimes(self, runtimes: dict[str, Any]) -> set[str]:
        aborted = set()
        for run_id, runtime in runtimes.items():
            reason = evaluate_abort_reason(runtime.status, **self.abort_thresholds)
            if reason:
                runtime.abort(reason)
                aborted.add(run_id)
        return aborted
