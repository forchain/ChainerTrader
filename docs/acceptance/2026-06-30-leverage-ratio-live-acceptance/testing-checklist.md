# Testing Checklist: Live Leverage Ratio Verification

## Skill Binding Metadata
- skill_id: blackbox-acceptance-orchestrator
- workflow_id: 2026-06-30-leverage-ratio-live-acceptance
- skill_run_root: docs/acceptance/2026-06-30-leverage-ratio-live-acceptance/
- source_contract: docs/acceptance/2026-06-30-leverage-ratio-live-acceptance/acceptance-contract.md

## Rules
- Black-box only: use runtime logs, task-visible outputs, API/UI surfaces, Binance web history, and DB records only if they are already part of the operator workflow.
- Do not inspect source code or test internals as acceptance evidence.
- Every pass/fail item must record exact env values, task mode, timestamp, and external identifiers.
- Status values: `pending`, `in_progress`, `passed`, `failed`, `blocked`, `reopened`, `skipped_force_majeure`.

| ID | Linked Gate | Purpose | Setup | Black-Box Steps | Expected Observable Result | Evidence To Capture | Failure Handling | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TEST-LR-001 | AC-LR-001 | Confirm the live run actually uses `TRADER_LEVERAGE_RATIO=1.0` | export live credentials, `TRADER_DB`, `TRADER_LEVERAGE_RATIO=1.0` | verify env parsing plus live submission context before order routing | runtime accepts `TRADER_LEVERAGE_RATIO=1.0` and uses it in the live submission environment | env snapshot, config test output, live task / router command, timestamp | blocked if runtime context incomplete | passed |
| TEST-LR-002 | AC-LR-002 | Prove cross-margin long keeps the configured order notional | `BOTH`, `small_live_auto`, `TRADER_LEVERAGE_RATIO=1.0`, requested notional well within available quote capital | submit a direct live cross-margin long route and inspect the returned order immediately | `requested_notional == effective_notional`; Binance order response shows the same quantity/notional | live router outcome, order id, requested/effective notional, open-order scan | actionable cleanup if blocked by stale orders; hard_fail if long order is reduced despite being within the limit | passed |
| TEST-LR-003 | AC-LR-003 | Prove cross-margin short keeps the configured order notional when within the limit | `SHORT_ONLY`, `small_live_auto`, `TRADER_LEVERAGE_RATIO=1.0`, requested notional within available quote capital | submit a direct live cross-margin short route and inspect the returned order immediately | `requested_notional == effective_notional`; Binance order response shows the same quantity/notional | live router outcome, order id, requested/effective notional, open-order scan | actionable cleanup if blocked by stale orders; hard_fail if short order is reduced despite being within the limit | passed |
| TEST-LR-004 | AC-LR-004 | Prove cross-margin short is capped at 1:1 when request exceeds owned capital | `SHORT_ONLY`, `small_live_auto`, `TRADER_LEVERAGE_RATIO=1.0`, task requested notional intentionally above available quote capital but still small | submit a direct live cross-margin short route with a request above the cap | `requested_notional > effective_notional`; Binance order response reflects the capped quantity/notional | live router outcome, order id, requested/effective notional, open-order scan | actionable cleanup if blocked by stale orders; hard_fail if effective notional still exceeds cap | passed |
| TEST-LR-005 | AC-LR-005 | Prove leverage ratio is a cap, not a sizing multiplier | keep same small task cap, raise `TRADER_LEVERAGE_RATIO` above `1.0`, ensure account capital is sufficient | rerun the capped short route with a higher leverage ratio but the same task cap | live outcome still respects `live_trade_max_notional` as the task cap and does not auto-enlarge because the ratio increased | live router outcome, order id, env snapshot with raised ratio | hard_fail if order grows beyond task cap solely because ratio increased | passed |
| TEST-LR-006 | AC-LR-006 | Ensure operator can independently verify acceptance | all previous tests finished | reconcile report against Binance Web and task-visible evidence | operator can follow exact page/filter/time-window and confirm each claimed order | completed execution report, open-order scan | reopened if evidence cannot be followed by operator | passed |

## Recommended Test Inputs
- Symbol: `BTC-USDT`
- Execution mode: `small_live_auto`
- Live data mode: existing realtime live path
- Suggested task variants:
  - cross-margin long: `strategy_params.chainer_mode=BOTH`
  - cross-margin short: `strategy_params.chainer_mode=SHORT_ONLY`
- Suggested smoke strategy: `smoke_test` only as a signal carrier; the verified acceptance path used direct live router submissions, so candle-close timing was not part of the proof
- Harness note: realtime warmup was the wrong execution shape for this acceptance. The live router path proved the order amount immediately, which is the actual requirement.

## Run Matrix
| Run ID | Objective | Key Env | Task Expectations | Notes |
| --- | --- | --- | --- | --- |
| RUN-LR-MARGIN-LONG-1 | long within limit | `TRADER_LEVERAGE_RATIO=1.0` | `BOTH`, requested amount within owned quote capital | proved cross-margin long preserves requested notional |
| RUN-LR-MARGIN-SHORT-1 | short within limit | `TRADER_LEVERAGE_RATIO=1.0` | `SHORT_ONLY`, requested amount within owned quote capital | proved cross-margin short preserves requested notional |
| RUN-LR-MARGIN-SHORT-2 | capped short | `TRADER_LEVERAGE_RATIO=1.0` | `SHORT_ONLY`, requested amount intentionally above owned quote capital | proved 1:1 cap enforcement |
| RUN-LR-MARGIN-SHORT-3 | independence | `TRADER_LEVERAGE_RATIO=2.0` or higher | `SHORT_ONLY`, same `live_trade_max_notional` as prior small-live cap | proved no auto-enlargement |

## Manual Verification Paths
- Binance Cross Margin Order History:
  - filter symbol `BTCUSDT`
  - confirm long or short entry order IDs and quantities
- Binance Trade History / Fee History:
  - match fills and fees for each accepted order
- Chainer runtime evidence:
  - `[auto_execution]` log lines
  - execution outcome payload containing `requested_notional` and `effective_notional`

## Success Tolerance
- Quantity/notional may differ slightly from the task request because of exchange precision and fill rounding.
- For pass/fail, compare against `effective_notional`, not against an idealized exact decimal.
- Small fee/slippage effects are acceptable; overshooting the configured cap is not.
- Current preflight note: cross-margin is the accepted account surface for both long and short validation in this workflow.
