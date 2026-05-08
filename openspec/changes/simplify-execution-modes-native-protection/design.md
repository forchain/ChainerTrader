## Context

The repository currently has three overlapping execution concepts:

- Backtrader backtests already support broker-managed order types and are the intended test environment.
- `paper_auto` simulates realtime execution with local cash and position state.
- The newer execution gateway abstraction defines portable order and protection intents for Backtrader, paper, and Binance live.

The overlap makes the project harder to reason about. The local paper exchange cannot become an exchange-equivalent simulator, while Backtrader already provides stronger test semantics. At the same time, live execution cannot degrade Chainer framework stop-loss or stop/take-profit behavior into ordinary closed-candle exits when the framework parameter semantics require real stop behavior.

## Goals / Non-Goals

**Goals:**

- Remove `paper_auto` from the supported realtime automatic execution model.
- Make Backtrader the project test/backtest execution engine for framework order semantics.
- Use the simplest order type that satisfies the strategy semantics.
- Require native exchange protection only when ordinary orders cannot satisfy the configured requirement.
- Route live automatic execution through the execution gateway so entry, close, protection placement, replacement, cancellation, persistence, and reconciliation share one contract.
- Fail explicitly when live protection cannot be placed or verified.

**Non-Goals:**

- Do not build a new local paper exchange.
- Do not require advanced order types for plain market entry or market close.
- Do not claim Backtrader can reproduce intrabar tick ordering from coarse OHLC data.
- Do not require manual notification mode to place exchange-native protection.
- Do not complete production credential smoke testing without explicit user-provided live credentials and opt-in.

## Decisions

### Decision: Semantic order selection replaces advanced-order preference

Use a semantic selector before gateway submission:

```
strategy/framework intent
        |
        v
semantic order selector
        |
        +-- ordinary market entry/close  -> market order
        +-- take-profit only             -> simplest valid native TP/limit behavior
        +-- stop-loss                    -> native stop protection
        +-- stop + take-profit           -> native OCO/bracket semantics when available
        +-- breakeven stop move          -> native cancel/replace or cancel + new stop
```

Rationale: this keeps the design simple while preserving the Chainer framework's stop-loss semantics. Ordinary orders remain valid where they satisfy the requirement. They are not valid substitutes for automatic live stop-loss protection because they require client-side observation and delayed submission.

Alternative considered: always use native advanced orders for every live order. Rejected because it adds exchange complexity for cases where a market order is sufficient.

Alternative considered: use ordinary closed-candle exits for all stops. Rejected because it does not meet stop-loss semantics in live automation.

### Decision: Backtrader is the test execution engine; paper is not a target gateway

Backtrader remains the backtest and test execution path for strategy validation. The implementation should strengthen Backtrader order mapping around native broker semantics instead of expanding the local paper gateway.

Rationale: Backtrader can model stop, limit, OCO, and bracket behavior within the available data granularity. A local paper exchange duplicates effort and still lacks realistic exchange lifecycle behavior.

Alternative considered: keep paper gateway as a full exchange-like simulator. Rejected because the additional complexity does not improve confidence beyond Backtrader and creates another behavior surface to maintain.

### Decision: Live automatic execution must use the execution gateway

Realtime live automatic modes must submit order and protection intents through `ExecutionGateway`. The legacy operation-only router may remain temporarily as a compatibility layer during migration, but it must not be the final owner of live order behavior.

Rationale: entry, close, stop, take-profit, replacement, cancellation, persistence, and reconciliation need consistent idempotency and event handling. A direct router path cannot safely add protection without duplicating the gateway.

Alternative considered: patch protection handling into `AutoExecutionRouter`. Rejected because it preserves two execution abstractions and makes recovery harder.

### Decision: Protection is not armed until native acceptance is verified

Live automatic execution must not report an active trade as protected until the gateway has accepted and verified the native exchange order identifiers needed for the selected protection semantics.

Rationale: a filled live entry without verified stop protection is a materially different risk state from a protected trade. The dashboard and persisted execution state must expose that difference.

Alternative considered: trust any exchange API response blindly. Rejected because reconnect/restart recovery depends on stable order identifiers.

### Decision: Manual notification keeps local risk behavior as notification only

Manual mode may continue to calculate and notify local stop-loss or take-profit triggers. Those notifications must not be described as exchange-native protection and must not be reused as proof that a live automatic trade is protected.

Rationale: manual workflows and automatic live execution have different safety contracts.

## Risks / Trade-offs

- Live protection support differs by Binance account mode and symbol rules -> Mitigation: capabilities must be explicit, unsupported protection must reject before reporting `protection_armed`, and tests must cover unsupported capability paths.
- OCO/bracket mapping can vary between Backtrader and Binance -> Mitigation: test portable scenarios at the intent/event level and maintain gateway-specific tests for exact API calls.
- Backtrader OHLC execution cannot know intrabar high/low order -> Mitigation: document the data-granularity limitation and use lower timeframe data when stop/take-profit ordering precision matters.
- Removing `paper_auto` breaks existing configs -> Mitigation: provide config migration guidance to use `manual_notify` for no-order realtime observation or Backtrader tasks for test execution.
- A live entry may fill before protection placement fails -> Mitigation: persist the failure, emit a protection-missing event, and apply an explicit fail-safe policy such as immediate market close or halt requiring operator action.
