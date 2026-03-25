---
name: strategy-optimize
description: Iteratively optimize a trading strategy by analyzing JSON backtest reports, identifying problems, making targeted code changes, and comparing metrics. Uses One Change Rule and anti-overfitting validation.
---

# Strategy Optimization Workflow

You are optimizing a ChainerTrader strategy. Follow this workflow exactly.

## Pre-flight Checklist

Before starting, verify ALL of these:

1. **JSON report system works**: Run `bash scripts/backtest_cli.sh scripts/backtest_train.json` and confirm a JSON file appears in `reports/`
2. **Baseline exists**: Read `scripts/baseline.json` to get baseline metrics
3. **Train/Val configs exist**: Confirm `scripts/backtest_train.json` and `scripts/backtest_val.json` exist

If any check fails → STOP and fix the infrastructure first.

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

### Step 8: Check Stop Conditions
STOP if ANY of these are true:
- **Target reached**: Sharpe > 1.0 AND Profit Factor > 1.5 AND MaxDD < 20% AND Trades ≥ 10
- **Stalled**: 5 consecutive rejected iterations
- **Max iterations**: 20 iterations completed

If not stopped → go to Step 2.

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
