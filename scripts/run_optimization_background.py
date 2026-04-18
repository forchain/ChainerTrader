#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trader.tools.optimization_background import launch_background_run


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run optimization tasks in background with low-token logging")
    parser.add_argument("--tasks", required=True, help="Path to tasks JSON")
    parser.add_argument("--stat", type=int, default=500, help="Stat limit passed to trader")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    tasks_path = (repo_root / args.tasks).resolve() if not Path(args.tasks).is_absolute() else Path(args.tasks)
    payload, exit_code = launch_background_run(repo_root, tasks_path, stat=args.stat)
    if exit_code != 0:
        print("No executable tasks found", file=sys.stderr)
        return exit_code

    print(json.dumps(payload, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
