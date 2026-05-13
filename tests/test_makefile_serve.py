import os
import stat
import subprocess
from pathlib import Path


def test_serve_sets_python_warning_filter_for_backtrader_invalid_escape_warning():
    repo_root = Path(__file__).resolve().parents[1]
    makefile = (repo_root / "Makefile").read_text(encoding="utf-8")

    assert 'PYTHONWARNINGS="ignore:invalid escape sequence"' in makefile


def test_makefile_prefers_uv_run_for_test_lint_and_serve():
    repo_root = Path(__file__).resolve().parents[1]
    makefile = (repo_root / "Makefile").read_text(encoding="utf-8")

    assert 'USING_UV=$(shell command -v uv >/dev/null 2>&1 && echo "yes")' in makefile
    assert "uv run ruff check ." in makefile
    assert "uv run pytest tests/" in makefile
    assert 'PYTHONWARNINGS="ignore:invalid escape sequence" uv run trader' in makefile


def test_serve_runtime_defaults_to_ccxt_polling_market_stream():
    from trader.live.stream import GLOBAL_MARKET_STREAM_HUB, BinanceKlineWebSocketAdapter, CcxtPollingMarketStreamAdapter

    assert isinstance(GLOBAL_MARKET_STREAM_HUB.connector, CcxtPollingMarketStreamAdapter)
    assert not isinstance(GLOBAL_MARKET_STREAM_HUB.connector, BinanceKlineWebSocketAdapter)


def test_binance_live_smoke_script_loads_dotenv_with_python_dotenv_before_requiring_credentials():
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts" / "run_binance_live_smoke_e2e.sh").read_text(encoding="utf-8")

    assert "[ -f .env ]" in script
    assert "dotenv_values" in script
    assert ". ./.env" not in script
    assert script.index("dotenv_values") < script.index("BINANCE_API_KEY and BINANCE_API_SECRET must be set.")


def test_operational_readiness_script_enables_debug_app_logs_by_default():
    repo_root = Path(__file__).resolve().parents[1]
    script = (repo_root / "scripts" / "verify_live_operational_readiness.sh").read_text(encoding="utf-8")

    assert 'TRADER_LOG_LEVEL="${TRADER_LOG_LEVEL:-DEBUG}"' in script


def test_binance_live_smoke_script_accepts_dotenv_assignments_with_spaces(tmp_path):
    repo_root = Path(__file__).resolve().parents[1]
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [ "${1:-}" = "run" ] && [ "${2:-}" = "python" ]; then
  cat >/dev/null
  printf '%s\\n' 'export BINANCE_API_KEY=fake-key'
  printf '%s\\n' 'export BINANCE_API_SECRET=fake-secret'
  printf '%s\\n' 'export TRADER_DB=sqlite://:memory:'
  exit 0
fi
if [ "${1:-}" = "run" ] && [ "${2:-}" = "pytest" ]; then
  exit 0
fi
echo "unexpected uv args: $*" >&2
exit 64
""",
        encoding="utf-8",
    )
    fake_uv.chmod(fake_uv.stat().st_mode | stat.S_IXUSR)
    (tmp_path / ".env").write_text(
        """# python-dotenv style with spaces around equals
TRADER_COMMISSION = 0.001
BINANCE_API_KEY = fake-key
BINANCE_API_SECRET = fake-secret
TRADER_DB = sqlite://:memory:
""",
        encoding="utf-8",
    )

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env.pop("BINANCE_API_KEY", None)
    env.pop("BINANCE_API_SECRET", None)

    result = subprocess.run(
        ["bash", str(repo_root / "scripts" / "run_binance_live_smoke_e2e.sh")],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "TRADER_COMMISSION: command not found" not in result.stderr
