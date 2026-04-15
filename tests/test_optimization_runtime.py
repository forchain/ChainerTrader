import json
from pathlib import Path

from trader.task.optimization_runtime import OptimizationRuntimeStatus, evaluate_abort_reason


def test_runtime_status_writes_snapshot_and_ordered_events(tmp_path: Path):
    runtime = OptimizationRuntimeStatus(tmp_path, "run-identity-1", total_samples=3, configured_workers=4)

    runtime.start()
    runtime.dataset_started("dataset-a")
    runtime.dataset_succeeded("dataset-a")
    runtime.sample_started(1)
    runtime.sample_succeeded(1)
    runtime.sample_failed(2, reason="execution_failed", message="worker crashed")
    runtime.sample_skipped(3, reason="dataset_failed", dataset_key="dataset-b")
    runtime.finish()

    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    events = [
        json.loads(line)
        for line in (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]

    assert status["run_id"] == "run-identity-1"
    assert status["stage"] == "finished"
    assert status["samples_total"] == 3
    assert status["samples_completed"] == 3
    assert status["samples_succeeded"] == 1
    assert status["samples_failed"] == 1
    assert status["samples_skipped"] == 1
    assert status["failure_rate"] == 0.5
    assert status["configured_workers"] == 4
    assert status["expected_workers"] == 0
    assert status["parallelism_ratio"] == 0.0
    assert status["last_progress_at"]
    assert [event["event"] for event in events] == [
        "run_started",
        "dataset_job_started",
        "dataset_job_succeeded",
        "sample_started",
        "sample_succeeded",
        "sample_failed",
        "sample_skipped",
        "run_finished",
    ]
    assert all(event["run_id"] == "run-identity-1" for event in events)


def test_runtime_status_writes_abort_summary(tmp_path: Path):
    runtime = OptimizationRuntimeStatus(tmp_path, "run-abort-1", total_samples=2, configured_workers=2)

    runtime.start()
    runtime.sample_started(1)
    runtime.sample_failed(1, reason="execution_failed", message="bad sample")
    runtime.abort("high_failure_rate")

    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    summary = json.loads((tmp_path / "abort_summary.json").read_text(encoding="utf-8"))

    assert status["stage"] == "aborted"
    assert status["health"] == "unhealthy"
    assert status["abort_reason"] == "high_failure_rate"
    assert summary["reason"] == "high_failure_rate"
    assert summary["at_stage"] == "sample_execution"
    assert summary["completed_samples"] == 1
    assert summary["failure_rate"] == 1.0


def test_evaluate_abort_reason_uses_failure_rate_after_observation_window():
    status = {
        "samples_completed": 50,
        "samples_failed": 46,
        "samples_timed_out": 0,
        "samples_succeeded": 4,
        "samples_total": 100,
        "samples_runnable": 100,
        "time_since_last_progress_seconds": 10,
        "parallelism_ratio": 1.0,
        "worker_cpu_efficiency": 1.0,
    }

    assert evaluate_abort_reason(status, max_failure_rate=0.9, min_completed_samples=50) == "high_failure_rate"


def test_evaluate_abort_reason_uses_no_progress_timeout():
    status = {
        "samples_completed": 1,
        "samples_failed": 0,
        "samples_timed_out": 0,
        "samples_succeeded": 1,
        "samples_total": 100,
        "samples_runnable": 100,
        "time_since_last_progress_seconds": 181,
        "parallelism_ratio": 1.0,
        "worker_cpu_efficiency": 1.0,
    }

    assert evaluate_abort_reason(status, no_progress_timeout_seconds=180) == "no_progress"


def test_evaluate_abort_reason_uses_low_runnable_ratio():
    status = {
        "samples_completed": 90,
        "samples_failed": 0,
        "samples_timed_out": 0,
        "samples_succeeded": 90,
        "samples_total": 100,
        "samples_runnable": 5,
        "time_since_last_progress_seconds": 10,
        "parallelism_ratio": 1.0,
        "worker_cpu_efficiency": 1.0,
    }

    assert evaluate_abort_reason(status, min_runnable_ratio=0.1) == "insufficient_runnable_samples"


def test_evaluate_abort_reason_uses_parallelism_collapse():
    status = {
        "samples_completed": 5,
        "samples_failed": 0,
        "samples_timed_out": 0,
        "samples_succeeded": 5,
        "samples_total": 100,
        "samples_runnable": 95,
        "time_since_last_progress_seconds": 181,
        "parallelism_ratio": 0.1,
        "worker_cpu_efficiency": 0.05,
    }

    assert (
        evaluate_abort_reason(
            status,
            no_progress_timeout_seconds=180,
            parallelism_collapse_ratio=0.25,
            worker_cpu_efficiency_threshold=0.1,
        )
        == "parallelism_collapse"
    )
