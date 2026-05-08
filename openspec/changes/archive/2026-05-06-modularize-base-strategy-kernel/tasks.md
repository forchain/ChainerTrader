## 1. Regression Guardrails

- [x] 1.1 Add structural tests that detect strategy-specific identifiers or report strings in `BaseStrategy`
- [x] 1.2 Add structural tests that detect direct protective stop/take-profit placement helpers in `BaseStrategy`
- [x] 1.3 Add parity tests covering existing BaseStrategy entry confirmation, exit confirmation, stop-loss, take-profit, breakeven, and short-mode behavior before extraction
- [x] 1.4 Add MACD triple divergence report regression tests proving exit classification is preserved without BaseStrategy-specific fallback logic

## 2. Domain and Lifecycle Extraction

- [x] 2.1 Move trade status, trade context, signal snapshot, and trade registry types into lifecycle/domain modules
- [x] 2.2 Add compatibility aliases or wrappers for existing `BaseStrategy.TradeStatus`, `BaseStrategy.TradeContext`, and `BaseStrategy.SignalSnapshot` references
- [x] 2.3 Implement lifecycle transitions for pending entry, opening, active, pending exit, closing, closed, and cancelled states in `TradeLifecycleEngine`
- [x] 2.4 Update `BaseStrategy.enter_trade`, `BaseStrategy.exit_trade`, `_process_trade_engine`, and `notify_order` to delegate lifecycle decisions to the lifecycle module
- [x] 2.5 Add lifecycle module tests independent of Backtrader strategy inheritance

## 3. Signal Router Extraction

- [x] 3.1 Implement a reusable `SignalRouter` for `LONG_ONLY`, `SHORT_ONLY`, and `BOTH` mode decisions
- [x] 3.2 Route signal snapshots through `SignalRouter` and return framework actions/lifecycle event payloads
- [x] 3.3 Update `BaseStrategy._process_signals()` to consume router output instead of embedding mode-specific branches
- [x] 3.4 Add router tests for blocked, entry-created, entry-cancelled, exit-requested, and active-trade cases without Backtrader
- [x] 3.5 Verify existing signal lifecycle hook tests still pass through the delegated router path

## 4. Risk Engine and Backtrader Adapter Extraction

- [x] 4.1 Move initial stop-loss and take-profit computation into `RiskEngine`
- [x] 4.2 Move breakeven ladder computation and replacement decisions into `RiskEngine`
- [x] 4.3 Implement a Backtrader strategy execution adapter that owns concrete `buy`, `sell`, `cancel`, stop, limit, and OCO-compatible calls
- [x] 4.4 Route risk outputs through normalized risk/protection intents before Backtrader adapter placement
- [x] 4.5 Remove direct protective order placement and cancellation helpers from `BaseStrategy`
- [x] 4.6 Add risk engine and Backtrader adapter unit tests for long and short stop-loss, take-profit, OCO-style cancellation, and breakeven replacement

## 5. Strategy Metadata Cleanup

- [x] 5.1 Remove MACD-specific fallback checks and hard-coded report labels from `BaseStrategy`
- [x] 5.2 Ensure MACD triple divergence passes explicit exit metadata for strategy-stop classifications
- [x] 5.3 Add or update report adapter behavior if legacy report rows need classification outside the base framework class
- [x] 5.4 Add tests proving private exit metadata survives lifecycle finalization and notification/report consumption

## 6. Integration and Compatibility

- [x] 6.1 Keep existing strategy subclass public APIs compatible: signal getters, context getters, lifecycle hooks, `enter_trade`, and `exit_trade`
- [x] 6.2 Update execution gateway parity tests so Backtrader and paper flows both consume the extracted kernel boundaries
- [x] 6.3 Update docs if user-facing architecture or operation guidance changes; otherwise record why README is not needed
- [x] 6.4 Run `openspec validate modularize-base-strategy-kernel --strict`
- [x] 6.5 Run targeted regression tests for BaseStrategy, MACD triple divergence execution/reporting, execution gateway contracts, and live auto execution safety
- [x] 6.6 Run formatting/lint checks for touched modules

### Verification Notes

- 2026-05-06: `openspec validate modularize-base-strategy-kernel --strict` passed.
- 2026-05-06: `uv run ruff check src/trader/strategy/base_strategy.py src/trader/strategy/lifecycle.py src/trader/strategy/risk.py src/trader/strategy/backtrader_adapter.py src/trader/strategy/signal_router.py tests/test_base_strategy_kernel_extraction.py` passed.
- 2026-05-06: `uv run pytest tests/test_base_strategy_kernel_extraction.py tests/test_base_strategy_signal_routing.py tests/test_entry_exit_ma_cross.py tests/test_chainer_stop_order.py tests/test_macd_triple_divergence_execution.py tests/test_strategy_execution_kernel.py tests/test_execution_gateway_contract.py tests/test_execution_gateway_rollout_safety.py tests/test_live_auto_execution.py` passed with 55 passed and 1 skipped.
- Residual risk: the skipped small-live smoke remains credential-gated and was not executed locally.
