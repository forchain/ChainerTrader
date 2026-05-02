from __future__ import annotations

import subprocess
import sys

from trader.database.config import TORTOISE_ORM

CONFIG_PATH = "trader.database.config.TORTOISE_ORM"


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("Usage: trader-db <init|makemigrations|migrate|history|heads|sqlmigrate|downgrade> [args...]")
        return 2

    # Importing TORTOISE_ORM here ensures packaging tools include the config module.
    _ = TORTOISE_ORM
    cmd = ["tortoise", "-c", CONFIG_PATH, *args]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
