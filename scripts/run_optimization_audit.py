#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from trader.task.optimization_audit_workflow import run_optimization_audit


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate optimization audit artifacts and enforce blocking rules.")
    parser.add_argument("--run-id", required=True, help="Optimization run id under reports/optimizations/")
    parser.add_argument("--base-dir", default=".", help="Repository base directory")
    parser.add_argument("--no-block", action="store_true", help="Do not exit non-zero when blockers are detected")
    args = parser.parse_args()

    result = run_optimization_audit(Path(args.base_dir), args.run_id, block_on_failure=not args.no_block)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "passed" or args.no_block else 1


if __name__ == "__main__":
    sys.exit(main())
