from __future__ import annotations

import os
from pathlib import Path

from trader.common import path

DEFAULT_DB_URL = "sqlite://data/trader.db"
MODELS_MODULE = "trader.database.models"
MIGRATIONS_MODULE = "trader.database.migrations"


def normalize_db_url(db_url: str | None) -> str:
    if not db_url:
        return DEFAULT_DB_URL
    return db_url


def ensure_sqlite_parent_dir(db_url: str) -> None:
    if not db_url.startswith("sqlite://"):
        return

    raw_path = db_url.removeprefix("sqlite://")
    if raw_path == ":memory:":
        return
    if raw_path.startswith("/"):
        db_path = Path(raw_path)
    else:
        db_path = Path(path.GetProjectDir()) / raw_path
    db_path.parent.mkdir(parents=True, exist_ok=True)


def build_tortoise_config(db_url: str | None) -> dict:
    normalized_url = normalize_db_url(db_url)
    ensure_sqlite_parent_dir(normalized_url)
    return {
        "connections": {
            "default": normalized_url,
        },
        "apps": {
            "models": {
                "models": [MODELS_MODULE],
                "default_connection": "default",
                "migrations": MIGRATIONS_MODULE,
            },
        },
    }


TORTOISE_ORM = build_tortoise_config(os.environ.get("TRADER_DB", DEFAULT_DB_URL))
