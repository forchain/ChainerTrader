# Acceptance Contract: Production Open-Loop Fast-Signal Verification

## Goal
- User-visible outcome: verify true production end-to-end closure from `server start -> strategy emits signal -> exchange receives real order`.
- This run is production-mode validation, not only smoke harness validation.
- Orders do not need to be filled; exchange-visible submitted/open/canceled records are acceptable if traceable.

## Scope
- In scope:
  - dedicated fast-signal strategy/task (must not use `realtime_macd_triple_divergence_top10_production.json`)
  - production runtime startup via `python -m trader --tasks ...`
  - real Binance API order operations via `small_live_auto`
  - coverage: long+short, spot+cross-margin, stop-loss/take-profit, cancel order
  - strict operation logging: success includes order IDs; failure surfaces explicit errors (no silent pass)
  - routing rule: for mixed tasks in one runtime, API path selection must follow each task's Chain Trader mode / execution mode (not one global base path)
- Out of scope:
  - profitability, long-duration strategy behavior, multi-symbol portfolio behavior

## Fast-Signal Strategy Logic
- Strategy: `smoke_test` (dedicated test strategy)
- Why it triggers quickly after startup:
  - it emits deterministic operations by bar count (`len(self)`), not by rare market pattern.
  - in 1m realtime stream, once bars advance, operations are emitted on fixed early bars:
    - bar 5: LONG entry
    - bar 10: SELL exit
    - bar 15: SHORT entry
    - bar 20: CLOSE short
- Why this is suitable for production closure validation:
  - predictable signal schedule
  - includes both long and short paths
  - attaches stop-loss/take-profit on entry signals to exercise protection order path

## Roles
- User: approves docs, validates Binance Web evidence.
- Project Manager: document/update criteria and coordinate execution.
- Development Agent: only if implementation gaps block acceptance.
- Testing Agent: black-box verification using command output, artifacts, Binance Web path.

## Resources And Preconditions
- Required env from `.env`:
  - `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `TRADER_DB`
- Execution mode:
  - `live_execution_mode=small_live_auto`
  - `live_data_mode=realtime`
- Exchange credentials source:
  - runtime must use `BINANCE_API_KEY/BINANCE_API_SECRET` for live exchange auth.
  - if `TRADER_EXCHANGE` conflicts, this run overrides it with runtime value derived from `BINANCE_*`.
- Safety:
  - keep `live_trade_max_notional` small (`~11 USDT`)
  - one-symbol task only (`BTC-USDT`) for controllability

## Acceptance Gates
| ID | Capability | Required Evidence | Status |
| --- | --- | --- | --- |
| AC-PROD-001 | Dedicated fast-signal production task is used (not top10 production task) | task file path, strategy name, interval, mode fields | passed |
| AC-PROD-002 | Production runtime starts and reaches realtime loop | startup log + realtime subscription/warmup logs | passed |
| AC-PROD-003 | Strategy emits signal quickly after startup | timestamped signal logs with op types and task id | passed |
| AC-PROD-004 | Spot long path submits real order | order submission log with order_id + Binance-visible order | passed |
| AC-PROD-005 | Cross-margin short path submits real order | order submission log with order_id + Binance-visible order | passed |
| AC-PROD-006 | Stop-loss/take-profit protection orders are submitted | protection order IDs and/or verifiable fallback evidence | passed |
| AC-PROD-007 | Cancel order operation works and is verifiable | cancel request result includes order ID and final canceled/absent evidence | passed |
| AC-PROD-008 | No silent exchange-operation failure | failed operations must emit explicit error logs; no swallowed failures | passed |
| AC-PROD-009 | Multi-task mode-aware API routing | in one runtime with mixed task modes, each task uses matching Spot/Margin API path by task mode/operation; no cross-task contamination | passed |

## New Routing Requirement (User Update)
- Problem: previous runs relied on global exchange/base-path assumptions from smoke-style setup, not true production mixed-task behavior.
- Required production behavior:
  - API path must be chosen per task (and per operation semantics when needed), using Chain Trader mode / execution settings.
  - Example: one task in spot path and another in margin path must both work in the same process without forcing a single global margin-only route.
  - This is a product requirement, not only a test-script workaround.

## Failure Classification
- actionable: API-recoverable (e.g., stale blocking orders) -> auto-remediate once, retry once, record evidence.
- force_majeure: unrecoverable in-run (permission/outage/account restriction) -> mark skipped_force_majeure and continue independent checks.
- hard_fail: required capability absent, silent failures, or unverifiable evidence.

## Review
- Production execution completed with evidence captured in `execution-report.md`.
