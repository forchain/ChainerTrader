# Integrated Acceptance Testing Plan: ChainerTrader Execution & Kernel Decoupling

## Objective
This plan defines the comprehensive testing strategy for the decoupled execution architecture and modularized strategy kernel in ChainerTrader. It ensures that the core trading logic remains robust across different execution environments (Backtrader, Paper, Binance Live) and validates the safety mechanisms introduced for staged rollout.

---

## Phase 1: Unit & Integration Regression
**Goal**: Verify that the extracted kernel components (`RiskEngine`, `SignalRouter`, `TradeLifecycleEngine`) perform their logic correctly and maintain compatibility with the `BaseStrategy`.

### 1.1 RiskEngine Logic Verification
- **Test Case**: Initial Stop-Loss & Take-Profit Calculation.
  - **Input**: `OrderIntent` (LONG), `stop_price=95000`, `take_profit_price=110000`.
  - **Expected**: `RiskIntent` of type `BRACKET` with correct prices and `trade_id`.
- **Test Case**: Breakeven Stop Replacement.
  - **Input**: `OrderIntent`, `new_stop_price=100000`, `replacement_of_order_id="order-1"`.
  - **Expected**: `RiskIntent` of type `REPLACE_STOP` targeting `order-1`.
- **Command**: `pytest tests/test_base_strategy_kernel_extraction.py`
- **Expected Outcome**: All assertions for price calculation and intent mapping pass.

### 1.2 SignalRouter Decision Matrix
- **Test Case**: Mode-based Blocking.
  - **Input**: `LONG_ONLY` mode, `short_signal=True`.
  - **Expected**: `SignalRouteAction(action_type=BLOCKED, reason="mode")`.
- **Test Case**: Position-based Blocking.
  - **Input**: Active trade present, `can_open_new_position=False`.
  - **Expected**: `SignalRouteAction(action_type=BLOCKED, reason="active_trade")`.
- **Command**: `pytest tests/test_base_strategy_signal_routing.py`
- **Expected Outcome**: Routing decisions align with mode constraints and current position state.

### 1.3 TradeLifecycleEngine State Transitions
- **Test Case**: Entry Sequence.
  - **Steps**: `PENDING_ENTRY_CONFIRM` -> `OPENING` -> `ACTIVE`.
  - **Verification**: Assert status updates after `mark_entry_opening` and `mark_entry_filled`.
- **Command**: `pytest tests/test_strategy_execution_kernel.py`
- **Expected Outcome**: Trade status transitions occur according to the state machine rules.

---

## Phase 2: Gateway Parity Testing
**Goal**: Ensure that all execution gateways behave identically from the perspective of the `ExecutionOrchestrator`.

### 2.1 Normalized Event Sequences
- **Test Case**: Gateway Event Consistency.
  - **Action**: Execute Buy-Stop-Sell sequence on `Backtrader`, `Paper`, and `BinanceLive` (Mocked).
  - **Expected Outcome**:
    - All gateways must emit `ORDER_SUBMITTED` followed by `ORDER_ACCEPTED` or `ORDER_FILLED`.
    - All gateways must emit `PROTECTION_ARMED` when a `RiskIntent` is processed.
- **Command**: `pytest tests/test_execution_gateways.py`

### 2.2 Capability-Based Rejection
- **Test Case**: Requesting Unsupported OCO.
  - **Action**: Request OCO protection on a gateway that doesn't support it.
  - **Expected**: `ExecutionResult` with status `REJECTED` and reason `UNSUPPORTED_CAPABILITY`.
- **Command**: `pytest tests/test_execution_gateway_contract.py`

---

## Phase 3: Staged Rollout Simulation
**Goal**: Validate the safety boundaries and transition logic between execution modes.

### 3.1 Safety Caps in `small_live_auto`
- **Test Case**: Notional Limit Enforcement.
  - **Input**: Submit order with notional value exceeding `live_trade_max_notional`.
  - **Expected**: Order rejected or blocked by the gateway resolution layer.
- **Command**: `pytest tests/test_execution_gateway_rollout_safety.py`

### 3.2 Mode Resolver Constraints
- **Test Case**: Invalid Mode Transition.
  - **Input**: Requesting `BINANCE_LIVE` while the environment is configured for `paper_auto`.
  - **Expected**: `GatewayResolutionError`.
- **Command**: `pytest tests/test_execution_gateway_contract.py`

---

## Phase 4: Advanced Order & Reconciliation Validation
**Goal**: Verify complex order handling (OCO) and recovery from system failures.

### 4.1 Native OCO Placement (Binance)
- **Test Case**: OCO Native Mapping.
  - **Action**: Simulate OCO placement with a mock Binance exchange.
  - **Expected**: `gateway_order_id` should be a comma-separated string of the Stop and TP IDs (e.g., `"stop-1,tp-1"`).
  - **Verification**: Metadata must show `native: true`.
- **Command**: `pytest tests/test_execution_gateways.py`

### 4.2 Durable State & Reconciliation
- **Test Case**: Simulated Crash Recovery.
  - **Step 1**: Execute an entry, save state to `ExecutionStateStore`.
  - **Step 2**: Initialize a new `ExecutionOrchestrator` with the same store.
  - **Step 3**: Run `reconcile()`.
  - **Expected**: Orchestrator identifies the active position from the gateway and synchronizes local state.
- **Command**: `pytest tests/test_execution_state_store.py`

---

## Phase 5: Real-Trade Smoke Test (Binance BTC-USDT)
**Goal**: Final end-to-end verification on a live exchange with minimal risk.

### 5.1 Minimal Notional Entry/Exit
- **Setup**: `live_execution_mode="small_live_auto"`, `live_trade_max_notional=15.0`.
- **Action**: Trigger a real BTC-USDT trade (e.g., via a dummy signal or manual override).
- **Verification**:
  - [ ] Order visible in Binance "Open Orders" or "Trade History".
  - [ ] Stop-Loss and Take-Profit orders placed (as OCO if possible).
  - [ ] Local logs show `ORDER_FILLED` and `PROTECTION_ARMED`.
  - [ ] Trade closed successfully via `close_position`.
- **Run Command**: 
  ```bash
  python -m trader.task.run_task configs/tasks/live_smoke_test.json --mode small_live_auto
  ```

---

## Summary of Verification Commands
| Category | Command |
|-----------|---------|
| **Core Logic** | `pytest tests/test_base_strategy_kernel_extraction.py tests/test_base_strategy_signal_routing.py` |
| **State Machine** | `pytest tests/test_strategy_execution_kernel.py` |
| **Gateways** | `pytest tests/test_execution_gateways.py tests/test_execution_gateway_contract.py` |
| **Persistence** | `pytest tests/test_execution_state_store.py` |
| **E2E Integration** | `pytest tests/test_macd_triple_divergence_execution.py` |
| **Rollout Safety** | `pytest tests/test_execution_gateway_rollout_safety.py` |
