## Why

The current realtime execution design includes a local `paper_auto` exchange path even though Backtrader already provides the project backtest/test execution engine. Keeping both a paper exchange and Backtrader increases complexity while still failing to provide true exchange semantics for protection behavior such as Chainer framework stop-loss, take-profit, and breakeven replacement.

This change simplifies the execution model around a semantic rule: use the simplest real order behavior that satisfies the strategy requirement, but do not replace required stop-loss or take-profit semantics with ordinary orders when ordinary orders cannot provide the same behavior.

## What Changes

- **BREAKING**: Remove `paper_auto` as a supported realtime automatic execution mode and stop treating the local paper gateway as a required execution target.
- Keep `manual_notify` as the no-order safety baseline for recommendations and local notification workflows.
- Keep Backtrader as the test/backtest execution engine and require it to support the Chainer framework's portable order semantics.
- Route live automatic execution through the unified execution gateway instead of the legacy operation-only `AutoExecutionRouter` path.
- Define order selection by semantic need:
  - Market entry and market close use ordinary market orders when no protective condition is required.
  - Simple take-profit may use the simplest exchange-native order type that satisfies the configured take-profit semantics.
  - Chainer framework stop-loss, stop replacement, and stop/take-profit mutual cancellation require exchange-native protection semantics when running live.
  - Client-side monitoring or closed-candle ordinary-order exits may be used only when the configured strategy semantics explicitly permit local/manual behavior, not as an automatic live replacement for stop-loss.
- Require live protection placement, verification, persistence, and recovery before an automatically opened live position is considered protected.
- Replace paper-specific dashboard/outcome language with mode-neutral execution outcomes for manual, Backtrader, and real live paths.

## Capabilities

### New Capabilities
- `order-semantics-selection`: Defines when ordinary orders are sufficient and when exchange-native protection order semantics are required.

### Modified Capabilities
- `execution-gateway-abstraction`: Remove paper gateway as a required interchangeable implementation and clarify gateway support around Backtrader and Binance live semantics.
- `staged-live-auto-execution`: Remove `paper_auto` from supported realtime automatic execution modes and preserve only manual notification plus real staged live modes.
- `live-auto-order-safety`: Remove paper execution safety scenarios and require live automatic protection to follow the same staged safety gates as live entries.
- `manual-live-trade-notifications`: Clarify that manual/local stop-loss notifications remain allowed only as notification behavior and are not proof of live exchange protection.

## Impact

- Affected code:
  - `src/trader/live/auto_execution.py`
  - `src/trader/execution/resolver.py`
  - `src/trader/execution/gateway.py`
  - `src/trader/execution/gateways.py`
  - `src/trader/strategy/backtrader_adapter.py`
  - `src/trader/strategy/execution_kernel.py`
  - `src/trader/exchange/binance/exchange.py`
  - `src/trader/exchange/binance/margin.py`
  - live monitor and dashboard event builders that expose paper execution outcomes
- Affected configuration:
  - task configs using `live_execution_mode=paper_auto`
  - examples and docs that describe paper execution as a staged realtime mode
- Affected tests:
  - Paper gateway and `paper_auto` tests should be removed or rewritten around Backtrader/live gateway semantics.
  - New tests are required for order semantic selection, Backtrader protection behavior, Binance live protection request mapping, and protection failure handling.
- External systems:
  - Binance spot and margin APIs for native order types, OCO, cancellation, replacement, and reconciliation.
