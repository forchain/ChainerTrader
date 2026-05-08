## 1. Execution Contract Foundation

- [x] 1.1 Define unified execution intent models and result models (`OrderIntent`, `RiskIntent`, views, reconcile payloads)
- [x] 1.2 Define `ExecutionGateway` interface and mode-based gateway resolver
- [x] 1.3 Define normalized `ExecutionEvent` schema and shared reason/status taxonomy
- [x] 1.4 Define explicit gateway capability descriptors and unsupported-capability result handling
- [x] 1.5 Define staged execution mode mapping so `manual_notify`, `paper_auto`, `small_live_auto`, and `full_live_auto` gate gateway resolution
- [x] 1.6 Add contract-level unit tests for intent validation, event normalization, and mode/gateway conflict rejection

## 2. Execution State Persistence

- [x] 2.1 Define durable execution state schema for intents, orders, protection orders, statuses, gateway mode, staged execution mode, and idempotency keys
- [x] 2.2 Implement execution state store interface with repository-backed persistence
- [x] 2.3 Persist intent and order identities before reconciliation can repair, skip, or resubmit execution
- [x] 2.4 Add restart/reconcile tests proving duplicate submissions are prevented by persisted state

## 3. Gateway Implementations

- [x] 3.1 Implement `BacktraderExecutionGateway` adapter using current backtrader order semantics
- [x] 3.2 Implement `PaperExecutionGateway` with deterministic fill/cancel/protection simulation and standardized events
- [x] 3.3 Implement `BinanceLiveExecutionGateway` for minimum required order capabilities (entry, native stop/take-profit/OCO where supported, replace, close, reconcile)
- [x] 3.4 Ensure Binance live emits `protection_armed` only after accepted native exchange protection orders are verified
- [x] 3.5 Add unsupported/rejected live protection paths and fail-safe protection-missing events
- [x] 3.6 Add minimum order mapping tests for market entry/close, stop, take-profit, OCO-style cancellation, and breakeven replacement
- [x] 3.7 Add gateway conformance tests to assert request/response and event contract parity for supported capabilities

## 4. Strategy Kernel Modularization

- [x] 4.1 Extract `TradeLifecycleEngine` from base strategy transition logic
- [x] 4.2 Extract `RiskEngine` for stop-loss, take-profit, and breakeven intent generation
- [x] 4.3 Add `ExecutionOrchestrator` to consume intents and call configured gateway
- [x] 4.4 Route existing signal-routing outcomes into normalized execution intents
- [x] 4.5 Add compatibility adapter so existing strategy subclasses keep current external behavior

## 5. Runtime Integration and Reconciliation

- [x] 5.1 Integrate gateway/orchestrator into trader live runtime and task flow
- [x] 5.2 Integrate reconciliation workflow on startup/reconnect using persisted execution state and current gateway/account views
- [x] 5.3 Ensure configuration-only switching respects staged modes and rejects unsafe gateway/mode conflicts
- [x] 5.4 Update monitoring payloads to include normalized execution event traces and distinguish native protection from local guardian state

## 6. Validation and Rollout Safety

- [x] 6.1 Add parity test suite for MACD triple divergence across backtrader and paper (event sequence + lifecycle outcomes)
- [x] 6.2 Add explicitly gated small-size live smoke tests using the same strategy interface and gateway contract
- [x] 6.3 Document migration/rollback toggles, staged mode mapping, native protection semantics, and operator acceptance checklist
- [x] 6.4 Run targeted regression suite and capture residual risk notes

### Verification Notes

- 2026-05-06: `bash scripts/setup_worktree.sh --profile base` passed.
- 2026-05-06: `openspec validate decouple-execution-gateway-and-strategy-kernel --strict` passed.
- 2026-05-06: `openspec validate staged-realtime-auto-trading --strict` passed.
- 2026-05-06: `uv run ruff check src/trader/execution src/trader/database/execution_state.py src/trader/database/models.py src/trader/database/manager.py src/trader/live/auto_execution.py src/trader/task/trader_task.py src/trader/strategy/execution_kernel.py tests/test_execution_gateway_contract.py tests/test_execution_state_store.py tests/test_execution_gateways.py tests/test_strategy_execution_kernel.py tests/test_execution_gateway_rollout_safety.py tests/test_trader_task_backtrader_live_runtime.py` passed.
- 2026-05-06: `uv run pytest tests/test_execution_gateway_contract.py tests/test_execution_state_store.py tests/test_execution_gateways.py tests/test_strategy_execution_kernel.py tests/test_execution_gateway_rollout_safety.py tests/test_trader_task_backtrader_live_runtime.py tests/test_live_auto_execution.py tests/test_manual_live_trade_notifications.py` passed with 54 passed and 2 skipped.
- Residual risk: small-live real exchange smoke remains explicitly gated by `CHAINERTRADER_ENABLE_SMALL_LIVE_SMOKE=1`, credentials, and a small notional cap; it was not executed in this local regression run.
- Residual risk: Binance native protection mapping is covered with adapter fakes; final production enablement still requires a real exchange smoke in the intended account mode.
- Residual risk: paper fills are deterministic and do not yet model partial fills, exchange latency, or slippage profiles.
