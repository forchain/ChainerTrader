## ADDED Requirements

### Requirement: Manual notify remains the no-order realtime safety baseline
When staged automatic realtime execution modes are available, `manual_notify` SHALL remain a recommendation-only mode. The system MUST NOT call exchange order placement APIs for `manual_notify` operations, even if the same task configuration format also supports `paper_auto`, `small_live_auto`, or `full_live_auto`.

#### Scenario: Manual notify receives a long signal after staged modes are added
- **WHEN** a realtime live task is configured with `live_execution_mode` set to `manual_notify` and the strategy emits a `BUY` or `LONG` operation
- **THEN** the system SHALL generate manual notification behavior according to the existing manual live notification requirements
- **THEN** the system MUST NOT simulate the operation as `paper_auto`
- **THEN** the system MUST NOT place an exchange order

#### Scenario: Manual notify receives a short signal after staged modes are added
- **WHEN** a realtime live task is configured with `live_execution_mode` set to `manual_notify` and the strategy emits a `SHORT` operation
- **THEN** the system SHALL generate manual notification behavior according to the existing manual live notification requirements
- **THEN** the system MUST NOT route the operation through cross-margin short execution
- **THEN** the system MUST NOT place an exchange order
