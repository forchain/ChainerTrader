## Context

Current strategy runtime is inheritance-heavy: `BaseStrategy/ChainerTrader` owns signal lifecycle handling, trade state transitions, stop/take-profit management, and order placement semantics. This creates coupling between strategy logic and execution details, which increases migration risk between backtest, paper, and live environments.

The current staged auto-trading work already introduced mode-based execution routing, but execution semantics are still not fully modeled as a stable framework contract that can be reused by backtrader, paper, and live gateways with parity checks.

## Goals / Non-Goals

**Goals:**
- Define a stable framework execution contract independent of concrete brokers/exchanges.
- Introduce modular runtime components so strategy classes focus on signal/context output.
- Provide three gateway implementations (`backtrader`, `paper`, `binance_live`) under one interface.
- Make mode switching configuration-driven with no strategy API changes.
- Enable parity verification (event sequence and lifecycle outcome) between backtrader and paper.
- Cover the minimum order semantics required by MACD triple divergence migration before broadening gateway support.
- Preserve staged auto-trading safety controls while adding gateway abstraction.

**Non-Goals:**
- Full coverage of all Binance order types in this change.
- Rewriting every existing strategy in one step.
- Changing strategy signal math or MACD triple divergence logic.
- Ungated live exchange tests in normal local or CI verification.

## Decisions

### Decision 1: Introduce `ExecutionGateway` as the single execution boundary
- Choice: all execution actions go through a unified gateway contract (`open_position`, `place_protection`, `replace_protection`, `close_position`, `cancel_order`, `reconcile`).
- Rationale: isolates exchange and simulator differences to adapter layer; enables configuration-based switching.
- Alternatives considered:
  - Keep direct `exchange.new_order` calls in runtime: simpler short-term but keeps coupling.
  - Strategy-level broker branching: increases strategy complexity and breaks portability.

### Decision 1b: Existing staged live modes remain authoritative
- Choice: gateway resolution is subordinate to the existing `live_execution_mode` safety model. `manual_notify` remains notification-only, `paper_auto` resolves to the paper gateway, `small_live_auto` and `full_live_auto` may resolve to Binance live, and `small_live_auto` continues to enforce `live_trade_max_notional`.
- Rationale: the gateway abstraction must not create a second switch that bypasses staged auto-trading protections.
- Alternatives considered:
  - Add a separate `execution_gateway=binance_live` switch that can override `live_execution_mode`: unsafe because it could bypass `manual_notify` or small-live caps.
  - Replace `live_execution_mode` entirely: too disruptive and loses the staged rollout semantics already implemented.

### Decision 1a: Scope gateway parity to an explicit minimum capability set
- Choice: gateways must share the same contract and equivalent behavior only for the supported minimum set: market entry/close, protective stop, take-profit limit, OCO-style mutual cancellation, breakeven stop replacement, cancellation, and reconciliation.
- Rationale: Binance live, backtrader, and paper cannot be fully equivalent across all exchange order types, account modes, latency, and fill semantics.
- Alternatives considered:
  - Claim full gateway equivalence: too broad and likely false for live exchange behavior.
  - Map every Binance order type now: unnecessary for MACD triple divergence migration.

### Decision 2: Use normalized execution events as parity contract
- Choice: define a common event schema emitted by every gateway.
- Rationale: parity should be judged by behavior (events/state), not internal implementation.
- Alternatives considered:
  - Compare raw exchange responses: not portable across gateways.
  - Compare only PnL aggregates: misses lifecycle regressions.

### Decision 2a: Paper gateway must model exchange-like lifecycle
- Choice: paper mode must use the same submitted/accepted/filled/canceled/rejected/protection/reconcile event flow as live mode, even when fills are deterministic.
- Rationale: a paper gateway that only mutates local cash and position does not reduce live migration risk.
- Alternatives considered:
  - Keep paper as immediate-fill accounting only: simpler but does not validate order lifecycle or protection behavior.

### Decision 2b: Live protection is native-first and explicit about fallback
- Choice: Binance live gateway emits `protection_armed` only after exchange-native protection orders are accepted and verified. Client-side WebSocket monitoring is modeled as local guardian state, not as native protection. Unsupported or unverified native protection returns explicit rejected/unsupported results.
- Rationale: live risk exposure depends on whether the exchange, not the local process, owns the protective order.
- Alternatives considered:
  - Treat WebSocket monitoring as equivalent to exchange protection: unsafe if the process disconnects or crashes.
  - Silently downgrade unsupported protection to local monitoring: hides risk and makes events misleading.

### Decision 2c: Reconciliation uses a durable execution state store
- Choice: phase 1 introduces a durable execution state store for intent ids, operation ids, gateway/stage mode, trade ids, order roles, exchange order ids, protection ids, statuses, quantities, prices, timestamps, and idempotency keys.
- Rationale: restart/reconnect reconciliation cannot be reliable if execution state only exists in monitor snapshots or in memory.
- Alternatives considered:
  - Reuse transient monitor event buffers: insufficient for restart recovery and duplicate prevention.
  - Query exchange state only: misses paper/backtrader state and local intent/idempotency mapping.

### Decision 3: Split strategy framework into composable kernel modules
- Choice: separate `SignalEngine`, `TradeLifecycleEngine`, `RiskEngine`, `ExecutionOrchestrator`, `ReconcileEngine`.
- Rationale: each module has one responsibility and can be tested independently.
- Alternatives considered:
  - Continue with monolithic base class and incremental patching: low migration cost now, high long-term complexity.

### Decision 4: Migrate in phases with compatibility adapter
- Choice: keep existing strategy inheritance working while routing core responsibilities through new modules.
- Rationale: avoids breaking all strategies; allows one strategy (MACD triple divergence) to be a pilot.
- Alternatives considered:
  - Big-bang refactor: faster conceptual cleanup, unacceptable delivery and regression risk.

## Risks / Trade-offs

- [Risk] Event schema drift between gateways causes false parity.
  - Mitigation: central event mapper tests and golden event fixtures.
- [Risk] Lifecycle logic split introduces temporary duplicate paths.
  - Mitigation: explicit compatibility adapter and staged cutover flags.
- [Risk] Paper behavior diverges from live edge cases (partial fills, cancel latency).
  - Mitigation: model mandatory edge cases in paper engine and add reconcile-driven assertions.
- [Risk] Migration creates broad test churn.
  - Mitigation: migrate one strategy family first, then widen only after parity pass.
- [Risk] Live smoke tests submit real orders unintentionally.
  - Mitigation: require explicit credentials, explicit enable flag, and small-size configuration before any live smoke path can run.
- [Risk] Gateway config conflicts with staged execution mode.
  - Mitigation: reject conflicting configs and derive live order permission from `live_execution_mode`.
- [Risk] System reports protection armed when only local monitoring is active.
  - Mitigation: separate native protection events from local guardian events and require exchange order ids for native protection armed state.
- [Risk] Reconciliation duplicates orders after restart.
  - Mitigation: persist idempotency keys and order identities before repair or resubmission decisions.

## Migration Plan

1. Add contract layer (`ExecutionGateway`, intents, normalized events, state store interfaces, mode resolver).
2. Add `BacktraderExecutionGateway` and adapt current live/backtest runtime calls to use gateway boundary.
3. Add `PaperExecutionGateway` with lifecycle-equivalent behavior and deterministic simulation options.
4. Add `BinanceLiveExecutionGateway` mapping minimum required order capabilities for MACD triple divergence.
5. Add durable execution state persistence and reconciliation loading before enabling repair/resubmission behavior.
6. Extract `RiskEngine` and `TradeLifecycleEngine` from base strategy flow behind compatibility adapter.
7. Run parity suite (`backtrader` vs `paper`) on MACD triple divergence scenarios.
8. Enable live small-size gateway path using same strategy code and contracts only behind explicit live-smoke prerequisites.

Rollback strategy:
- Keep compatibility path and legacy execution route toggles until parity and live-smoke pass.

## Open Questions

- Whether paper mode should support configurable slippage/latency profiles in phase 1 or later.
- Whether short live execution remains cross-margin only in this phase or expands to futures mapping.
