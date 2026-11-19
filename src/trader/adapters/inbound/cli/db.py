from __future__ import annotations

import subprocess
import sys

CONFIG_PATH = "trader.adapters.outbound.persistence.config.TORTOISE_ORM"


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("Usage: trader-db <init|makemigrations|migrate|history|heads|sqlmigrate|downgrade> [args...]")
        return 2

    cmd = ["tortoise", "-c", CONFIG_PATH, *args]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
