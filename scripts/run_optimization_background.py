#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from trader.task.task_config import parse_task_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run optimization tasks in background with low-token logging")
    parser.add_argument("--tasks", required=True, help="Path to tasks JSON")
    parser.add_argument("--stat", type=int, default=500, help="Stat limit passed to trader")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    tasks_path = (repo_root / args.tasks).resolve() if not Path(args.tasks).is_absolute() else Path(args.tasks)
    parsed = parse_task_config(str(tasks_path))
    if not parsed:
        print("No executable tasks found", file=sys.stderr)
        return 1

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
        str(tasks_path),
        "--stat",
        str(args.stat),
    ]

    env = os.environ.copy()
    env["TRADER_API"] = ""

    with log_path.open("w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(
            command,
            cwd=repo_root,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env=env,
        )

    pid_path.write_text(str(proc.pid), encoding="utf-8")
    meta_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "tasks_path": str(tasks_path),
                "sample_count": len(parsed),
                "pid": proc.pid,
                "log_path": str(log_path),
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(json.dumps({"run_id": run_id, "pid": proc.pid, "log_path": str(log_path), "meta_path": str(meta_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
