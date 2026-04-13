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

from dotenv import dotenv_values


PROFILE_REQUIREMENTS = {
    "base": [],
    "db-backtest": ["TRADER_DB", "TRADER_EXCHANGE"],
    "optimization": ["TRADER_DB", "TRADER_EXCHANGE"],
}


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
    env_file = args.env_file

    if not env_file.exists():
        print(f"✗  Missing .env file: {env_file}")
        return 1

    values = dotenv_values(env_file)
    required = list(PROFILE_REQUIREMENTS[args.profile])
    for key in args.require_env:
        if key not in required:
            required.append(key)

    print(f"Context profile : {args.profile}")
    print(f".env file       : {env_file.resolve()}")

    missing = []
    if required:
        print("Required env    :")
        for key in required:
            value = values.get(key)
            present = value is not None and str(value).strip() != ""
            status = "present" if present else "missing"
            print(f"  - {key}: {status}")
            if not present:
                missing.append(key)
    else:
        print("Required env    : none")

    if missing:
        print("")
        print("✗  Runtime context incomplete.")
        print("   Missing required env vars: " + ", ".join(missing))
        return 2

    print("")
    print("✓  Runtime context looks complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
