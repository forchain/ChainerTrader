## ADDED Requirements

### Requirement: Real automatic order placement requires explicit staged mode selection
The system SHALL place realtime live exchange orders only when the task execution mode explicitly selects a real automatic mode. `manual_notify` and `paper_auto` MUST NOT call exchange order placement APIs.

#### Scenario: Manual notify remains no-order
- **WHEN** a realtime live task is configured with `live_execution_mode` set to `manual_notify`
- **THEN** the system SHALL route strategy operations to manual notification behavior
- **THEN** the system MUST NOT call exchange order placement APIs

#### Scenario: Paper auto remains no-order
- **WHEN** a realtime live task is configured with `live_execution_mode` set to `paper_auto`
- **THEN** the system SHALL route strategy operations to simulated execution behavior
- **THEN** the system MUST NOT call exchange order placement APIs

#### Scenario: Unknown execution mode is configured
- **WHEN** a realtime live task is configured with an unsupported `live_execution_mode`
- **THEN** the system SHALL refuse real order placement
- **THEN** the system SHALL report the unsupported mode as a configuration error

### Requirement: Small live auto caps every real order by fixed notional
The system SHALL require `small_live_auto` tasks to configure a positive `live_trade_max_notional`. Every real order placed by `small_live_auto` MUST have an effective notional value less than or equal to `live_trade_max_notional`.

#### Scenario: Small live max notional is configured
- **WHEN** `small_live_auto` processes a valid operation and `live_trade_max_notional` is positive
- **THEN** the system SHALL calculate order quantity from no more than `live_trade_max_notional`
- **THEN** the system SHALL place the order only if the calculated quantity passes validation

#### Scenario: Small live max notional is missing
- **WHEN** `small_live_auto` processes a valid operation and `live_trade_max_notional` is missing, zero, or negative
- **THEN** the system MUST NOT place an exchange order
- **THEN** the system SHALL record a skipped execution outcome explaining that the small-live notional cap is missing or invalid

#### Scenario: Strategy requests larger notional than small-live cap
- **WHEN** `small_live_auto` receives an operation whose task or strategy sizing would exceed `live_trade_max_notional`
- **THEN** the system SHALL reduce the effective order notional to `live_trade_max_notional`
- **THEN** the system MUST NOT place an order above the configured cap

### Requirement: Automatic execution validates operation price and quantity
The system SHALL validate operation price, calculated quantity, effective notional, and exchange-side order constraints before placing any real order.

#### Scenario: Operation price is invalid
- **WHEN** an automatic real-order mode receives an operation with missing, zero, negative, or non-finite price
- **THEN** the system MUST NOT place an exchange order
- **THEN** the system SHALL record a skipped execution outcome with an invalid price reason

#### Scenario: Calculated quantity is invalid
- **WHEN** an automatic real-order mode calculates a missing, zero, negative, or non-finite order quantity
- **THEN** the system MUST NOT place an exchange order
- **THEN** the system SHALL record a skipped execution outcome with an invalid quantity reason

#### Scenario: Exchange constraints reject the order size
- **WHEN** exchange metadata or adapter validation indicates the calculated quantity or notional fails exchange constraints
- **THEN** the system MUST NOT place an exchange order
- **THEN** the system SHALL record a skipped execution outcome with the exchange constraint reason

### Requirement: Automatic execution prevents duplicate operation routing
The system SHALL prevent the same realtime strategy operation from being simulated or sent to the exchange more than once. Operation identity SHALL prefer a stable signal event id when available and otherwise use a deterministic fallback based on operation side, signal time, and signal price.

#### Scenario: Replayed operation has the same signal event id
- **WHEN** realtime strategy execution emits an operation whose signal event id has already been routed
- **THEN** the system MUST NOT simulate or place the operation again
- **THEN** the system SHALL record or expose that the operation was skipped as a duplicate

#### Scenario: Replayed operation has no signal event id
- **WHEN** realtime strategy execution emits an operation without a signal event id but with the same side, signal time, and signal price as an already routed operation
- **THEN** the system MUST NOT simulate or place the operation again
- **THEN** the system SHALL record or expose that the operation was skipped as a duplicate

### Requirement: Automatic real orders check account-side prerequisites
The system SHALL check the account-side prerequisites needed for a real order before placement. Long-side orders SHALL validate available quote balance when required by the selected account type. Exit orders SHALL validate that a known position or balance exists before selling or closing.

#### Scenario: Long order has insufficient quote balance
- **WHEN** an automatic real-order mode prepares a long-side order and the selected account type does not have enough available quote balance for the effective notional
- **THEN** the system MUST NOT place the exchange order
- **THEN** the system SHALL record a skipped execution outcome with an insufficient balance reason

#### Scenario: Exit order has no known position
- **WHEN** an automatic real-order mode prepares a sell or close operation and the runtime has no known position or available base balance to exit
- **THEN** the system MUST NOT place the exchange order
- **THEN** the system SHALL record a skipped execution outcome with an empty or unknown position reason

### Requirement: Automatic execution publishes dashboard-visible outcomes
The system SHALL make automatic execution outcomes visible to live monitoring consumers so operators can distinguish manual recommendations, paper executions, skipped orders, failed orders, and real submitted orders.

#### Scenario: Paper execution appears in live monitor data
- **WHEN** `paper_auto` simulates an operation
- **THEN** the live monitor data SHALL identify the event as a paper execution
- **THEN** the live monitor data SHALL include the effective simulated notional or quantity

#### Scenario: Real order outcome appears in live monitor data
- **WHEN** `small_live_auto` or `full_live_auto` routes an operation to a real exchange order
- **THEN** the live monitor data SHALL identify whether the order was submitted, skipped, or failed
- **THEN** the live monitor data SHALL include the effective notional or quantity and any skip or failure reason
