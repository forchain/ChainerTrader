# execution-gateway-abstraction Specification

## Purpose
TBD - created by archiving change decouple-execution-gateway-and-strategy-kernel. Update Purpose after archive.
## Requirements
### Requirement: Unified Execution Gateway Contract
The framework SHALL expose a unified `ExecutionGateway` contract for trade execution, protective order management, cancellation, and reconciliation so strategy logic does not directly depend on backtrader or live exchange APIs.

#### Scenario: Strategy submits entry intent through unified contract
- **WHEN** a strategy emits an entry intent in framework runtime
- **THEN** the runtime SHALL invoke the configured gateway through the same contract regardless of execution mode

### Requirement: Interchangeable Gateway Implementations
The system SHALL provide gateway implementations for `backtrader` and `binance_live` modes that share request and response schemas for the supported minimum capability set. Unsupported features SHALL fail with explicit capability errors rather than silently degrading. The system MUST NOT require a local `paper` gateway as an execution target for strategy validation or staged realtime execution.

#### Scenario: Runtime switches gateway by configuration
- **WHEN** runtime configuration changes execution mode from `backtrader` to `binance_live`
- **THEN** the strategy execution path SHALL continue without strategy interface changes

#### Scenario: Unsupported gateway capability is explicit
- **WHEN** a gateway receives an intent outside its supported capability set
- **THEN** the gateway SHALL reject the intent with a normalized unsupported-capability result

#### Scenario: Paper gateway is not required
- **WHEN** the framework capability matrix is evaluated
- **THEN** `paper` SHALL NOT be required as a gateway implementation for apply readiness or runtime support
- **THEN** Backtrader SHALL be the supported no-live-order execution engine for strategy testing

### Requirement: Gateway Resolution Preserves Staged Live Modes
The system SHALL resolve execution gateways through the staged execution safety model. `manual_notify` SHALL remain notification-only, and live gateway execution SHALL be available only through live-capable modes such as `small_live_auto` and `full_live_auto`.

#### Scenario: Manual notify cannot submit live orders
- **WHEN** runtime configuration uses `live_execution_mode=manual_notify`
- **THEN** gateway resolution SHALL NOT return a gateway path that submits broker or live exchange orders

#### Scenario: Paper auto cannot resolve a gateway
- **WHEN** runtime configuration uses `live_execution_mode=paper_auto`
- **THEN** gateway resolution SHALL reject the mode as unsupported
- **THEN** gateway resolution SHALL NOT return a paper or live execution gateway

#### Scenario: Small live cap remains authoritative
- **WHEN** runtime configuration uses `live_execution_mode=small_live_auto`
- **THEN** all live entry intents SHALL be capped by `live_trade_max_notional` before reaching the live gateway

#### Scenario: Explicit gateway cannot upgrade safety mode
- **WHEN** an explicit gateway configuration conflicts with the staged execution mode
- **THEN** the runtime SHALL reject the configuration instead of allowing the gateway setting to bypass staged safety behavior

### Requirement: Standardized Execution Events
The system SHALL publish normalized execution events across all gateways, including at minimum submission, acceptance, fill, cancellation, rejection, protection armed/triggered/replaced, and reconcile gap detection.

#### Scenario: Equivalent fill outcomes emit normalized events
- **WHEN** an order is filled in different gateways for the same strategy flow
- **THEN** each gateway SHALL emit the same normalized event type with mapped common fields

### Requirement: Reconciliation and Recovery Contract
The gateway contract SHALL support reconciliation APIs to restore position/order state after restart or stream interruption.

#### Scenario: Runtime restarts with open position
- **WHEN** runtime starts and reconciliation is requested for a symbol with active exposure
- **THEN** the gateway SHALL return current position and open protection order views needed to resume lifecycle management

### Requirement: Durable Execution State for Reconciliation
The system SHALL persist execution state needed for reconciliation, idempotency, and restart recovery, including intent ids, operation ids, gateway name, staged execution mode, symbol, trade id, exchange order ids, protection order ids, order roles, order status, quantities, prices, and timestamps.

#### Scenario: Restart recovers idempotency keys
- **WHEN** runtime restarts after submitting an intent
- **THEN** reconciliation SHALL load the persisted intent and order identity before deciding whether to submit, skip, or repair execution

#### Scenario: Protection state is durable
- **WHEN** a protective stop or take-profit order is accepted
- **THEN** the system SHALL persist enough protection state to detect missing, stale, or mismatched protection after restart

### Requirement: Minimum Order Semantics for Strategy Migration
The execution gateway contract SHALL support the minimum order semantics required by Chainer framework strategy migration: market entry, market close, protective stop, take-profit behavior, OCO-style mutual cancellation between stop and take-profit protection when both are required, breakeven stop replacement, cancellation, and reconciliation. The contract SHALL allow ordinary market orders where they satisfy the semantics and SHALL require native protection only where the requested semantics cannot be represented by ordinary orders.

#### Scenario: Ordinary entry and close remain simple
- **WHEN** a strategy requests market entry or market close without conditional protection semantics
- **THEN** each configured live gateway SHALL use ordinary market order behavior
- **THEN** the gateway MUST NOT require OCO or bracket support for the ordinary order

#### Scenario: Protective stop and take-profit are portable
- **WHEN** a trade enters an active position with stop-loss and take-profit values
- **THEN** each configured gateway SHALL represent both protection rules through the shared protection intent and event model

#### Scenario: Breakeven replaces protective stop
- **WHEN** breakeven logic moves the stop price for an active trade
- **THEN** each configured gateway SHALL process a protection replacement intent and emit a normalized protection-replaced event

### Requirement: Binance Live Protection Uses Native Orders When Armed
The Binance live gateway SHALL treat exchange-native accepted protection orders as the source of truth for `protection_armed` events. Client-side market monitoring or WebSocket guardian behavior SHALL be represented separately and SHALL NOT be reported as native protection being armed.

#### Scenario: Native protection accepted
- **WHEN** Binance accepts the live protective stop, take-profit, or OCO-style protection order set
- **THEN** the gateway SHALL emit `protection_armed` with the accepted exchange order identifiers

#### Scenario: Native protection unsupported
- **WHEN** Binance live execution receives a protection intent that is unsupported for the configured account mode or symbol
- **THEN** the gateway SHALL return a normalized unsupported-capability or rejected result and SHALL NOT emit `protection_armed`

#### Scenario: Native protection placement fails after entry
- **WHEN** entry has filled but live protection placement fails or cannot be verified
- **THEN** the orchestrator SHALL emit a protection-failed or protection-missing event and apply the configured fail-safe policy before continuing live automation

#### Scenario: Local guardian is not native protection
- **WHEN** client-side WebSocket monitoring is active as a fallback or verification layer
- **THEN** the system SHALL identify it as local guardian state and SHALL NOT use it as proof that exchange-native protection is armed

