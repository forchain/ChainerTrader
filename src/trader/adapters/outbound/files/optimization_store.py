from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from trader.adapters.outbound.files.optimization_html import (
    build_rankings_html,
    write_shortlist_html,
    write_workbench_html,
)
from trader.core.optimization.domain import TERMINAL_STAGES, build_optimization_artifacts
from trader.core.optimization.use_cases.audit import RunOptimizationAuditUseCase


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class FileTaskConfigFileStore:
    """File-system implementation of TaskConfigFileStore."""

    def exists(self, path: str | Path) -> bool:
        return Path(path).exists()

    def load_json(self, path: str | Path) -> Any:
        return json.loads(Path(path).read_text(encoding="utf-8"))

    def write_json(self, path: str | Path, payload: Any) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def read_lines(self, path: str | Path, limit: int) -> list[str]:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
        return lines[-limit:]


class FileRankingReportStore:
    """File-system implementation of RankingReportStore under base_dir/reports/optimizations."""

    def __init__(self, base_dir: str | Path | None = None, *, static_dir: Path | None = None):
        self.base_dir = Path(base_dir) if base_dir is not None else Path.cwd()
        self.static_dir = static_dir or (
            Path(__file__).resolve().parents[4] / "trader" / "adapters" / "inbound" / "http" / "static" / "optimization-workbench"
        )

    def run_dir(self, run_id: str) -> Path:
        return self.base_dir / "reports" / "optimizations" / run_id

    def run_dir_str(self, run_id: str) -> str:
        return str(self.run_dir(run_id))

    def load_sample_reports(self, run_id: str) -> list[dict]:
        runs_dir = self.run_dir(run_id) / "runs"
        if not runs_dir.exists():
            return []
        reports = []
        for path in sorted(runs_dir.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["report_path"] = str(path.resolve())
            reports.append(payload)
        return reports

    def load_failures(self, run_id: str) -> list[dict]:
        failures_path = self.run_dir(run_id) / "failures.json"
        return json.loads(failures_path.read_text(encoding="utf-8")) if failures_path.exists() else []

    def write_artifacts(self, run_id: str, sample_reports: list[dict], failures: list[dict]) -> dict:
        artifacts = build_optimization_artifacts(run_id, sample_reports, failures)
        run_dir = self.run_dir(run_id)
        rankings_dir = run_dir / "rankings"
        shortlist_dir = run_dir / "shortlist"
        workbench_dir = run_dir / "workbench"
        rankings_dir.mkdir(parents=True, exist_ok=True)
        shortlist_dir.mkdir(parents=True, exist_ok=True)
        workbench_dir.mkdir(parents=True, exist_ok=True)

        _write_json(run_dir / "manifest.json", artifacts["manifest"])
        _write_json(run_dir / "aggregate.json", artifacts["aggregate"])
        _write_json(run_dir / "failures.json", artifacts["failures"])
        _write_json(run_dir / "fingerprints.json", artifacts["fingerprints"])
        _write_json(run_dir / "audit.json", artifacts["audit"])
        _write_json(run_dir / "clusters.json", artifacts["clusters"])
        _write_json(run_dir / "local_best.json", artifacts["local_best"])
        _write_json(run_dir / "shortlist.json", artifacts["shortlist"])
        _write_json(run_dir / "workbench.json", artifacts["workbench"])
        _write_json(rankings_dir / "by_score.json", artifacts["rankings"]["by_score"])
        _write_json(rankings_dir / "by_excess_return.json", artifacts["rankings"]["by_excess_return"])
        (rankings_dir / "index.html").write_text(
            build_rankings_html(run_id, artifacts["rankings"]["by_score"]),
            encoding="utf-8",
        )
        write_shortlist_html(shortlist_dir / "index.html", artifacts["shortlist"])
        write_workbench_html(
            workbench_dir / "index.html",
            artifacts["workbench"],
            self.static_dir / "app.js",
            self.static_dir / "style.css",
        )
        return artifacts

    def write_agent_review_summary(self, run_id: str, summary: dict) -> str:
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        target = run_dir / "agent_review_summary.json"
        _write_json(target, summary)
        return str(target)

    def write_rolling_outputs(
        self,
        report_id: str,
        summary: dict,
        monthly_items: list[dict],
        output_dir: str | None = None,
    ) -> None:
        report_root = Path(output_dir) if output_dir is not None else self.run_dir(report_id)
        report_root.mkdir(parents=True, exist_ok=True)
        FileTaskConfigFileStore().write_json(report_root / "summary.json", summary)
        FileTaskConfigFileStore().write_json(report_root / "monthly.json", monthly_items)


class FileOptimizationRuntimeStatus:
    """File-backed runtime progress/status tracker for parameter optimization runs."""

    def __init__(
        self,
        run_dir: str | Path,
        run_id: str,
        *,
        total_samples: int = 0,
        total_datasets: int = 0,
        configured_workers: int = 0,
    ):
        self.run_dir = Path(run_dir)
        self.run_id = run_id
        self.status_path = self.run_dir / "status.json"
        self.events_path = self.run_dir / "events.jsonl"
        self.abort_summary_path = self.run_dir / "abort_summary.json"
        self.status: dict[str, Any] = {
            "run_id": run_id,
            "stage": "created",
            "elapsed_seconds": 0,
            "last_progress_at": None,
            "time_since_last_progress_seconds": 0,
            "dataset_jobs_total": total_datasets,
            "dataset_jobs_running": 0,
            "dataset_jobs_succeeded": 0,
            "dataset_jobs_failed": 0,
            "dataset_jobs_timed_out": 0,
            "samples_total": total_samples,
            "samples_runnable": total_samples,
            "samples_running": 0,
            "samples_completed": 0,
            "samples_succeeded": 0,
            "samples_failed": 0,
            "samples_timed_out": 0,
            "samples_skipped": 0,
            "configured_workers": configured_workers,
            "expected_workers": min(configured_workers, total_samples) if configured_workers else 0,
            "running_workers": 0,
            "parallelism_ratio": 0.0,
            "worker_cpu_efficiency": 0.0,
            "host_cpu_pct": 0.0,
            "failure_rate": 0.0,
            "samples_per_minute": 0.0,
            "health": "healthy",
            "abort_reason": None,
        }
        self._started_at: datetime | None = None
        self._last_progress_at: datetime | None = None

    def start(self) -> None:
        self._started_at = datetime.now(timezone.utc)
        self.status["stage"] = "dataset_preparation" if self.status["dataset_jobs_total"] else "sample_execution"
        self._progress()
        self._append_event("run_started")
        self.write()

    def dataset_started(self, dataset_key: str) -> None:
        self.status["stage"] = "dataset_preparation"
        self.status["dataset_jobs_running"] += 1
        self._append_event("dataset_job_started", dataset_key=dataset_key)
        self.write()

    def dataset_succeeded(self, dataset_key: str) -> None:
        self.status["dataset_jobs_running"] = max(0, self.status["dataset_jobs_running"] - 1)
        self.status["dataset_jobs_succeeded"] += 1
        self._progress()
        self._append_event("dataset_job_succeeded", dataset_key=dataset_key)
        self.write()

    def dataset_failed(self, dataset_key: str, *, reason: str = "dataset_failed", message: str | None = None) -> None:
        self.status["dataset_jobs_running"] = max(0, self.status["dataset_jobs_running"] - 1)
        self.status["dataset_jobs_failed"] += 1
        self._progress()
        self._append_event("dataset_job_failed", dataset_key=dataset_key, reason=reason, message=message)
        self.write()

    def dataset_timed_out(self, dataset_key: str, *, message: str | None = None) -> None:
        self.status["dataset_jobs_running"] = max(0, self.status["dataset_jobs_running"] - 1)
        self.status["dataset_jobs_timed_out"] += 1
        self._progress()
        self._append_event("dataset_job_timed_out", dataset_key=dataset_key, reason="dataset_timeout", message=message)
        self.write()

    def sample_started(self, task_id: int) -> None:
        self.status["stage"] = "sample_execution"
        self.status["samples_running"] += 1
        self._recompute_health()
        self._append_event("sample_started", task_id=task_id)
        self.write()

    def sample_succeeded(self, task_id: int) -> None:
        self.status["samples_running"] = max(0, self.status["samples_running"] - 1)
        self.status["samples_completed"] += 1
        self.status["samples_succeeded"] += 1
        self._progress()
        self._append_event("sample_succeeded", task_id=task_id)
        self.write()

    def sample_failed(self, task_id: int, *, reason: str = "execution_failed", message: str | None = None) -> None:
        self.status["samples_running"] = max(0, self.status["samples_running"] - 1)
        self.status["samples_completed"] += 1
        self.status["samples_failed"] += 1
        self._progress()
        self._append_event("sample_failed", task_id=task_id, reason=reason, message=message)
        self.write()

    def sample_timed_out(self, task_id: int, *, message: str | None = None) -> None:
        self.status["samples_running"] = max(0, self.status["samples_running"] - 1)
        self.status["samples_completed"] += 1
        self.status["samples_timed_out"] += 1
        self._progress()
        self._append_event("sample_timed_out", task_id=task_id, reason="sample_timeout", message=message)
        self.write()

    def sample_skipped(self, task_id: int, *, reason: str, dataset_key: str | None = None, message: str | None = None) -> None:
        self.status["samples_completed"] += 1
        self.status["samples_skipped"] += 1
        self.status["samples_runnable"] = max(0, self.status["samples_runnable"] - 1)
        self._progress()
        self._append_event("sample_skipped", task_id=task_id, reason=reason, dataset_key=dataset_key, message=message)
        self.write()

    def finish(self) -> None:
        self.status["stage"] = "finished"
        self.status["health"] = "healthy"
        self._progress()
        self._append_event("run_finished")
        self.write()

    def abort(self, reason: str) -> None:
        self.status["stage"] = "aborted"
        self.status["health"] = "unhealthy"
        self.status["abort_reason"] = reason
        self._progress()
        self._append_event("run_aborted", reason=reason)
        self.write()
        self._write_json(
            self.abort_summary_path,
            {
                "run_id": self.run_id,
                "reason": reason,
                "at_stage": "sample_execution",
                "completed_samples": self.status["samples_completed"],
                "failure_rate": self.status["failure_rate"],
            },
        )

    def write(self) -> None:
        self._recompute_health()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(self.status_path, self.status)

    def _append_event(self, event: str, **payload: Any) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "run_id": self.run_id,
            "timestamp": _utc_now_iso(),
            "event": event,
        }
        record.update({key: value for key, value in payload.items() if value is not None})
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def _progress(self) -> None:
        now = datetime.now(timezone.utc)
        self._last_progress_at = now
        self.status["last_progress_at"] = now.isoformat(timespec="seconds").replace("+00:00", "Z")

    def _recompute_health(self) -> None:
        now = datetime.now(timezone.utc)
        if self._started_at:
            self.status["elapsed_seconds"] = int((now - self._started_at).total_seconds())
        if self._last_progress_at:
            self.status["time_since_last_progress_seconds"] = int((now - self._last_progress_at).total_seconds())

        remaining = max(0, self.status["samples_runnable"] - self.status["samples_completed"] - self.status["samples_running"])
        expected_workers = min(self.status["configured_workers"], remaining + self.status["samples_running"])
        if self.status["stage"] in TERMINAL_STAGES:
            expected_workers = 0
        self.status["expected_workers"] = expected_workers
        self.status["running_workers"] = self.status["samples_running"]
        self.status["parallelism_ratio"] = (
            round(self.status["samples_running"] / expected_workers, 4) if expected_workers else 0.0
        )

        executed = self.status["samples_succeeded"] + self.status["samples_failed"] + self.status["samples_timed_out"]
        failed = self.status["samples_failed"] + self.status["samples_timed_out"]
        self.status["failure_rate"] = round(failed / executed, 4) if executed else 0.0

        if self._started_at and self.status["samples_completed"]:
            elapsed_minutes = max((now - self._started_at).total_seconds() / 60, 1 / 60)
            self.status["samples_per_minute"] = round(self.status["samples_completed"] / elapsed_minutes, 4)

    @staticmethod
    def _write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        tmp_path.replace(path)


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def write_optimization_artifacts(
    base_dir: str | Path,
    optimization_run_id: str,
    sample_reports: list[dict],
    failures: list[dict],
) -> Path:
    store = FileRankingReportStore(base_dir)
    store.write_artifacts(optimization_run_id, sample_reports, failures)
    return store.run_dir(optimization_run_id)


def run_optimization_audit(base_dir: str | Path, run_id: str, *, block_on_failure: bool = True) -> dict[str, Any]:
    return RunOptimizationAuditUseCase(FileRankingReportStore(base_dir)).execute(
        run_id,
        block_on_failure=block_on_failure,
    )
