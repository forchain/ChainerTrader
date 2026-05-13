#!/usr/bin/env bash
set -euo pipefail

if [ -f .env ]; then
  eval "$(
    uv run python - <<'PY'
from pathlib import Path
from dotenv import dotenv_values

for key, value in dotenv_values(Path(".env")).items():
    if value is None:
        continue
    print(f'export {key}={value!r}')
PY
  )"
fi

if [ -z "${BINANCE_API_KEY:-}" ] || [ -z "${BINANCE_API_SECRET:-}" ]; then
  echo "BINANCE_API_KEY and BINANCE_API_SECRET must be set."
  exit 1
fi
if [ -z "${TRADER_DB:-}" ]; then
  echo "TRADER_DB must be set for execution_state closure verification."
  exit 1
fi

export CHAINERTRADER_ENABLE_BINANCE_LIVE_E2E="${CHAINERTRADER_ENABLE_BINANCE_LIVE_E2E:-1}"
export CHAINERTRADER_LIVE_SMOKE_DRIVER="${CHAINERTRADER_LIVE_SMOKE_DRIVER:-ccxt}"
export CHAINERTRADER_SMALL_LIVE_MAX_NOTIONAL="${CHAINERTRADER_SMALL_LIVE_MAX_NOTIONAL:-11}"
export CHAINERTRADER_SMALL_LIVE_HARD_LIMIT="${CHAINERTRADER_SMALL_LIVE_HARD_LIMIT:-25}"
export CHAINERTRADER_LIVE_SMOKE_SYMBOL="${CHAINERTRADER_LIVE_SMOKE_SYMBOL:-BTC-USDT}"
export CHAINERTRADER_LIVE_SMOKE_ENABLE_MARGIN="${CHAINERTRADER_LIVE_SMOKE_ENABLE_MARGIN:-1}"
export CHAINERTRADER_LIVE_SMOKE_ENABLE_SPOT="${CHAINERTRADER_LIVE_SMOKE_ENABLE_SPOT:-1}"

uv run pytest tests/test_binance_live_smoke_e2e.py::test_binance_live_smoke_covers_chainer_protection_and_macd_metadata -q -s
