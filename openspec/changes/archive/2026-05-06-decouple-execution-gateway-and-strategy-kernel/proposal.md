## Why

`BaseStrategy/ChainerTrader` currently mixes signal generation, trade lifecycle, risk management, and execution concerns, which makes strategy extension and live migration harder. We need a framework-level abstraction so the same strategy code can move from backtest to paper to live by configuration, with no strategy-side interface changes.

## What Changes

- Introduce a framework-level `ExecutionGateway` contract for order/risk execution and reconciliation.
- Add three gateway implementations with a shared event/state contract: backtrader, paper, and Binance live.
- Split strategy framework responsibilities into composable kernel modules (signal, lifecycle, risk, orchestration) while preserving existing strategy-facing behavior.
- Standardize execution event and state models so parity can be verified across backtest and paper before live rollout.
- Define the minimum order semantics required for MACD triple divergence migration: market entry/exit, protective stop, take-profit, OCO-style mutual cancellation, breakeven stop replacement, and reconciliation.
- Preserve staged auto-trading safety semantics by mapping gateway selection through existing `live_execution_mode` values (`manual_notify`, `paper_auto`, `small_live_auto`, `full_live_auto`) rather than adding an independent live-ordering switch.
- Define live protection semantics so Binance native protection orders are distinguished from local monitoring/guardian fallback and protection is only reported as armed after confirmed exchange-side acceptance.
- Add execution state persistence as part of the phase 1 contract so reconciliation has a durable source for intent ids, order ids, protection state, and idempotency keys.

## Capabilities

### New Capabilities
- `execution-gateway-abstraction`: Unified execution contract and event/state model with interchangeable backtrader, paper, and live implementations.
- `strategy-kernel-modularization`: Composable strategy kernel that separates signal, lifecycle, and risk responsibilities from strategy classes.

### Modified Capabilities
- `framework-signal-routing`: Signal routing shall hand off framework trade actions as execution intents instead of binding directly to broker/exchange APIs.
- `strategy-signal-context`: Signal context shall flow into risk/execution intents so strategy metadata remains portable across backtrader, paper, and live gateways.

## Impact

- Affected code: `src/trader/strategy/*`, `src/trader/live/*`, `src/trader/task/*`, exchange adapter boundaries, and execution-related tests.
- Operational impact: backtest and live runtimes use a shared execution interface; live gateway selection is derived from existing staged `live_execution_mode` values instead of a parallel ordering switch.
- Safety impact: existing `manual_notify` and `small_live_auto` caps remain authoritative; gateway configuration must not bypass notification-only mode or live notional caps.
- Testing impact: add parity tests for execution events and lifecycle outcomes across backtrader and paper; live smoke tests must be credential-gated and explicitly enabled.
