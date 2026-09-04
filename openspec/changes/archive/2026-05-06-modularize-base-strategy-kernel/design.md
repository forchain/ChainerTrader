## Context

`decouple-execution-gateway-and-strategy-kernel` added an execution contract and gateway implementations, but `BaseStrategy` still acts as the real strategy kernel. It defines trade context/status types, owns active-trade registries, evaluates mode routing, confirms entries/exits, directly calls Backtrader `buy`/`sell`/`cancel`, manages stop/take-profit orders, computes breakeven moves, and contains MACD triple divergence fallback classification logic.

This change is a follow-up refactor to make the previous architecture true in code. It must preserve existing strategy subclass behavior while moving reusable trading behavior behind framework modules and adapters.

## Goals / Non-Goals

**Goals:**
- Make `BaseStrategy` a thin Backtrader compatibility shell and strategy hook surface.
- Move trade context/status definitions and lifecycle transitions into a reusable lifecycle/domain module.
- Move `LONG_ONLY`/`SHORT_ONLY`/`BOTH` routing decisions into a reusable signal router.
- Move stop-loss, take-profit, and breakeven computation into a risk module that emits normalized risk intents.
- Move Backtrader-specific order placement and cancellation into an adapter that implements the execution boundary.
- Remove strategy-specific fallback logic from framework base code while preserving MACD triple divergence report classifications.
- Prove parity with existing BaseStrategy behavior before deleting old paths.

**Non-Goals:**
- Changing strategy signal semantics.
- Replacing Backtrader as the backtest engine.
- Expanding Binance order support beyond the existing execution-gateway capability set.
- Modeling paper partial fills, latency, or slippage beyond the current deterministic paper behavior.
- Rewriting every legacy strategy subclass in one change.

## Decisions

### Decision 1: Use Extract-Then-Delegate, Not Big-Bang Rewrite

Extract lifecycle, signal, risk, and Backtrader adapter modules first, then delegate `BaseStrategy` methods to them while preserving the existing public surface.

Rationale: existing strategy tests cover many trading edge cases. A compatibility shell lets us move ownership without forcing all strategies to migrate immediately.

Alternatives considered:
- Rewrite strategies to use a new base class immediately: too high-risk and would mix migration with behavior changes.
- Keep `BaseStrategy` as owner and add helper methods: this repeats the current failure mode where modules exist but the base class still owns behavior.

### Decision 2: Define a Strategy Kernel Facade

Introduce a `StrategyKernel` or equivalent facade that coordinates:
- `SignalRouter`
- `TradeLifecycleEngine`
- `RiskEngine`
- `ExecutionOrchestrator`
- a broker-specific adapter such as `BacktraderStrategyExecutionAdapter`

`BaseStrategy.next()` and `notify_order()` should delegate into this facade. The facade returns state updates/events; `BaseStrategy` handles Backtrader lifecycle plumbing and strategy hooks.

Rationale: this creates one composition point and prevents `BaseStrategy` from directly wiring every module again.

Alternatives considered:
- Let `BaseStrategy` call each module directly: less code now, but it leaves the class as the orchestration owner.
- Put everything into `ExecutionOrchestrator`: execution orchestration should not own signal semantics or strategy lifecycle rules.

### Decision 3: Lifecycle State Is Framework Domain State

Move `TradeStatus`, `TradeContext`, trade registry behavior, pending-entry/exit confirmation transitions, and order-result transitions into lifecycle/domain modules. `BaseStrategy` may expose compatibility aliases temporarily, but it must not be the source of truth.

Rationale: paper/live parity requires a lifecycle state machine that is independent of Backtrader strategy inheritance.

Alternatives considered:
- Keep `TradeContext` nested in `BaseStrategy`: convenient but blocks reuse outside Backtrader.

### Decision 4: Risk Engine Produces Intents Before Adapter Placement

Risk computation should decide what protection is needed: initial stop, take-profit, OCO-style pairing, breakeven replacement, or cancellation. It should not call Backtrader directly. The configured adapter/gateway is responsible for concrete order placement.

Rationale: this keeps backtest, paper, and live protection semantics aligned at the intent boundary.

Alternatives considered:
- Leave Backtrader protective orders in `BaseStrategy` and only map live later: this is exactly the divergence risk the user raised.

### Decision 5: Strategy-Specific Classifications Must Flow Through Metadata

Remove `macd_stop_enabled` and MACD-specific text fallback from `BaseStrategy`. MACD triple divergence must provide explicit exit metadata when it requests an exit, or a report adapter must classify legacy data outside the base framework.

Rationale: base framework code must not know individual strategy names, parameters, or report labels.

Alternatives considered:
- Keep a generic fallback hook in `BaseStrategy`: acceptable only if it is strategy-neutral and receives metadata, not if it embeds strategy-specific checks.

## Risks / Trade-offs

- Behavior regression in backtests → Add parity tests around existing BaseStrategy signal routing, stop/take-profit, breakeven, and MACD triple divergence report outputs before deleting old logic.
- Temporary compatibility duplication → Allow aliases/shims during migration, but add tests proving new modules own decisions and `BaseStrategy` delegates.
- Refactor size may become too large → Land in phases: domain extraction, signal router, lifecycle, risk, adapter, cleanup.
- Backtrader quirks leak into domain objects → Keep Backtrader order objects inside the Backtrader adapter; lifecycle state stores portable order references and normalized event data.
- Async execution orchestrator mismatch with Backtrader sync callbacks → Keep adapter sync-friendly and isolate async persistence/orchestration where already used by live runtime.

## Migration Plan

1. Add extracted domain types and tests without changing behavior.
2. Move signal routing into `SignalRouter`; update `BaseStrategy._process_signals()` to delegate.
3. Move lifecycle transitions into `TradeLifecycleEngine`; update `enter_trade`, `exit_trade`, `_process_trade_engine`, and `notify_order` to delegate.
4. Move stop/take-profit/breakeven decisions into `RiskEngine`; route concrete placement through Backtrader adapter.
5. Remove MACD-specific fallback from `BaseStrategy`; preserve report behavior through explicit metadata.
6. Add structural guard tests that fail if strategy-specific code or direct protective order placement returns to `BaseStrategy`.
7. Run existing strategy regression suites and targeted parity tests.

Rollback is straightforward before cleanup by keeping compatibility aliases and restoring delegation points to the previous implementation. After cleanup, rollback should use git revert of this change rather than mixing old and new ownership.

## Open Questions

- Should the compatibility aliases `BaseStrategy.TradeStatus`, `BaseStrategy.TradeContext`, and `BaseStrategy.SignalSnapshot` remain indefinitely for external users, or be deprecated after one release?
- Should the Backtrader adapter live under `src/trader/strategy/` because it wraps strategy lifecycle, or under `src/trader/execution/` because it places orders?
