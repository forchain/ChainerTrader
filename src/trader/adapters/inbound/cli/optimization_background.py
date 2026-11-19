from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable

from trader.task.task_config import parse_task_config


def launch_background_run(
    repo_root: Path,
    tasks_path: Path,
    stat: int = 500,
    popen: Callable[..., subprocess.Popen] = subprocess.Popen,
) -> tuple[dict, int]:
    resolved_tasks_path = tasks_path.resolve()
    parsed = parse_task_config(str(resolved_tasks_path))
    if not parsed:
        return {"status": "no_tasks", "tasks_path": str(resolved_tasks_path)}, 1

    run_id = next((task.optimization_run_id for task in parsed if task.optimization_run_id), "adhoc-run")
    run_dir = repo_root / "tmp" / "optimization_runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    log_path = run_dir / "runner.log"
    meta_path = run_dir / "meta.json"
    pid_path = run_dir / "runner.pid"

    command = [
        "uv",
        "run",
        "python",
        "-m",
        "trader",
        "--tasks",
        str(resolved_tasks_path),
        "--stat",
        str(stat),
    ]

    env = os.environ.copy()
    env["TRADER_API"] = ""
    env["TRADER_NOTICE"] = "[]"
    env["TRADER_TASKS"] = str(resolved_tasks_path)
    env["TRADER_OPTIMIZATION_RUN_ID"] = run_id

    with log_path.open("w", encoding="utf-8") as log_file:
        proc = popen(
            command,
            cwd=repo_root,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )

    pid_path.write_text(str(proc.pid), encoding="utf-8")
    meta_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "tasks_path": str(resolved_tasks_path),
                "sample_count": len(parsed),
                "pid": proc.pid,
                "log_path": str(log_path),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return {
        "run_id": run_id,
        "pid": proc.pid,
        "log_path": str(log_path),
        "meta_path": str(meta_path),
    }, 0
