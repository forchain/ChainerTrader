# staged-live-auto-execution Specification

## Purpose
TBD - created by archiving change staged-realtime-auto-trading. Update Purpose after archive.
## Requirements
### Requirement: Realtime live tasks support staged automatic execution modes
The system SHALL support realtime live execution modes `manual_notify`, `small_live_auto`, and `full_live_auto`. Real automatic modes SHALL consume the same realtime closed-candle strategy operations as `manual_notify`, but route them through automatic execution semantics instead of manual recommendation semantics. `paper_auto` SHALL be rejected as unsupported.

#### Scenario: Paper auto mode is rejected
- **WHEN** a realtime live task is configured with `live_execution_mode` set to `paper_auto`
- **THEN** the system SHALL reject the task configuration as unsupported
- **THEN** the system MUST NOT simulate execution and MUST NOT call exchange order placement APIs

#### Scenario: Small live auto mode receives a strategy entry operation
- **WHEN** a realtime live task is configured with `live_execution_mode` set to `small_live_auto` and a closed-candle strategy execution produces an entry operation
- **THEN** the system SHALL route the operation through real-order validation, capped sizing, and the configured execution gateway
- **THEN** the system SHALL place a real order only when every configured safety gate passes

#### Scenario: Full live auto mode receives a strategy entry operation
- **WHEN** a realtime live task is configured with `live_execution_mode` set to `full_live_auto` and a closed-candle strategy execution produces an entry operation
- **THEN** the system SHALL route the operation through real-order validation, configured full sizing, and the configured execution gateway
- **THEN** the system SHALL place a real order only when every configured safety gate passes

### Requirement: Staged automatic execution emits structured execution outcomes
The system SHALL produce a structured execution outcome for every automatic realtime operation that is placed, skipped, or failed. The outcome SHALL include task id, execution mode, market, operation type, signal time, signal price, requested notional or quantity, effective notional or quantity, result status, and skip or failure reason when applicable.

#### Scenario: Protection placement result is visible
- **WHEN** an automatic real-order mode opens a position that requires stop-loss or take-profit protection
- **THEN** the system SHALL emit or persist the protection placement result separately from the entry order result
- **THEN** the outcome SHALL identify whether protection was armed, skipped, failed, missing, or unsupported

#### Scenario: Real order is skipped
- **WHEN** an automatic real-order mode refuses to place an order because a safety gate fails
- **THEN** the system SHALL emit or persist an execution outcome with status indicating skipped execution
- **THEN** the outcome SHALL include the concrete skip reason

#### Scenario: Real order placement fails
- **WHEN** an automatic real-order mode calls an exchange order API and the exchange adapter returns an error or no accepted order result
- **THEN** the system SHALL emit or persist an execution outcome with status indicating failed execution
- **THEN** the outcome SHALL include the failure reason available from the adapter or runtime
