#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize optimization background run status")
    parser.add_argument("--run-id", required=True, help="Optimization run id")
    parser.add_argument("--tail", type=int, default=20, help="How many log lines to include")
    return parser.parse_args()


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    args = parse_args()
    run_dir = repo_root / "tmp" / "optimization_runs" / args.run_id
    meta_path = run_dir / "meta.json"
    if not meta_path.exists():
        print(json.dumps({"run_id": args.run_id, "status": "missing"}))
        return 1

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    pid = meta["pid"]
    log_path = Path(meta["log_path"])
    proc_exists = Path(f"/proc/{pid}").exists() if Path("/proc").exists() else True
    report_dir = repo_root / "reports" / "optimizations" / args.run_id

    log_tail = []
    if log_path.exists():
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        log_tail = lines[-args.tail :]

    payload = {
        "run_id": args.run_id,
        "pid": pid,
        "process_running": proc_exists,
        "log_path": str(log_path),
        "report_dir_exists": report_dir.exists(),
        "manifest_exists": (report_dir / "manifest.json").exists(),
        "aggregate_exists": (report_dir / "aggregate.json").exists(),
        "rankings_exists": (report_dir / "rankings" / "by_score.json").exists(),
        "log_tail": log_tail,
    }
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
