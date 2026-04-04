#!/usr/bin/env bash
# 测试脚本：验证 DB 优先下载功能
# 用法：bash scripts/test_db_download.sh [round1|round2|verify]

set -e
PYTHON=/Users/tonyoutlier/github.com/ChainerLabs/ChainerTrader/.claude/worktrees/loving-mirzakhani/.venv/bin/python3
SCRIPT=scripts/download_backtest_data.py
LOG_DIR=logs/test_db_download
mkdir -p "$LOG_DIR"

COINS=(BTC-USDT ETH-USDT BNB-USDT SOL-USDT XRP-USDT DOGE-USDT ADA-USDT AVAX-USDT TRX-USDT LINK-USDT)
DAILY_START="2017-01-01"
HOURLY_START="2025-01-01"

MODE=${1:-round1}

echo "============================================"
echo "  DB-First Download Test — Mode: $MODE"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "============================================"

run_downloads() {
    local round=$1
    local total_api=0
    local total_db=0

    for coin in "${COINS[@]}"; do
        for interval_cfg in "1d:$DAILY_START" "1h:$HOURLY_START"; do
            interval="${interval_cfg%%:*}"
            start="${interval_cfg##*:}"
            log="$LOG_DIR/${coin//-/}_${interval}_${round}.log"

            echo ""
            echo "▶ $coin $interval (start: $start)"
            $PYTHON $SCRIPT --symbol "$coin" --interval "$interval" --start-date "$start" 2>&1 | tee "$log"

            # Count API vs DB hits
            if grep -q "\[DB\] Case: fully covered" "$log"; then
                echo "  → ✓ DB 完全命中，无 API 调用"
                ((total_db++)) || true
            elif grep -q "\[DB\]" "$log"; then
                echo "  → ↓ DB 部分命中，补充下载缺失部分"
                ((total_db++)) || true
            else
                echo "  → ↓ 纯 API 模式下载"
                ((total_api++)) || true
            fi
        done
    done

    echo ""
    echo "============================================"
    echo "  Round $round 汇总"
    echo "  DB 命中（含部分）: $total_db / $((${#COINS[@]} * 2))"
    echo "  纯 API 下载:       $total_api / $((${#COINS[@]} * 2))"
    echo "============================================"
}

verify_outputs() {
    echo ""
    echo "=== 验证 CSV 文件 ==="
    local ok=0
    local fail=0
    for coin in "${COINS[@]}"; do
        symbol="${coin//-/}"
        for interval_cfg in "1d:$DAILY_START:$(date +%Y%m%d)" "1h:${HOURLY_START//-/}:$(date +%Y%m%d)"; do
            interval="${interval_cfg%%:*}"
            # Find matching CSV
            pattern="data/${symbol}-${interval}-*.csv"
            files=($pattern)
            if [ ${#files[@]} -gt 0 ] && [ -f "${files[0]}" ]; then
                size=$(wc -l < "${files[0]}")
                echo "  ✓ ${files[0]} (${size} rows)"
                ((ok++)) || true
            else
                echo "  ✗ MISSING: data/${symbol}-${interval}-*.csv"
                ((fail++)) || true
            fi
        done
    done
    echo ""
    echo "  CSV 存在: $ok / $((${#COINS[@]} * 2))"
    echo "  CSV 缺失: $fail / $((${#COINS[@]} * 2))"
}

verify_db() {
    echo ""
    echo "=== 验证 DB Collections ==="
    ENV_FILE=$(git rev-parse --show-superproject-working-tree 2>/dev/null || git rev-parse --show-toplevel 2>/dev/null || echo ".")
    $PYTHON - <<EOF
import os, sys
from dotenv import load_dotenv
load_dotenv(dotenv_path="${ENV_FILE}/.env")
from pymongo import MongoClient

uri = os.environ.get("TRADER_DB")
db_name = os.environ.get("TRADER_DB_NAME", "trader")
client = MongoClient(uri, serverSelectionTimeoutMS=5000)
db = client[db_name]

coins = ["BTC-USDT","ETH-USDT","BNB-USDT","SOL-USDT","XRP-USDT",
         "DOGE-USDT","ADA-USDT","AVAX-USDT","TRX-USDT","LINK-USDT"]
intervals = ["1d", "1h"]

ok = 0
fail = 0
for coin in coins:
    symbol = coin.replace("-", "")
    for iv in intervals:
        col_name = f"klines-{symbol}-{iv}"
        count = db[col_name].count_documents({})
        if count > 0:
            first = db[col_name].find_one({}, sort=[("open_time", 1)])["open_time"]
            last  = db[col_name].find_one({}, sort=[("open_time", -1)])["open_time"]
            from datetime import datetime
            print(f"  ✓ {col_name}: {count:,} candles  [{datetime.fromtimestamp(first).date()} ~ {datetime.fromtimestamp(last).date()}]")
            ok += 1
        else:
            print(f"  ✗ {col_name}: EMPTY")
            fail += 1

print(f"\n  DB 有数据: {ok} / {len(coins) * len(intervals)}")
print(f"  DB 为空:   {fail} / {len(coins) * len(intervals)}")
EOF
}

case $MODE in
    round1)
        run_downloads "round1"
        verify_db
        verify_outputs
        ;;
    round2)
        run_downloads "round2"
        ;;
    verify)
        verify_db
        verify_outputs
        ;;
    *)
        echo "Usage: $0 [round1|round2|verify]"
        exit 1
        ;;
esac
