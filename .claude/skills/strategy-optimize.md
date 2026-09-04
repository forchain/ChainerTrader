---
name: strategy-optimize
description: Iteratively optimize a trading strategy by analyzing JSON backtest reports, identifying problems, making targeted code changes, and comparing metrics. Uses One Change Rule and anti-overfitting validation.
---

# Strategy Optimization Workflow

You are optimizing a ChainerTrader strategy. **Always start by asking the user to choose a mode.**

## Mode Selection (FIRST STEP)

Ask user:
> Which optimization mode do you prefer?
>
> 1. **Auto Mode** (default)
>    - I run 20 iterations automatically, making decisions on problem identification and hypothesis
>    - You get a final summary at the end
>    - Can specify custom iteration count with `--iterations N`
>
> 2. **Manual Mode**
>    - After each iteration, I generate an analysis report for your review
>    - You decide which problems to fix and which hypotheses to try
>    - You can reject my suggestions or request different changes
>    - I wait for your approval before implementing each change
>
> **Default: Auto Mode** (press Enter or say "auto")

Store the mode and iteration count. Continue below based on selection.

## Pre-flight Checklist

Before starting, verify ALL of these:

### 1. Data Sufficiency Check (CRITICAL)

Read the task config JSON (e.g., `backtest_full_4years.json`):
- **Extract**: `symbol`, `interval`, `csv` file path
- **Verify data file exists** and check its size/row count
- **Minimum requirements** for valid optimization:
  - ≥ 2 years of historical data (for crypto markets)
  - ≥ 50-100 sample trades (depends on signal frequency)
  - If total_trades < 30: **STOP** and download more data

**If data is insufficient:**
```bash
# Download more data using generic script
uv run --with requests --with pandas python3 scripts/download_backtest_data.py \
  --symbol <SYMBOL> --interval <INTERVAL> --years <YEARS>

# Example for BTC daily data:
uv run --with requests --with pandas python3 scripts/download_backtest_data.py \
  --symbol BTC-USDT --interval 1d --years 5

# Example for ETH hourly (4 years):
uv run --with requests --with pandas python3 scripts/download_backtest_data.py \
  --symbol ETH-USDT --interval 1h --years 4
```

### 2. Run Full Backtest

Execute backtest with complete historical data:
```bash
bash scripts/backtest_cli.sh <config_json>
```

Read the latest JSON report from `reports/` and verify:
- `total_trades` ≥ 50 minimum (ideally ≥ 100)
- Record baseline: `sharpe`, `profit_factor`, `max_dd_pct`, `total_trades`, `win_rate_pct`

**Example baseline format:**
```
Baseline: Sharpe=-0.07, PF=1.87, MaxDD=3.89%, Trades=17, WinRate=41%
Data: 4 years (35,986 bars), 2021-01 ~ 2024-12
```

### 3. Infrastructure Check

- JSON report system works (verified by step 2)
- Train/Val config files exist: `scripts/backtest_train.json`, `scripts/backtest_val.json`

**If any check fails → STOP and fix infrastructure first.**

## Target Metrics

| Metric | Target | Hard Constraint |
|--------|--------|----------------|
| Sharpe Ratio | > 1.0 | — |
| Profit Factor | > 1.5 | — |
| Max Drawdown | — | < 20% |
| Total Trades | — | ≥ 10 |
| Val Sharpe | — | ≥ Train Sharpe × 0.7 |

## Problem Identification Priority

When reading a JSON report, identify the HIGHEST priority problem:

1. **P1**: Sharpe < 0 → Strategy loses money risk-adjusted. Focus: reduce losing trades or increase win quality
2. **P2**: Total trades < 10 → Not enough signals. Focus: relax entry conditions or add new signal sources
3. **P3**: Max Drawdown > 20% → Risk too high. Focus: tighten stop-loss or reduce position sizing
4. **P4**: Profit Factor < 1.0 → Losses exceed gains. Focus: improve exit timing or entry filtering
5. **P5**: Val Sharpe < Train Sharpe × 0.7 → Overfitting. Focus: simplify logic, remove over-tuned parameters

## Iteration Loop

### AUTO MODE
If user selected Auto Mode: Follow Steps 1-8 below for each iteration (up to specified count), without pausing for user review. Proceed automatically unless optimization targets are met or stop conditions triggered.

### MANUAL MODE
If user selected Manual Mode: Follow Steps 1-7 below, then pause at Step 8 to present Analysis Report for user review before proceeding.

---

### Step 1: Run Train Backtest
```bash
bash scripts/backtest_cli.sh scripts/backtest_train.json
```

### Step 2: Read Report
Read the LATEST JSON file in `reports/` (sort by filename timestamp).
Do NOT read log files or CSV data.

### Step 3: Identify Problem
Using the Priority list above, identify the single highest-priority problem.

### Step 4: Formulate Hypothesis
State ONE specific hypothesis. Example:
- "Signal fires on every bar after detection because _detect_bottom_triple_divergence returns True repeatedly → add a one-shot flag"
- "Only 5 trades in 13 months → relax opp_ratio from 0.35 to 0.5 to detect more divergence patterns"

### Step 5: Implement ONE Change
- Change exactly ONE function, ONE parameter, or ONE block of logic
- Record the change with `git diff` before running

### Step 6: Run Train Backtest Again
```bash
bash scripts/backtest_cli.sh scripts/backtest_train.json
```

### Step 7: Compare Metrics
Read the new JSON report. Compare with previous iteration:

- **ACCEPT** if: Sharpe improved OR (Sharpe unchanged AND Profit Factor improved)
- **REJECT** if: Sharpe worsened OR Max Drawdown increased beyond 20%

If REJECTED:
```bash
git checkout -- src/trader/strategy/
```
Record: "FAILED: [hypothesis] → [result]"

### Step 8: Manual Mode Review (if applicable)

**ONLY FOR MANUAL MODE:**

Generate and present Analysis Report to user. Do NOT implement change yet. Format:

```
## 📊 Iteration [N] - Analysis Report

### Baseline vs Previous
- Sharpe: [prev] → [current] (Δ [change]%) ⬆️/⬇️
- PF: [prev] → [current] (Δ [change]%) ⬆️/⬇️
- MaxDD: [prev] → [current] (Δ [change]%) ⬆️/⬇️
- Win Rate: [prev] → [current] (Δ [change]%) ⬆️/⬇️
- Trades: [count]

### Current Problem (Priority)
**[P1-P5]**: [Problem Description]
- Example: "P1 - Sharpe < 0: Only 7/17 trades profitable, 41% win rate too low"

### My Hypothesis
"[Specific hypothesis with reasoning]"
- Example: "Change chainer_mode from LONG_ONLY to BOTH to capture short signals"
- Example: "Increase price_eps to -5 to allow near-equal price lows"

### Proposed Change
- **File**: `src/trader/strategy/[strategy].py`
- **Parameter**: [param_name]
- **Before**: [old_value]
- **After**: [new_value]
- **Reasoning**: [brief explanation]

### Questions for Your Review
1. Do you agree this is the main problem?
2. Is my hypothesis reasonable for your domain knowledge?
3. Should I implement this change, or do you suggest an alternative?

---
**Your Options:**
- ✅ "Proceed" (implement the change)
- 🔄 "Alternative: [your suggestion]" (I'll implement your change instead)
- ❌ "Skip this problem" (I'll focus on next priority)
- 🛑 "Stop optimization" (end the session)
```

**User responds with approval or alternative**. Based on response:
- If approved → implement change and go to Step 6 (rerun)
- If alternative → implement user's suggestion instead
- If skip → identify next priority problem and present new report
- If stop → end optimization

---

**FOR AUTO MODE:** Skip Step 8 review, implement automatically and continue.

### Step 9: Check Stop Conditions
STOP if ANY of these are true:
- **Target reached**: Sharpe > 1.0 AND Profit Factor > 1.5 AND MaxDD < 20% AND Trades ≥ 10
- **Stalled**: 5 consecutive rejected iterations
- **Max iterations**: [specified count] iterations completed

If not stopped → go to Step 2 for next iteration.

## Anti-Overfitting Validation (Every 5 Iterations)

After every 5th ACCEPTED change:

```bash
bash scripts/backtest_cli.sh scripts/backtest_val.json
```

Read the validation JSON report. Check:
- `val_sharpe ≥ train_sharpe × 0.7` → PASS, continue
- `val_sharpe < train_sharpe × 0.7` → FAIL, STOP optimization

If FAIL: Report overfitting risk. Suggest rolling back to last validation-passing version.

## Token Efficiency Rules

- ONLY read JSON report files from `reports/` (< 5KB each)
- NEVER read log files, CSV data, or raw K-line data
- Each iteration should read: 1 JSON report + relevant code section only
- Target: < 5000 tokens per iteration

## Reporting

After stopping, output a summary:

```
## Optimization Summary
- Strategy: [name]
- Iterations: [N] (accepted: [A], rejected: [R])
- Baseline: Sharpe=[X], PF=[Y], Trades=[Z]
- Final: Sharpe=[X], PF=[Y], Trades=[Z]
- Changes made: [list of accepted changes]
- Failed hypotheses: [list of rejected hypotheses]
- Validation: [PASS/FAIL/NOT_RUN]
```
