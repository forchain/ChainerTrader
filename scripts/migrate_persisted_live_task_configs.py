#!/usr/bin/env python3

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from dotenv import load_dotenv

from trader.common.config import Config, TRADER_DB
from trader.common.logger import Logger
from trader.database.manager import DatabaseManager
from trader.task.persisted_live_config_migration import migrate_persisted_live_task_configs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-shot migration for persisted live task configs.")
    parser.add_argument(
        "--db",
        help="Enable database with a Tortoise ORM URL (default: sqlite://data/trader.db)",
        nargs="?",
        const="sqlite://data/trader.db",
        default=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = parse_args(argv)
    db_url = getattr(args, "db", None) or os.environ.get(TRADER_DB) or "sqlite://data/trader.db"
    cfg = Config(db=db_url)
    db_manager = DatabaseManager(cfg, Logger(cfg))

    try:
        report = asyncio.run(_run_migration(db_manager))
    except Exception as exc:
        print(f"persisted live config migration failed: {exc}", file=sys.stderr)
        return 1

    print(
        "persisted live config migration complete: "
        f"scanned={report.scanned} updated={report.updated} skipped={report.skipped}"
    )
    return 0


async def _run_migration(db_manager: DatabaseManager):
    await db_manager.start()
    try:
        task_repo = getattr(db_manager, "task", None)
        if task_repo is None or not hasattr(task_repo, "get_all_tasks") or not hasattr(task_repo, "add_tasks"):
            raise RuntimeError("task persistence is unavailable for persisted live config migration")
        return await migrate_persisted_live_task_configs(task_repo)
    finally:
        await db_manager.stop()


if __name__ == "__main__":
    raise SystemExit(main())
