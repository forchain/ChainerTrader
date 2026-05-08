## ADDED Requirements

### Requirement: Real short execution is disabled unless cross margin is explicitly selected
The system SHALL disable real short order placement by default. Realtime real automatic modes SHALL place a real `SHORT` order only when the task explicitly configures `live_short_execution` as `margin_cross`.

#### Scenario: Short execution is disabled
- **WHEN** `small_live_auto` or `full_live_auto` processes a `SHORT` operation and `live_short_execution` is missing or set to `disabled`
- **THEN** the system MUST NOT place an exchange order
- **THEN** the system SHALL record a skipped execution outcome explaining that real short execution is disabled

#### Scenario: Cross margin short execution is enabled
- **WHEN** `small_live_auto` or `full_live_auto` processes a `SHORT` operation and `live_short_execution` is set to `margin_cross`
- **THEN** the system SHALL route the operation through Binance cross-margin order validation
- **THEN** the system SHALL place a cross-margin short order only when every cross-margin safety gate passes

### Requirement: Cross margin short execution uses the Binance margin order path
When `live_short_execution` is `margin_cross`, the system SHALL use the Binance cross-margin order API path for real short-side execution. The system MUST NOT silently map a real short operation to a spot sell order.

#### Scenario: Short operation reaches real order placement
- **WHEN** a cross-margin-enabled task places a real `SHORT` order
- **THEN** the order SHALL be routed through the Binance margin adapter
- **THEN** the order MUST NOT be routed through the Binance spot order adapter

#### Scenario: Spot account receives short operation
- **WHEN** a task is using spot-only execution context and receives a `SHORT` operation
- **THEN** the system MUST NOT map that operation to a spot `SELL`
- **THEN** the system SHALL record a skipped execution outcome indicating that spot short is unsupported

### Requirement: Cross margin short execution validates margin readiness
Before placing a real cross-margin short order, the system SHALL validate that margin execution is configured and usable for the exchange account. If margin readiness cannot be confirmed, the system MUST NOT place the short order.

#### Scenario: Margin adapter is unavailable
- **WHEN** a cross-margin-enabled task receives a `SHORT` operation but the margin adapter is unavailable or uninitialized
- **THEN** the system MUST NOT place the exchange order
- **THEN** the system SHALL record a skipped execution outcome with a margin adapter unavailable reason

#### Scenario: Margin account readiness check fails
- **WHEN** a cross-margin-enabled task receives a `SHORT` operation but the margin account readiness check fails
- **THEN** the system MUST NOT place the exchange order
- **THEN** the system SHALL record a skipped execution outcome with the readiness failure reason

### Requirement: Cross margin short execution respects staged sizing
Cross-margin short orders SHALL use the same staged sizing rules as other real automatic orders. `small_live_auto` cross-margin shorts MUST be capped by `live_trade_max_notional`; `full_live_auto` cross-margin shorts SHALL use configured full sizing after validation.

#### Scenario: Small live cross-margin short is capped
- **WHEN** `small_live_auto` places a cross-margin `SHORT` order
- **THEN** the effective order notional MUST be less than or equal to `live_trade_max_notional`
- **THEN** the system SHALL record the capped effective notional in the execution outcome

#### Scenario: Full live cross-margin short uses configured sizing
- **WHEN** `full_live_auto` places a cross-margin `SHORT` order
- **THEN** the effective order quantity SHALL be based on the configured full sizing policy
- **THEN** the order MUST still pass margin readiness, price, quantity, duplicate, and account-side validation before placement

### Requirement: Cross margin short exits close known short exposure
When a cross-margin-enabled task processes a short-side exit such as `CLOSE`, the system SHALL route the exit through the margin order path only when it has known short exposure or sufficient account information to determine the close quantity.

#### Scenario: Close has known short exposure
- **WHEN** a cross-margin-enabled task processes `CLOSE` and the runtime has known short exposure for the market
- **THEN** the system SHALL calculate a close quantity from that known exposure
- **THEN** the system SHALL route the close order through the Binance margin adapter after validation

#### Scenario: Close has unknown short exposure
- **WHEN** a cross-margin-enabled task processes `CLOSE` and the runtime cannot determine the short exposure to close
- **THEN** the system MUST NOT place a margin close order
- **THEN** the system SHALL record a skipped execution outcome with an unknown short exposure reason
