import os
import sqlite3
import subprocess
import sys


def test_trader_db_migrate_initializes_required_schema_for_new_sqlite_db(tmp_path):
    db_path = tmp_path / "acceptance.db"
    db_url = f"sqlite://{db_path}"
    env = {**os.environ, "TRADER_DB": db_url}

    result = subprocess.run(
        [sys.executable, "-m", "trader.tools.db", "migrate"],
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=30,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    assert {"klines", "tasks", "availability", "execution_states", "users", "sessions", "exchange_credentials", "strategy_configs"} <= tables
    with sqlite3.connect(db_path) as connection:
        execution_state_columns = {
            row[1]
            for row in connection.execute(
                'PRAGMA table_info("execution_states")'
            )
        }
    assert "task_id" in execution_state_columns
