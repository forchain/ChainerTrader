#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -f .git ] && [ ! -d .venv ]; then
  bash scripts/setup_worktree.sh
fi

if [ -f .env ]; then
  eval "$({
    uv run python - <<'PY'
from pathlib import Path
from dotenv import dotenv_values
for key, value in dotenv_values(Path('.env')).items():
    if value is None:
        continue
    print(f"export {key}={value!r}")
PY
  })"
fi

: "${BINANCE_API_KEY:?BINANCE_API_KEY must be set}"
: "${BINANCE_API_SECRET:?BINANCE_API_SECRET must be set}"
: "${TRADER_DB:?TRADER_DB must be set}"

TASKS_FILE="${CHAINERTRADER_PROD_FAST_TASKS_FILE:-configs/tasks/live/production_fast_signal_smoke.json}"
RUN_SECONDS="${CHAINERTRADER_PROD_FAST_RUN_SECONDS:-420}"
LOG_FILE="${CHAINERTRADER_PROD_FAST_LOG_FILE:-/tmp/chainer_prod_fast_signal_smoke.log}"
REPORT_FILE="${CHAINERTRADER_PROD_FAST_REPORT_FILE:-/tmp/chainer_prod_fast_signal_smoke_report.json}"

if [ ! -f "$TASKS_FILE" ]; then
  echo "tasks file not found: $TASKS_FILE" >&2
  exit 1
fi

export CHAINERTRADER_SMALL_LIVE_HARD_LIMIT="${CHAINERTRADER_SMALL_LIVE_HARD_LIMIT:-25}"
export CHAINERTRADER_SMALL_LIVE_MAX_NOTIONAL="${CHAINERTRADER_SMALL_LIVE_MAX_NOTIONAL:-11}"
export BINANCE_MARGIN_BASE_PATH="${BINANCE_MARGIN_BASE_PATH:-https://api.binance.com}"
export BINANCE_SPOT_BASE_PATH="${BINANCE_SPOT_BASE_PATH:-https://api.binance.com}"

# Force runtime exchange credentials from BINANCE_* for this production smoke run.
export TRADER_EXCHANGE="${TRADER_EXCHANGE_OVERRIDE:-{\"name\":\"BINANCE\",\"driver\":\"ccxt\",\"api_key\":\"${BINANCE_API_KEY}\",\"api_secret\":\"${BINANCE_API_SECRET}\",\"spot_base_path\":\"${BINANCE_SPOT_BASE_PATH}\",\"margin_base_path\":\"${BINANCE_MARGIN_BASE_PATH}\"}}"

rm -f "$LOG_FILE" "$REPORT_FILE"

echo "[prod-smoke] starting trader process"
(
  set -o pipefail
  timeout "$RUN_SECONDS" uv run python -m trader --tasks "$TASKS_FILE" 2>&1 | tee "$LOG_FILE"
) || true

# Build black-box evidence from operator-visible logs.
uv run python - <<'PY'
import ast
import json
import re
from pathlib import Path

log_path = Path('/tmp/chainer_prod_fast_signal_smoke.log')
report_path = Path('/tmp/chainer_prod_fast_signal_smoke_report.json')

if not log_path.exists():
    raise SystemExit('log file missing')

text = log_path.read_text(encoding='utf-8', errors='ignore')
lines = text.splitlines()

submitted = []
failed = []
signal_lines = []
cancel_lines = []

for ln in lines:
    if 'Realtime strategy signal:' in ln:
        signal_lines.append(ln)
    if '[auto_execution] submitted ' in ln:
        payload_txt = ln.split('[auto_execution] submitted ', 1)[1].strip()
        try:
            payload = ast.literal_eval(payload_txt)
        except Exception:
            payload = {'raw': payload_txt}
        submitted.append(payload)
    if '[auto_execution] failed ' in ln:
        payload_txt = ln.split('[auto_execution] failed ', 1)[1].strip()
        try:
            payload = ast.literal_eval(payload_txt)
        except Exception:
            payload = {'raw': payload_txt}
        failed.append(payload)
    if 'CANCELED' in ln or 'cancel' in ln.lower():
        if 'order' in ln.lower():
            cancel_lines.append(ln)

# Hard guardrails:
# 1) success must include order_id
# 2) failures must be explicit (presence of failed payload if any failed path)
for item in submitted:
    oid = item.get('order_id') if isinstance(item, dict) else None
    if not oid:
        raise SystemExit('hard_fail: submitted outcome without order_id')

summary = {
    'signals_detected': len(signal_lines),
    'submitted_count': len(submitted),
    'failed_count': len(failed),
    'cancel_related_lines': len(cancel_lines),
    'submitted': submitted,
    'failed': failed,
    'signal_samples': signal_lines[:20],
    'cancel_samples': cancel_lines[:20],
}

report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False))

if len(submitted) == 0:
    raise SystemExit('hard_fail: no submitted exchange order observed')
PY

echo "[prod-smoke] collecting cleanup/cancel evidence"
set +e
CLEANUP_EXIT=1
for attempt in 1 2; do
  CHAINERTRADER_LIVE_SMOKE_CLEANUP_ONLY=1 uv run python -m trader.tools.binance_live_smoke >/tmp/chainer_prod_fast_signal_cleanup.log 2>&1
  CLEANUP_EXIT=$?
  if [ "$CLEANUP_EXIT" -eq 0 ]; then
    break
  fi
  if rg -n --fixed-strings "Timestamp for this request is outside" /tmp/chainer_prod_fast_signal_cleanup.log >/dev/null 2>&1; then
    echo "[prod-smoke] cleanup attempt $attempt hit -1021 time drift, retrying once..." >&2
    sleep 2
    continue
  fi
  break
done
set -e
if [ "$CLEANUP_EXIT" -ne 0 ]; then
  echo "[prod-smoke] cleanup command failed, see /tmp/chainer_prod_fast_signal_cleanup.log" >&2
fi

echo "[prod-smoke] completed"
echo "[prod-smoke] log: $LOG_FILE"
echo "[prod-smoke] report: $REPORT_FILE"
echo "[prod-smoke] cleanup_log: /tmp/chainer_prod_fast_signal_cleanup.log"
