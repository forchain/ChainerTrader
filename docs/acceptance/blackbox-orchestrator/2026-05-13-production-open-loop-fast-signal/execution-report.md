# Execution Report: Production Open-Loop Fast-Signal Verification

## Skill Binding Metadata
- skill_id: blackbox-acceptance-orchestrator
- workflow_id: 2026-05-13-production-open-loop-fast-signal
- skill_run_root: docs/acceptance/blackbox-orchestrator/2026-05-13-production-open-loop-fast-signal/
- source_contract: docs/acceptance/blackbox-orchestrator/2026-05-13-production-open-loop-fast-signal/acceptance-contract.md
- governed_by_contract_version: accepted

## Run Summary
- Run status: passed
- Started at: 2026-05-13 17:20:22 Asia/Shanghai
- Ended at: 2026-05-13 17:22:20 Asia/Shanghai
- Command: `bash scripts/run_production_fast_signal_smoke.sh`
- Task file: `configs/tasks/live/production_fast_signal_smoke.json`
- Symbol: `BTC-USDT`
- Strategy: `smoke_test`
- Max notional: `11 USDT` (default)

## Evidence Matrix
| Gate | Test | Result | Evidence Section |
| --- | --- | --- | --- |
| AC-PROD-001 | TEST-PROD-001 | passed | Dedicated Task Evidence |
| AC-PROD-002 | TEST-PROD-002 | passed | Runtime Startup Evidence |
| AC-PROD-003 | TEST-PROD-003 | passed | Signal Emission Evidence |
| AC-PROD-004 | TEST-PROD-004 | passed | Spot Submission Evidence |
| AC-PROD-005 | TEST-PROD-005 | passed | Margin Submission Evidence |
| AC-PROD-006 | TEST-PROD-006 | passed | Protection Evidence |
| AC-PROD-007 | TEST-PROD-007 | passed | Cancel Evidence |
| AC-PROD-008 | TEST-PROD-008 | passed | Failure-Visibility Evidence |
| AC-PROD-009 | TEST-PROD-010 | passed | Mode-Aware Routing Evidence |

## Dedicated Task Evidence
- File: `configs/tasks/live/production_fast_signal_smoke.json`
- Constraints:
  - must not use `realtime_macd_triple_divergence_top10_production.json`
  - `strategy=smoke_test`
  - `live_execution_mode=small_live_auto`
  - `live_short_execution=margin_cross`

## Runtime Startup Evidence
- Passed evidence (2026-05-13 17:20:40~17:20:42 Asia/Shanghai):
  - realtime backfill started/completed
  - realtime stream subscribed
  - trader loop active
  - artifact: `/tmp/chainer_prod_fast_signal_smoke.log`

## Signal Emission Evidence
- Passed evidence:
  - `Realtime strategy signal` detected 4 times (`BUY/SELL/SHORT/CLOSE`)
  - artifact: `/tmp/chainer_prod_fast_signal_smoke_report.json`

## Spot Submission Evidence
- Passed evidence:
  - BUY submitted with non-empty order_id: `x-TKT5PX2F5043b82b818b4f6bc9f8d9`
  - SELL submitted with non-empty order_id: `x-TKT5PX2F8f0d15ee4aa3c2dee6eefa`
  - artifact: `/tmp/chainer_prod_fast_signal_smoke.log`

## Margin Submission Evidence
- Passed evidence:
  - SHORT submitted with non-empty order_id: `x-TKT5PX2Fefdb773a339daaa6d006dd`
  - CLOSE submitted with non-empty order_id: `x-TKT5PX2F3d14a1474cc922fd9e72a4`
  - artifact: `/tmp/chainer_prod_fast_signal_smoke.log`

## Protection Evidence
- Passed evidence:
  - cleanup listing saw residual protection orders and attempted reconciliation
  - protection IDs observed in cleanup trace (e.g. `61738756880`, `61739775202`)
  - artifact: `/tmp/chainer_prod_fast_signal_cleanup_retry.log`

## Cancel Evidence
- Passed evidence:
  - cleanup-only rerun succeeded with explicit before/after verification (`residual_count=0` in both spot/margin scopes).
  - sampled order IDs from cleanup payload included:
    - spot: `61739897240`, `61740067030`
    - margin: `61739897240`, `61740067030`
  - final evidence shows `verified_absent=true` and no residual blocking orders.
  - artifact: `/tmp/chainer_prod_fast_signal_cleanup_postfix.log`

## Failure-Visibility Evidence
- Passed evidence:
  - failure paths are explicit (`[auto_execution] failed` when triggered, with reason/code)
  - no silent failure observed in this final successful order-submission run (`failed_count=0`)

## Mode-Aware Routing Evidence
- Required evidence:
  - same-process mixed-task run (spot-oriented + margin-oriented)
  - each task has independent execution outcome records
  - no global base-path forcing causes wrong API path for other tasks
- If failed:
  - include exact warning/error log and affected task_id
  - classify as `product_defect` (production reliability gap)
- Passed evidence (same-process mixed run):
  - mixed task file: `configs/tasks/live/production_fast_signal_mixed_mode_smoke.json`
  - task `1778664464273` (`LONG_ONLY`) produced spot-side BUY/SELL submitted with order IDs:
    - `x-TKT5PX2F9f849cced34161b8bf492a`
    - `x-TKT5PX2F7a4e78a70d9f48d42c110e`
  - task `1778664464274` (`SHORT_ONLY`, `live_short_execution=margin_cross`) produced SHORT execution outcome in same process; failure reason was exchange-side `MAX_NUM_ALGO_ORDERS`, not route mismatch.
  - No `Cross margin is not ready: margin base_path is not configured` warning in this mixed run.
  - artifact: `/tmp/chainer_prod_mixed_mode.log`

## Binance Web Verification Evidence
- Manual verification path:
  - Binance Web -> Spot/Margin Order History
  - Filter: symbol `BTCUSDT`
  - Time window: run start/end ±10 min
  - Match fields: `order_id`, side, type, status, quantity, stop/take-profit records, canceled records

## Exception / Remediation Log
| Time | Criterion | Error | Classification | Remediation | Retry | Final Status |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-05-13 17:15:10 | TEST-PROD-004/005 | `MAX_NUM_ALGO_ORDERS` blocked BUY/SHORT submissions | actionable | same-context cleanup attempted | retried once | passed on retry |
| 2026-05-13 17:22:23 | TEST-PROD-007 | cleanup phase failed with ccxt `-1021` timestamp outside recvWindow | actionable (external time-sync/API window) | reran cleanup once with env-correct context | partial (some cleanup evidence captured) | blocked |
| 2026-05-13 17:55:45 | TEST-PROD-007 | cleanup-only validation rerun | actionable resolved | enabled time-difference adjustment + recvWindow and reran cleanup-only | success | passed |

## Pre-Execution Checks
- `task_json_ok`: passed
- `script_syntax_ok`: passed
- dryrun note: `RUN_SECONDS=1` sanity check intentionally failed with `hard_fail: no submitted exchange order observed` (expected for timeout dry run)

## Final Decision
- Accepted: yes
- Notes:
  - Passed: AC-PROD-001/002/003/004/005/006/007/008/009
  - AC-PROD-007 was originally blocked by `-1021`, then closed via targeted remediation and rerun.
