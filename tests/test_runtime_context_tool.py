from __future__ import annotations

from pathlib import Path

from trader.tools.runtime_context import validate_runtime_context


def test_validate_runtime_context_reports_missing_env_file(tmp_path: Path):
    payload, exit_code = validate_runtime_context(tmp_path / ".env", profile="base")

    assert exit_code == 1
    assert payload["status"] == "missing_env_file"


def test_validate_runtime_context_reports_missing_required_keys(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("TRADER_DB=\n", encoding="utf-8")

    payload, exit_code = validate_runtime_context(env_file, profile="db-backtest")

    assert exit_code == 2
    assert payload["status"] == "incomplete"
    assert payload["missing"] == ["TRADER_DB", "TRADER_EXCHANGE"]


def test_validate_runtime_context_reports_complete_context(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text('TRADER_DB="mongodb://localhost:27017/"\nTRADER_EXCHANGE="BINANCE"\n', encoding="utf-8")

    payload, exit_code = validate_runtime_context(env_file, profile="db-backtest", require_env=["TRADER_DB"])

    assert exit_code == 0
    assert payload["status"] == "complete"
    assert payload["required"] == ["TRADER_DB", "TRADER_EXCHANGE"]
