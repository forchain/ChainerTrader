from __future__ import annotations

import json
from pathlib import Path

TERMINAL_STAGES = {"finished", "aborted"}


def build_status(repo_root: Path, run_id: str, tail: int = 20) -> tuple[dict, int]:
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

    proc_exists = Path(f"/proc/{pid}").exists() if Path("/proc").exists() else True
    if runtime_status and runtime_status.get("stage") in TERMINAL_STAGES:
        proc_exists = False

    report_dir = repo_root / "reports" / "optimizations" / run_id

    log_tail = []
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        log_tail = lines[-tail:]

    payload = {
        "run_id": run_id,
        "status": runtime_status.get("stage") if runtime_status else ("running" if proc_exists else "unknown"),
        "pid": pid,
        "process_running": proc_exists,
        "log_path": str(log_path),
        "status_path": str(status_path) if status_path.exists() else None,
        "runtime_status": runtime_status,
        "report_dir_exists": report_dir.exists(),
        "manifest_exists": (report_dir / "manifest.json").exists(),
        "aggregate_exists": (report_dir / "aggregate.json").exists(),
        "rankings_exists": (report_dir / "rankings" / "by_score.json").exists(),
        "log_tail": log_tail,
    }
    return payload, 0
