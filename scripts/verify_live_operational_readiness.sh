#!/usr/bin/env bash
set -euo pipefail

RUN_SECONDS="${CHAINERTRADER_OPERATIONAL_VERIFY_SECONDS:-240}"
MIN_REQUEST_SPACING_SECONDS="${CHAINERTRADER_OPERATIONAL_MIN_REQUEST_SPACING_SECONDS:-10}"
LOG_PATH="${CHAINERTRADER_OPERATIONAL_LOG_PATH:-/tmp/chainer_live_operational_verify.log}"
STDOUT_PATH="${CHAINERTRADER_OPERATIONAL_STDOUT_PATH:-/tmp/chainer_live_operational_verify.stdout.log}"

rm -f "$LOG_PATH" "$STDOUT_PATH"

echo "Starting make serve for operational verification: seconds=$RUN_SECONDS log=$LOG_PATH"
TRADER_LOG_FILE="$LOG_PATH" TRADER_LOG_LEVEL="${TRADER_LOG_LEVEL:-DEBUG}" make serve >"$STDOUT_PATH" 2>&1 &
PID=$!

cleanup() {
  if kill -0 "$PID" >/dev/null 2>&1; then
    kill "$PID" >/dev/null 2>&1 || true
    wait "$PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

DEADLINE=$((SECONDS + RUN_SECONDS))
while (( SECONDS < DEADLINE )); do
  if ! kill -0 "$PID" >/dev/null 2>&1; then
    echo "make serve exited before operational verification window completed. stdout=$STDOUT_PATH log=$LOG_PATH" >&2
    exit 1
  fi
  REMAINING=$((DEADLINE - SECONDS))
  if (( REMAINING > 5 )); then
    sleep 5 || true
  else
    sleep "$REMAINING" || true
  fi
done
cleanup
trap - EXIT

uv run python -m trader.tools.live_operational_verify \
  --log "$LOG_PATH" \
  --min-request-spacing-seconds "$MIN_REQUEST_SPACING_SECONDS"
