## 1. Remove Paper Auto From Realtime Mode Contracts

- [x] 1.1 Update live execution mode normalization and gateway resolution so `paper_auto` is rejected as unsupported.
- [x] 1.2 Remove or migrate task configs and examples that use `live_execution_mode=paper_auto`.
- [x] 1.3 Replace dashboard and monitor wording that reports paper execution outcomes with manual/backtrader/live execution outcome language.
- [x] 1.4 Remove or rewrite tests that assert `paper_auto` local cash, local position, or paper execution dashboard behavior.

## 2. Add Semantic Order Selection

- [x] 2.1 Add a tested order semantic selector that maps ordinary entry/close to market order intents and maps required stop/take-profit behavior to protection intents.
- [x] 2.2 Add validation that ordinary orders are not used as automatic live substitutes for Chainer framework stop-loss semantics.
- [x] 2.3 Add validation for protection quantity, side, stop price, take-profit price, and side-specific price relationships before gateway submission.
- [x] 2.4 Add tests covering market entry, market close, stop-only, take-profit-only, stop plus take-profit, and breakeven replacement selection.

## 3. Strengthen Backtrader Protection Semantics

- [x] 3.1 Update the Backtrader execution path to use broker-native stop, limit, OCO, or bracket semantics where required by the protection intent.
- [x] 3.2 Preserve order role metadata for entry, ordinary close, stop exit, take-profit exit, and protection replacement events.
- [x] 3.3 Add Backtrader tests for Chainer framework stop-loss, take-profit, OCO-style mutual cancellation, and breakeven stop replacement.
- [x] 3.4 Document or test the OHLC data granularity limitation so backtest results are not described as tick-accurate when tick data is unavailable.

## 4. Route Live Automation Through Execution Gateway

- [x] 4.1 Replace legacy direct live order submission with `ExecutionGateway` order and protection intents for `auto_trade`.
- [x] 4.2 Keep small-live notional caps and account prerequisite checks before live gateway submission.
- [x] 4.3 Persist entry, close, protection, replacement, cancellation, and failure state through the execution state store.
- [x] 4.4 Emit dashboard-visible events for protection armed, rejected, missing, failed, replaced, and canceled states.

## 5. Implement Binance Native Protection Correctly

- [x] 5.1 Audit Binance spot and margin SDK calls for market, stop-loss, take-profit, OCO, cancel, and cancel-replace parameters.
- [x] 5.2 Fix protection side mapping so long protection closes with sell-side orders and short protection closes with buy-side orders.
- [x] 5.3 Verify native protection order identifiers before emitting `protection_armed`.
- [x] 5.4 Add fail-safe behavior for filled entries whose required live protection cannot be placed or verified.
- [x] 5.5 Add mocked gateway tests for supported, unsupported, rejected, unverified, and replacement protection cases.

## 6. Documentation And Verification

- [x] 6.1 Update README or user-facing docs if live execution mode configuration or operating guidance changes.
- [x] 6.2 Update OpenSpec-facing docs or specs affected by removing `paper_auto`.
- [x] 6.3 Run focused automated tests for execution gateway contracts, live auto order safety, Backtrader protection behavior, and manual notification no-order behavior.
- [x] 6.4 Run `openspec validate simplify-execution-modes-native-protection --strict` and resolve any spec validation issues.

## 7. Review Follow-up Hardening

- [x] 7.1 Remove the remaining local `PaperExecutionGateway` implementation and paper gateway tests/imports.
- [x] 7.2 Use native stop-market/take-profit-market semantics for single-leg Binance protection where supported, instead of stop-limit substitutes.
- [x] 7.3 Route Binance margin single-leg stop, take-profit, and replacement protection through margin APIs.
- [x] 7.4 Fix live short risk-update replacement to use short exposure and buy-side protection semantics.
- [x] 7.5 Add explicit fail-safe behavior when entry succeeds but required protection cannot be armed or verified.
- [x] 7.6 Re-run focused tests and OpenSpec strict validation after review hardening.
