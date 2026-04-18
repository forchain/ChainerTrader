#!/usr/bin/env python3
"""
Validate runtime context for worktree sessions using the same dotenv parser as the app.

Examples:
  .venv/bin/python scripts/check_runtime_context.py
  .venv/bin/python scripts/check_runtime_context.py --profile db-backtest
  .venv/bin/python scripts/check_runtime_context.py --require-env TRADER_DB --require-env TRADER_EXCHANGE
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trader.tools.runtime_context import PROFILE_REQUIREMENTS, validate_runtime_context


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate worktree runtime context")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(".env"),
        help="Path to .env file (default: ./.env)",
    )
    parser.add_argument(
        "--profile",
        choices=sorted(PROFILE_REQUIREMENTS.keys()),
        default="base",
        help="Validation profile",
    )
    parser.add_argument(
        "--require-env",
        action="append",
        default=[],
        help="Additional required environment variable names",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload, exit_code = validate_runtime_context(args.env_file, profile=args.profile, require_env=args.require_env)

    if payload["status"] == "missing_env_file":
        print(f"✗  Missing .env file: {args.env_file}")
        return exit_code

    print(f"Context profile : {payload['profile']}")
    print(f".env file       : {payload['env_file']}")

    required = payload["required"]
    missing = payload["missing"]
    if required:
        print("Required env    :")
        for key in required:
            status = "missing" if key in missing else "present"
            print(f"  - {key}: {status}")
    else:
        print("Required env    : none")

    if missing:
        print("")
        print("✗  Runtime context incomplete.")
        print("   Missing required env vars: " + ", ".join(missing))
        return exit_code

    print("")
    print("✓  Runtime context looks complete.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
