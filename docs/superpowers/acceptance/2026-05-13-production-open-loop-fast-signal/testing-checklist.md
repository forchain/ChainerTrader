# Testing Checklist: Production Open-Loop Fast-Signal Verification

## Rules
- Black-box only: use command output, generated artifacts, Binance Web checks.
- Do not claim pass without timestamp + order identifier evidence.
- Status values: `pending`, `in_progress`, `passed`, `failed`, `blocked`, `reopened`, `skipped_force_majeure`.

## Test Cases
| ID | Gate | Purpose | Steps | Expected Result | Evidence | Failure Handling | Status |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TEST-PROD-001 | AC-PROD-001 | Ensure dedicated fast-signal task is used | Use dedicated task file only; assert task config excludes `realtime_macd_triple_divergence_top10_production.json` | Runtime command points to dedicated task file | task path + config snapshot | Wrong task path -> hard_fail stop | passed |
| TEST-PROD-002 | AC-PROD-002 | Ensure production runtime reaches live loop | Start `python -m trader --tasks <dedicated-task>` | Warmup/realtime loop logs appear | startup/realtime log lines + timestamps | Startup error -> failed | passed |
| TEST-PROD-003 | AC-PROD-003 | Ensure fast signal appears quickly | Observe signal logs/events after startup | LONG/SELL/SHORT/CLOSE signals appear by early bar windows | signal timestamp, op type, task id, bar phase | no signal in timeout -> failed | passed |
| TEST-PROD-004 | AC-PROD-004 | Verify spot long real submission | Observe auto_execution submit logs during long flow | submit success with `order_id` and spot scope | order_id, symbol, side/type, timestamp | missing order_id/silent failure -> hard_fail | passed |
| TEST-PROD-005 | AC-PROD-005 | Verify cross-margin short real submission | Observe auto_execution submit logs during short flow | submit success with `order_id` and margin scope | order_id, symbol, side/type, timestamp | actionable blocker -> remediate once + retry | passed |
| TEST-PROD-006 | AC-PROD-006 | Verify stop-loss/take-profit submission | Inspect protection logs/events after entry | protection IDs emitted or verifiable fallback evidence | protection order IDs, type, timestamp | missing protection evidence -> failed | passed |
| TEST-PROD-007 | AC-PROD-007 | Verify cancel operation | Run approved cancel/cleanup path for generated open/protection orders | canceled/absent evidence for target order IDs | before/after IDs, cancel result per ID | cannot cancel -> actionable/hard_fail by reason | passed |
| TEST-PROD-008 | AC-PROD-008 | Verify no silent failure | Inspect all exchange operation paths in run logs | every failure has explicit error output; no silent continue | failed log payloads with reason/code | silent failure -> hard_fail | passed |
| TEST-PROD-009 | AC-PROD-004~007 | Human verify Binance Web records | Check Binance Web by time window + symbol + order IDs | Web records match report evidence | manual verification checklist rows | mismatch -> reopened | pending |
| TEST-PROD-010 | AC-PROD-009 | Verify task-level mode-aware API routing in one runtime | Run mixed-task config: at least one spot-oriented task and one margin-oriented task in same process; observe each task's execution outcomes | spot task uses spot-compatible path; margin task uses margin-compatible path; no global forced path warning blocks either task | per-task task_id/mode/op_type/submitted-or-failed evidence + path-related logs | if either task is forced into wrong path due to global config, mark failed and open development demand | passed |

## Execution Constraints
- Must use dedicated fast-signal task.
- Must use production key path from `BINANCE_API_KEY/BINANCE_API_SECRET`.
- Must keep small notional.
- If actionable blockers occur, remediate once then retry once.
- Mixed-task routing checks must run in one process to prove no cross-task contamination.
