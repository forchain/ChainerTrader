## MODIFIED Requirements

### Requirement: Real automatic order placement requires explicit staged mode selection
The system SHALL place live exchange orders only when the task execution mode explicitly selects `auto_trade`. `manual_notify` MUST NOT call exchange order placement APIs. Removed modes such as `small_live_auto`, `full_live_auto`, `staged_auto_trade`, and `paper_auto` SHALL be rejected as unsupported and MUST NOT simulate or place orders.

#### Scenario: Manual notify remains no-order
- **WHEN** a realtime live task is configured with `live_execution_mode` set to `manual_notify`
- **THEN** the system SHALL route strategy operations to manual notification behavior
- **THEN** the system MUST NOT call exchange order placement APIs

#### Scenario: Removed live execution mode is unsupported
- **WHEN** a live task is configured with a removed `live_execution_mode`
- **THEN** the system SHALL reject the configuration as unsupported
- **THEN** the system MUST NOT simulate execution and MUST NOT call exchange order placement APIs

#### Scenario: Unknown execution mode is configured
- **WHEN** a realtime live task is configured with an unsupported `live_execution_mode`
- **THEN** the system SHALL refuse real order placement
- **THEN** the system SHALL report the unsupported mode as a configuration error

### Requirement: Automatic execution validates operation price and quantity
The system SHALL validate operation price, calculated quantity, effective notional, protection quantity, protection price values, and exchange-side order constraints before placing any real order or native protection order.

#### Scenario: Operation price is invalid
- **WHEN** an automatic real-order mode receives an operation with missing, zero, negative, or non-finite price
- **THEN** the system MUST NOT place an exchange order
- **THEN** the system SHALL record a skipped execution outcome with an invalid price reason

#### Scenario: Calculated quantity is invalid
- **WHEN** an automatic real-order mode calculates a missing, zero, negative, or non-finite order quantity
- **THEN** the system MUST NOT place an exchange order
- **THEN** the system SHALL record a skipped execution outcome with an invalid quantity reason

#### Scenario: Protection price is invalid
- **WHEN** an automatic real-order mode prepares stop-loss or take-profit protection with a missing, zero, negative, non-finite, or side-invalid protection price
- **THEN** the system MUST NOT place the protection order
- **THEN** the system SHALL record a skipped, rejected, or failed protection outcome with the validation reason

#### Scenario: Exchange constraints reject the order size
- **WHEN** exchange metadata or adapter validation indicates the calculated quantity or notional fails exchange constraints
- **THEN** the system MUST NOT place an exchange order
- **THEN** the system SHALL record a skipped execution outcome with the exchange constraint reason

### Requirement: Automatic execution publishes dashboard-visible outcomes
The system SHALL make automatic execution outcomes visible to live monitoring consumers so operators can distinguish manual recommendations, skipped orders, failed orders, real submitted orders, and live protection state.

#### Scenario: Real order outcome appears in live monitor data
- **WHEN** `auto_trade` routes an operation to a real exchange order
- **THEN** the live monitor data SHALL identify whether the order was submitted, skipped, or failed
- **THEN** the live monitor data SHALL include the effective notional or quantity and any skip or failure reason

#### Scenario: Live protection outcome appears in live monitor data
- **WHEN** `auto_trade` routes stop-loss or take-profit protection to the live gateway
- **THEN** the live monitor data SHALL identify whether protection is armed, rejected, missing, failed, replaced, or canceled
- **THEN** the live monitor data SHALL include the relevant protection order identifiers when native protection is armed

## REMOVED Requirements

### Requirement: Paper auto remains no-order
**Reason**: `paper_auto` is no longer a supported realtime execution mode. It should be rejected before routing, not handled as a no-order simulation mode.

**Migration**: Use `manual_notify` for no-order realtime operation and Backtrader for test execution.
