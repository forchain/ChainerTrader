#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trader.tools.optimization_status import build_status


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize optimization background run status")
    parser.add_argument("--run-id", required=True, help="Optimization run id")
    parser.add_argument("--tail", type=int, default=20, help="How many log lines to include")
    return parser.parse_args()
def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    args = parse_args()
    payload, exit_code = build_status(repo_root, args.run_id, args.tail)
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
