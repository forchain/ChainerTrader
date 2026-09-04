## ADDED Requirements

### Requirement: Realtime live tasks support staged automatic execution modes
The system SHALL support staged realtime live execution modes in addition to `manual_notify`: `paper_auto`, `small_live_auto`, and `full_live_auto`. These modes SHALL consume the same realtime closed-candle strategy operations as `manual_notify`, but route them through automatic execution semantics instead of manual recommendation semantics.

#### Scenario: Paper auto mode receives a strategy entry operation
- **WHEN** a realtime live task is configured with `live_execution_mode` set to `paper_auto` and a closed-candle strategy execution produces an entry operation
- **THEN** the system SHALL create a simulated execution for that operation
- **THEN** the system MUST NOT call exchange order placement APIs

#### Scenario: Small live auto mode receives a strategy entry operation
- **WHEN** a realtime live task is configured with `live_execution_mode` set to `small_live_auto` and a closed-candle strategy execution produces an entry operation
- **THEN** the system SHALL route the operation through real-order validation and capped sizing
- **THEN** the system SHALL place a real order only when every configured safety gate passes

#### Scenario: Full live auto mode receives a strategy entry operation
- **WHEN** a realtime live task is configured with `live_execution_mode` set to `full_live_auto` and a closed-candle strategy execution produces an entry operation
- **THEN** the system SHALL route the operation through real-order validation and configured full sizing
- **THEN** the system SHALL place a real order only when every configured safety gate passes

### Requirement: Paper auto uses configured local account state
The system SHALL initialize `paper_auto` account state from task configuration, using configured `free` cash when available and `manual_start_position` as the starting position. The system MUST NOT require exchange account balance reads to simulate paper executions.

#### Scenario: Paper auto starts with configured cash and no position
- **WHEN** a realtime live task is configured with `paper_auto`, `free` is positive, and `manual_start_position` is zero
- **THEN** the paper account state SHALL start with that configured cash
- **THEN** the paper account state SHALL start with no position

#### Scenario: Paper auto starts with configured position
- **WHEN** a realtime live task is configured with `paper_auto` and `manual_start_position` is non-zero
- **THEN** the paper account state SHALL include that starting position before processing new strategy operations
- **THEN** exits SHALL be simulated against that local starting position rather than exchange balances

### Requirement: Paper auto supports simulated long and short positions
The system SHALL allow `paper_auto` to simulate long and short strategy operations without requiring real margin, futures, or borrowing support.

#### Scenario: Paper auto simulates a long entry
- **WHEN** `paper_auto` processes a `BUY` or `LONG` operation with a valid price
- **THEN** the system SHALL decrease paper cash by the simulated notional amount
- **THEN** the system SHALL increase paper position by the simulated quantity

#### Scenario: Paper auto simulates a short entry
- **WHEN** `paper_auto` processes a `SHORT` operation with a valid price
- **THEN** the system SHALL create or increase a simulated short position
- **THEN** the system MUST NOT require `live_short_execution` to be enabled

#### Scenario: Paper auto simulates an exit
- **WHEN** `paper_auto` processes a `SELL` or `CLOSE` operation with an open simulated position
- **THEN** the system SHALL reduce or close the simulated position
- **THEN** the system SHALL update paper cash according to the simulated exit price and quantity

### Requirement: Staged automatic execution emits structured execution outcomes
The system SHALL produce a structured execution outcome for every automatic realtime operation that is simulated, placed, skipped, or failed. The outcome SHALL include task id, execution mode, market, operation type, signal time, signal price, requested notional or quantity, effective notional or quantity, result status, and skip or failure reason when applicable.

#### Scenario: Paper execution outcome is recorded
- **WHEN** `paper_auto` simulates an operation
- **THEN** the system SHALL emit or persist an execution outcome with status indicating simulated execution
- **THEN** the outcome SHALL identify the originating strategy operation

#### Scenario: Real order is skipped
- **WHEN** an automatic real-order mode refuses to place an order because a safety gate fails
- **THEN** the system SHALL emit or persist an execution outcome with status indicating skipped execution
- **THEN** the outcome SHALL include the concrete skip reason

#### Scenario: Real order placement fails
- **WHEN** an automatic real-order mode calls an exchange order API and the exchange adapter returns an error or no accepted order result
- **THEN** the system SHALL emit or persist an execution outcome with status indicating failed execution
- **THEN** the outcome SHALL include the failure reason available from the adapter or runtime
