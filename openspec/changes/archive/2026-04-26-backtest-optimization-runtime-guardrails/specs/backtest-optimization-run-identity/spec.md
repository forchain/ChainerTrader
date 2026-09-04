## ADDED Requirements

### Requirement: Stable optimization run identity
An optimization run SHALL generate one `optimization_run_id` for a launch and reuse it across background metadata, runtime directories, status artifacts, single-sample reports, aggregate reports, and failure records.

#### Scenario: Background launch uses one run identity
- **WHEN** a user starts a parameter optimization through the background launcher
- **THEN** the system SHALL generate exactly one `optimization_run_id` for that launch
- **AND** the execution phase SHALL reuse that same identifier
- **AND** the run directory, status artifacts, logs, and reports SHALL be associated with that identifier

#### Scenario: Repeated task parsing does not replace run identity
- **WHEN** the same optimization task definition is parsed more than once during one launch
- **THEN** the system SHALL preserve the launch `optimization_run_id`
- **AND** the system SHALL NOT generate a replacement run id during execution

### Requirement: Run identity is visible in runtime status
Runtime status artifacts SHALL include the active `optimization_run_id` so monitoring tools can correlate live state with final reports.

#### Scenario: Status snapshot contains run identity
- **WHEN** an optimization run writes `status.json`
- **THEN** the snapshot SHALL include `run_id`
- **AND** `run_id` SHALL equal the `optimization_run_id` used by the final report artifacts
