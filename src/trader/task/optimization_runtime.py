from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TERMINAL_STAGES = {"finished", "aborted"}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def evaluate_abort_reason(
    status: dict[str, Any],
    *,
    max_failure_rate: float = 0.9,
    min_completed_samples: int = 50,
    no_progress_timeout_seconds: float = 180.0,
    min_runnable_ratio: float = 0.1,
    parallelism_collapse_ratio: float = 0.25,
    worker_cpu_efficiency_threshold: float = 0.1,
) -> str | None:
    completed = int(status.get("samples_completed") or 0)
    succeeded = int(status.get("samples_succeeded") or 0)
    failed = int(status.get("samples_failed") or 0) + int(status.get("samples_timed_out") or 0)
    executed = succeeded + failed
    failure_rate = failed / executed if executed else 0.0
    total = int(status.get("samples_total") or 0)
    runnable = int(status.get("samples_runnable") or 0)
    time_since_progress = float(status.get("time_since_last_progress_seconds") or 0)
    parallelism_ratio = float(status.get("parallelism_ratio") or 0.0)
    worker_cpu_efficiency = float(status.get("worker_cpu_efficiency") or 0.0)

    if completed >= min_completed_samples and failure_rate > max_failure_rate:
        return "high_failure_rate"

    if (
        runnable > completed
        and time_since_progress > no_progress_timeout_seconds
        and parallelism_ratio < parallelism_collapse_ratio
        and worker_cpu_efficiency < worker_cpu_efficiency_threshold
    ):
        return "parallelism_collapse"

    if runnable > completed and time_since_progress > no_progress_timeout_seconds:
        return "no_progress"

    if total > 0 and runnable / total < min_runnable_ratio:
        return "insufficient_runnable_samples"

    return None


class OptimizationRuntimeStatus:
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

    def start(self):
        self._started_at = datetime.now(timezone.utc)
        self.status["stage"] = "dataset_preparation" if self.status["dataset_jobs_total"] else "sample_execution"
        self._progress()
        self._append_event("run_started")
        self.write()

    def dataset_started(self, dataset_key: str):
        self.status["stage"] = "dataset_preparation"
        self.status["dataset_jobs_running"] += 1
        self._append_event("dataset_job_started", dataset_key=dataset_key)
        self.write()

    def dataset_succeeded(self, dataset_key: str):
        self.status["dataset_jobs_running"] = max(0, self.status["dataset_jobs_running"] - 1)
        self.status["dataset_jobs_succeeded"] += 1
        self._progress()
        self._append_event("dataset_job_succeeded", dataset_key=dataset_key)
        self.write()

    def dataset_failed(self, dataset_key: str, *, reason: str = "dataset_failed", message: str | None = None):
        self.status["dataset_jobs_running"] = max(0, self.status["dataset_jobs_running"] - 1)
        self.status["dataset_jobs_failed"] += 1
        self._progress()
        self._append_event("dataset_job_failed", dataset_key=dataset_key, reason=reason, message=message)
        self.write()

    def dataset_timed_out(self, dataset_key: str, *, message: str | None = None):
        self.status["dataset_jobs_running"] = max(0, self.status["dataset_jobs_running"] - 1)
        self.status["dataset_jobs_timed_out"] += 1
        self._progress()
        self._append_event("dataset_job_timed_out", dataset_key=dataset_key, reason="dataset_timeout", message=message)
        self.write()

    def sample_started(self, task_id: int):
        self.status["stage"] = "sample_execution"
        self.status["samples_running"] += 1
        self._recompute_health()
        self._append_event("sample_started", task_id=task_id)
        self.write()

    def sample_succeeded(self, task_id: int):
        self.status["samples_running"] = max(0, self.status["samples_running"] - 1)
        self.status["samples_completed"] += 1
        self.status["samples_succeeded"] += 1
        self._progress()
        self._append_event("sample_succeeded", task_id=task_id)
        self.write()

    def sample_failed(self, task_id: int, *, reason: str = "execution_failed", message: str | None = None):
        self.status["samples_running"] = max(0, self.status["samples_running"] - 1)
        self.status["samples_completed"] += 1
        self.status["samples_failed"] += 1
        self._progress()
        self._append_event("sample_failed", task_id=task_id, reason=reason, message=message)
        self.write()

    def sample_timed_out(self, task_id: int, *, message: str | None = None):
        self.status["samples_running"] = max(0, self.status["samples_running"] - 1)
        self.status["samples_completed"] += 1
        self.status["samples_timed_out"] += 1
        self._progress()
        self._append_event("sample_timed_out", task_id=task_id, reason="sample_timeout", message=message)
        self.write()

    def sample_skipped(self, task_id: int, *, reason: str, dataset_key: str | None = None, message: str | None = None):
        self.status["samples_completed"] += 1
        self.status["samples_skipped"] += 1
        self.status["samples_runnable"] = max(0, self.status["samples_runnable"] - 1)
        self._progress()
        self._append_event("sample_skipped", task_id=task_id, reason=reason, dataset_key=dataset_key, message=message)
        self.write()

    def finish(self):
        self.status["stage"] = "finished"
        self.status["health"] = "healthy"
        self._progress()
        self._append_event("run_finished")
        self.write()

    def abort(self, reason: str):
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

    def write(self):
        self._recompute_health()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(self.status_path, self.status)

    def _append_event(self, event: str, **payload):
        self.run_dir.mkdir(parents=True, exist_ok=True)
        record = {
            "run_id": self.run_id,
            "timestamp": utc_now_iso(),
            "event": event,
        }
        record.update({key: value for key, value in payload.items() if value is not None})
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    def _progress(self):
        now = datetime.now(timezone.utc)
        self._last_progress_at = now
        self.status["last_progress_at"] = now.isoformat(timespec="seconds").replace("+00:00", "Z")

    def _recompute_health(self):
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
    def _write_json(path: Path, payload: dict[str, Any]):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        tmp_path.replace(path)
