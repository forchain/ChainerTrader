## Context

The current realtime live path is built around a persistent Backtrader live runner and `manual_notify` semantics. It consumes realtime Binance kline updates, executes strategies only on closed candles, publishes dashboard events, and sends manual notifications without placing exchange orders. The older polling live path still has automatic exchange placement through `TraderTask.operate_exchange()`, but realtime live tasks explicitly reject non-manual execution modes.

The desired next step is not a direct jump to full automatic trading. It is a staged rollout that proves the realtime automatic execution path in simulation first, then with tightly capped real orders, then with full configured sizing. The design must also support real short execution eventually, and for the first version that means Binance cross margin rather than spot shorting, isolated margin, or futures.

## Goals / Non-Goals

**Goals:**
- Add realtime staged automatic execution modes while keeping `manual_notify` unchanged.
- Use `paper_auto` as the first automatic mode: strategy operations become simulated orders and paper account state updates, with no exchange order calls.
- Use `small_live_auto` as the first real-order mode: strategy operations may place real orders, but every order is capped by `live_trade_max_notional`.
- Use `full_live_auto` as the full automatic mode: order sizing follows the task/strategy sizing policy while retaining validation, duplicate prevention, and failure handling.
- Support real short execution only when explicitly enabled as Binance cross margin with `live_short_execution = "margin_cross"`.
- Keep staged execution framework-owned. Strategies emit operations; shared runtime/execution code decides how to simulate or route them.

**Non-Goals:**
- Implement Binance isolated margin in this change.
- Implement Binance futures in this change.
- Implement exchange-side OCO, bracket, stop-limit, take-profit, or trailing stop orders.
- Implement fill reconciliation, partial-fill lifecycle management, or account stream listeners.
- Guarantee that paper account state matches external manual trades or external exchange-side position changes.

## Decisions

### Decision 1: Introduce a shared live execution router behind realtime strategy operations

Realtime operation handling should route each new strategy operation through a framework-owned execution boundary. The router should receive the task config, operation, symbol, current known execution state, and exchange adapter. It should return a structured execution event describing what happened: simulated fill, real order accepted, skipped, or failed.

This keeps strategies responsible only for signal generation and preserves the framework-first policy for mode routing and trade lifecycle behavior.

Alternatives considered:
- Add `auto_trade` branches directly inside `start_realtime()`: fast, but grows an already large method and duplicates safety logic.
- Let each strategy place orders directly: violates shared signal routing and makes testing staged execution across strategies much harder.

### Decision 2: Make `paper_auto` the first automatic mode and initialize it from task config

`paper_auto` should use configured `free` cash and `manual_start_position` as the initial paper account state. It should support both long and short simulated positions so the strategy and dashboard can validate both sides without exchange risk.

Alternatives considered:
- Initialize paper state from exchange balances: closer to account reality, but it reintroduces credentials/account dependencies into the first automatic safety stage.
- Restore paper state from previous task history first: useful later, but not required for the first rollout and can be added as a follow-up once the execution event model is stable.

### Decision 3: Gate real-order modes by explicit mode and fixed small-live notional cap

`small_live_auto` should require a positive `live_trade_max_notional` and MUST size every real order at or below that cap. `full_live_auto` may use task/strategy sizing, but still must pass the same validation and duplicate-prevention gates.

Alternatives considered:
- Use a percent scale in small live mode: flexible, but harder to reason about operationally and can change silently as account/task capital changes.
- Use the existing `free / price` calculation immediately: too large a jump from manual notifications to real orders.

### Decision 4: Treat real short execution as an explicit cross-margin capability

Spot `SHORT` is not a true open-short operation. The first real short implementation should use Binance cross margin only when `live_short_execution = "margin_cross"` is configured. If the mode is disabled, real automatic modes must skip `SHORT` and short-side `CLOSE` operations rather than silently mapping them into spot sells.

Alternatives considered:
- Support Binance isolated margin first: safer per symbol, but requires isolated account transfer, borrow, repay, and per-pair readiness handling not present in the current code.
- Support Binance futures first: a different account, API, leverage model, and liquidation/funding model; it should be a separate change.
- Treat spot `SELL` as short: incorrect and dangerous because spot sell only reduces or liquidates existing base assets.

### Decision 5: Record execution outcomes separately from notification events

Manual notifications describe recommendations. Automatic execution needs structured order intent and execution result data, even in paper mode. The runtime should persist enough data to reconstruct which strategy operation was routed, whether it was simulated or sent to the exchange, what quantity/notional was used, and why it was skipped or failed.

Alternatives considered:
- Reuse `ManualTradeNotificationEvent` for paper and live orders: it has useful presentation fields, but its semantics explicitly say recommendation, not execution.
- Store only raw exchange responses: insufficient for paper mode, skipped operations, and deterministic tests.

## Risks / Trade-offs

- Real order placement can duplicate on reconnect or process restart. -> Use operation identity keys such as signal event id plus side/time/price fallback, persist routed outcomes, and refuse duplicate routed operations.
- Cross-margin short can borrow unexpectedly or increase liquidation risk. -> Require explicit `live_short_execution = "margin_cross"`, cap small-live notional, log side effect behavior, and skip when margin mode/readiness is not confirmed.
- Paper state can diverge from real account state. -> Label paper execution clearly and keep it independent from exchange balances.
- `full_live_auto` can place larger orders than intended. -> Keep explicit mode selection, preserve validation gates, and require tests proving `small_live_auto` caps are not reused accidentally as full sizing.
- Exchange precision and minimum notional rules can reject orders. -> Normalize quantity through exchange metadata where available and treat invalid quantity/min-notional failures as skipped/failed execution outcomes.

## Migration Plan

1. Add task configuration fields for staged execution: `live_execution_mode`, `live_trade_max_notional`, and `live_short_execution`, preserving existing defaults.
2. Add an execution event model and live execution router with paper simulation support.
3. Integrate the router into realtime live operation handling while preserving manual-notify notification behavior.
4. Add real-order routing for `small_live_auto` and `full_live_auto` long-side operations.
5. Add guarded Binance cross-margin short routing behind `live_short_execution = "margin_cross"`.
6. Add or update live task examples for paper and small-live modes.
7. Update README live-mode documentation because this changes exposed live trading operation.

Rollback strategy: keep `manual_notify` as the default safe realtime mode. If real-order validation fails, operators can switch live tasks back to `manual_notify` or `paper_auto` without changing strategy code.

## Open Questions

- Should a follow-up change restore paper account state from persisted execution history after restart?
- Should real fill reconciliation use Binance user data streams or explicit order query polling in a later change?
- Should isolated margin be the next short-capability extension after cross margin, or should futures take priority?
