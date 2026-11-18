from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from trader.core.optimization.domain import TERMINAL_STAGES
from trader.core.optimization.interfaces import TaskConfigFileStore


class OptimizationBackgroundStatusUseCase:
    """Compute optimization background run health from persisted runtime metadata and process probe."""

    def __init__(self, *, config_store: TaskConfigFileStore, base_dir: Path):
        self.config_store = config_store
        self.base_dir = Path(base_dir)

    def build_status(
        self,
        run_id: str,
        *,
        tail: int = 20,
        process_exists: Callable[[int], bool],
    ) -> tuple[dict[str, Any], int]:
        run_dir = self.base_dir / "tmp" / "optimization_runs" / run_id
        meta_path = run_dir / "meta.json"
        if not self.config_store.exists(str(meta_path)):
            return {"run_id": run_id, "status": "missing"}, 1

        meta = self.config_store.load_json(str(meta_path))
        pid = meta["pid"]
        log_path = Path(meta["log_path"])
        status_path = run_dir / "status.json"
        runtime_status = self.config_store.load_json(str(status_path)) if self.config_store.exists(str(status_path)) else None

        proc_exists = process_exists(pid)
        if runtime_status and runtime_status.get("stage") in TERMINAL_STAGES:
            proc_exists = False

        report_dir = self.base_dir / "reports" / "optimizations" / run_id
        manifest_exists = (report_dir / "manifest.json").exists()

        log_tail: list[str] = []
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
