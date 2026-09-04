## Why

The execution gateway change introduced portable gateway contracts, but `BaseStrategy` still owns most strategy-kernel responsibilities: trade context storage, lifecycle transitions, Backtrader order placement, stop/take-profit maintenance, breakeven replacement, signal routing, and a MACD-specific fallback. This keeps the framework hard to extend and undermines the goal of moving the same strategy code from backtest to paper to live by configuration.

## What Changes

- Extract `BaseStrategy` trade context and lifecycle state transitions into dedicated kernel/domain modules used by the legacy Backtrader adapter.
- Extract signal routing for `LONG_ONLY`, `SHORT_ONLY`, and `BOTH` into a reusable router that returns framework actions rather than directly mutating strategy state.
- Extract risk management for stop-loss, take-profit, and breakeven into a reusable risk module that emits execution/risk intents through the execution orchestrator boundary.
- Move Backtrader-specific `buy`/`sell`/`cancel` calls into a Backtrader strategy adapter so `BaseStrategy` no longer directly owns protective order placement semantics.
- Remove MACD triple divergence fallback logic from `BaseStrategy`; preserve classification through explicit strategy-provided exit metadata or a reporting adapter.
- Keep existing strategy subclass APIs backward-compatible during migration: existing subclasses still override signal getters/context hooks and can call `enter_trade`/`exit_trade`, but shared behavior is delegated to kernel modules.
- Add structural and behavioral tests proving `BaseStrategy` is a thin compatibility shell and the extracted modules own lifecycle/risk/signal decisions.

## Capabilities

### New Capabilities
- `base-strategy-kernel-extraction`: Enforces that `BaseStrategy` delegates lifecycle, signal routing, risk, and Backtrader order-adapter behavior to explicit framework modules.

### Modified Capabilities
- `framework-signal-routing`: Signal routing shall be implemented by a reusable router that produces framework actions and lifecycle events instead of embedding mode logic in `BaseStrategy`.
- `strategy-signal-context`: Strategy context and exit classifications shall remain strategy-provided metadata and must not require strategy-specific fallback logic inside the base framework class.

## Impact

- Affected code: `src/trader/strategy/base_strategy.py`, new or existing modules under `src/trader/strategy/`, `src/trader/execution/`, and Backtrader execution adapter boundaries.
- Compatibility impact: existing strategy subclasses should keep their public override/call surface, with adapter shims preserving `enter_trade`, `exit_trade`, signal lifecycle hooks, and report metadata.
- Testing impact: add module-level tests for lifecycle, signal routing, risk intent generation, Backtrader adapter order placement, and regression parity for existing BaseStrategy behavior.
- Risk impact: this is a refactor-heavy change around trading behavior; implementation must be incremental and prove parity before deleting compatibility paths.
