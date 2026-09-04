"""Tests for the worker PID mapping lifecycle used by the optimization monitor dashboard."""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from trader.task.backtrader_task import _write_worker_pid


# ---------------------------------------------------------------------------
# _write_worker_pid helper
# ---------------------------------------------------------------------------


def test_write_worker_pid_creates_file(tmp_path, monkeypatch):
    """PID file should be written to workers/<pid>.json under the run dir."""
    monkeypatch.chdir(tmp_path)
    run_id = "test-run-abc123"
    task_id = 42

    pid_file = _write_worker_pid(run_id, task_id)

    assert pid_file is not None
    assert pid_file.exists(), "PID mapping file must exist after _write_worker_pid"
    payload = json.loads(pid_file.read_text(encoding="utf-8"))
    assert payload["task_id"] == task_id
    assert payload["run_id"] == run_id
    assert payload["pid"] == os.getpid()
    assert "started_at" in payload


def test_write_worker_pid_returns_none_when_no_run_id():
    """When run_id is None (non-optimization task), no file is written."""
    result = _write_worker_pid(None, 1)
    assert result is None


def test_write_worker_pid_is_idempotent_for_same_pid(tmp_path, monkeypatch):
    """Writing again for the same PID overwrites atomically—no stale tmp files."""
    monkeypatch.chdir(tmp_path)
    run_id = "run-idem"
    _write_worker_pid(run_id, 1)
    pid_file = _write_worker_pid(run_id, 2)
    assert pid_file is not None
    payload = json.loads(pid_file.read_text(encoding="utf-8"))
    assert payload["task_id"] == 2, "Second call should overwrite the first"
    # No leftover .tmp file
    assert not list(pid_file.parent.glob("*.tmp")), "No temporary files should remain"


# ---------------------------------------------------------------------------
# run_backtest_sample PID lifecycle
# ---------------------------------------------------------------------------


def _make_minimal_spec(run_id: str | None = "run-xyz", task_id: int = 99):
    """Return a minimal BacktestSampleSpec-like object for PID lifecycle tests."""
    from trader.task.backtrader_task import BacktestSampleSpec

    return BacktestSampleSpec(
        task_id=task_id,
        strategy_name="dummy",
        strategy_names=["dummy"],
        symbol="BTC-USDT",
        interval="1h",
        start_time=0,
        end_time=0,
        data_path="/nonexistent",
        use_data_range=False,
        free_cash=1000.0,
        cfg={},
        strategy_params={},
        optimization_run_id=run_id,
        param_id=None,
        dataset_key=None,
    )


def test_pid_file_removed_after_successful_run(tmp_path, monkeypatch):
    """PID file must be deleted in the finally block even on success."""
    monkeypatch.chdir(tmp_path)
    spec = _make_minimal_spec()

    # Patch heavy internals so the function returns quickly with an error (ok=False)
    with patch("trader.task.backtrader_task.Config"), \
         patch("trader.task.backtrader_task.Logger"), \
         patch("trader.task.backtrader_task.parse_strategies", return_value=None):
        from trader.task.backtrader_task import run_backtest_sample
        result = run_backtest_sample(spec)

    assert not result.ok
    workers_dir = tmp_path / "tmp" / "optimization_runs" / spec.optimization_run_id / "workers"
    remaining = list(workers_dir.glob("*.json"))
    assert remaining == [], f"PID files should be removed after run, found: {remaining}"


def test_pid_file_removed_after_exception(tmp_path, monkeypatch):
    """PID file must be cleaned up even when execution raises an unhandled exception."""
    monkeypatch.chdir(tmp_path)
    spec = _make_minimal_spec()

    with patch("trader.task.backtrader_task.Config"), \
         patch("trader.task.backtrader_task.Logger"), \
         patch("trader.task.backtrader_task.parse_strategies", side_effect=RuntimeError("boom")):
        from trader.task.backtrader_task import run_backtest_sample
        result = run_backtest_sample(spec)

    assert not result.ok
    assert "boom" in (result.error or "")
    workers_dir = tmp_path / "tmp" / "optimization_runs" / spec.optimization_run_id / "workers"
    remaining = list(workers_dir.glob("*.json"))
    assert remaining == [], f"PID files should be removed even after exception, found: {remaining}"
