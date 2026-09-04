## 1. Configuration And Mode Routing

- [x] 1.1 Extend task config parsing and serialization for `paper_auto`, `small_live_auto`, `full_live_auto`, `live_trade_max_notional`, and `live_short_execution`.
- [x] 1.2 Add normalization helpers for staged live execution mode and short execution mode, preserving `manual_notify` and default safe behavior.
- [x] 1.3 Add validation errors for unsupported execution modes and invalid small-live notional caps.
- [x] 1.4 Update live task examples under `configs/tasks/live/` for `paper_auto` and capped `small_live_auto`.

## 2. Execution Outcome Model

- [x] 2.1 Define a structured automatic execution outcome model with task id, mode, market, operation identity, side/type, price, requested/effective sizing, status, and reason fields.
- [x] 2.2 Add deterministic operation identity generation using signal event id when present and side/time/price fallback otherwise.
- [x] 2.3 Add persistence or task-state attachment for automatic execution outcomes so dashboard snapshots can show routed, skipped, failed, and simulated operations.
- [x] 2.4 Add tests for outcome serialization and operation identity stability.

## 3. Live Execution Router

- [x] 3.1 Implement a framework-owned live execution router that receives realtime strategy operations and dispatches by execution mode.
- [x] 3.2 Keep `manual_notify` routed to existing manual notification behavior and prove it does not simulate or place orders.
- [x] 3.3 Integrate the router into realtime live operation handling without moving order logic into strategy classes.
- [x] 3.4 Ensure duplicate operations are skipped before paper simulation or real exchange placement.

## 4. Paper Auto Execution

- [x] 4.1 Implement `paper_auto` state initialization from configured `free` cash and `manual_start_position`.
- [x] 4.2 Implement simulated long entry and exit accounting.
- [x] 4.3 Implement simulated short entry and close accounting without requiring margin or futures configuration.
- [x] 4.4 Emit paper execution outcomes and dashboard-visible paper execution data.
- [x] 4.5 Add tests proving `paper_auto` supports long and short simulation without calling exchange order APIs or exchange balance APIs.

## 5. Real Long Order Execution

- [x] 5.1 Implement real-order sizing for `small_live_auto` using `live_trade_max_notional` as a hard per-order cap.
- [x] 5.2 Implement real-order sizing for `full_live_auto` using configured full sizing while preserving validation gates.
- [x] 5.3 Validate operation price, calculated quantity, effective notional, and exchange constraints before order placement.
- [x] 5.4 Validate account-side prerequisites for long entries and exits, including quote balance and known position/base balance.
- [x] 5.5 Emit submitted, skipped, and failed execution outcomes for real long-side orders.
- [x] 5.6 Add tests proving small-live orders are capped, invalid orders are skipped, insufficient balances are skipped, and full-live sizing is not capped by small-live settings.

## 6. Cross Margin Short Execution

- [x] 6.1 Add explicit `live_short_execution = "margin_cross"` gating for real `SHORT` and short-side `CLOSE` operations.
- [x] 6.2 Ensure real `SHORT` operations are never silently routed through spot `SELL`.
- [x] 6.3 Add Binance cross-margin readiness checks before short order placement.
- [x] 6.4 Route cross-margin short entries through the Binance margin adapter only after staged sizing and safety validation.
- [x] 6.5 Route short closes through the margin adapter only when known short exposure or sufficient account information is available.
- [x] 6.6 Add tests proving disabled short execution skips orders, enabled cross-margin short uses the margin path, spot short is rejected, and unknown short exposure prevents close placement.

## 7. Monitoring And Notifications

- [x] 7.1 Publish automatic execution outcomes to live monitor consumers and initial snapshots.
- [x] 7.2 Update dashboard event builders or monitor serialization so operators can distinguish manual recommendations, paper executions, real submitted orders, skipped orders, and failed orders.
- [x] 7.3 Update notification behavior if needed so real-order and paper-order outcomes are not mislabeled as manual recommendations.
- [x] 7.4 Add tests for monitor snapshot and realtime event contracts for paper, skipped, failed, and submitted execution outcomes.

## 8. Documentation And Verification

- [x] 8.1 Update README live trading documentation for staged execution modes, small-live notional caps, and cross-margin short opt-in.
- [x] 8.2 Run targeted unit tests for task config, execution routing, paper simulation, real order safety, cross-margin gating, and monitor contracts.
- [x] 8.3 Run existing manual live notification and realtime live runtime regression tests.
- [x] 8.4 Run OpenSpec validation for `staged-realtime-auto-trading`.
- [x] 8.5 Document any external smoke-test prerequisites for real exchange order validation, including credentials, margin account readiness, and explicit operator opt-in.
