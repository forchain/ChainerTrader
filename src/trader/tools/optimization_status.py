from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Callable

TERMINAL_STAGES = {"finished", "aborted"}


def default_process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def build_status(
    repo_root: Path,
    run_id: str,
    tail: int = 20,
    process_exists: Callable[[int], bool] = default_process_exists,
) -> tuple[dict, int]:
    run_dir = repo_root / "tmp" / "optimization_runs" / run_id
    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        return {"run_id": run_id, "status": "missing"}, 1

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    pid = meta["pid"]
    log_path = Path(meta["log_path"])
    status_path = run_dir / "status.json"
    runtime_status = None
    if status_path.exists():
        runtime_status = json.loads(status_path.read_text(encoding="utf-8"))

    proc_exists = process_exists(pid)
    if runtime_status and runtime_status.get("stage") in TERMINAL_STAGES:
        proc_exists = False

    report_dir = repo_root / "reports" / "optimizations" / run_id
    manifest_exists = (report_dir / "manifest.json").exists()

    log_tail = []
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        log_tail = lines[-tail:]

    status = runtime_status.get("stage") if runtime_status else None
    if status is None and manifest_exists:
        status = "finished"
        proc_exists = False
    if status is None:
        status = "running" if proc_exists else "exited"

    payload = {
        "run_id": run_id,
        "status": status,
        "pid": pid,
        "process_running": proc_exists,
        "log_path": str(log_path),
        "status_path": str(status_path) if status_path.exists() else None,
        "runtime_status": runtime_status,
        "report_dir_exists": report_dir.exists(),
        "manifest_exists": manifest_exists,
        "aggregate_exists": (report_dir / "aggregate.json").exists(),
        "rankings_exists": (report_dir / "rankings" / "by_score.json").exists(),
        "log_tail": log_tail,
    }
    return payload, 0
