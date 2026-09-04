## ADDED Requirements

### Requirement: Optimization run status snapshot
An optimization run SHALL maintain a live `status.json` snapshot with run identity, stage, progress counters, liveness information, health metrics, and terminal state.

#### Scenario: User checks status during sample execution
- **WHEN** a user checks an optimization run while samples are executing
- **THEN** `status.json` SHALL show the current stage
- **AND** it SHALL show dataset counters, sample counters, failure rate, parallelism ratio, and last progress time

#### Scenario: Status shows terminal completion
- **WHEN** an optimization run finishes or aborts
- **THEN** `status.json` SHALL show a terminal stage
- **AND** status check tooling SHALL NOT report the run as still active solely because the run directory exists

### Requirement: Optimization run event stream
An optimization run SHALL append lifecycle events to `events.jsonl` so the run can be replayed after completion.

#### Scenario: Run lifecycle events are emitted
- **WHEN** an optimization run starts, executes dataset jobs, executes samples, and finishes
- **THEN** `events.jsonl` SHALL include events for run start, dataset job transitions, sample transitions, and run finish
- **AND** each event SHALL include the run id, timestamp, event type, and relevant entity identifiers

#### Scenario: Timeout and skipped events are distinct
- **WHEN** dataset jobs or samples time out or samples are skipped
- **THEN** `events.jsonl` SHALL record timeout and skipped events with distinct event types
- **AND** these events SHALL include structured reasons

### Requirement: Health metrics use explicit parallelism definitions
Runtime status SHALL define expected workers and parallelism ratio relative to remaining runnable sample work.

#### Scenario: Parallelism ratio during active sample execution
- **WHEN** runnable samples remain during sample execution
- **THEN** `expected_workers` SHALL equal the smaller of configured workers and remaining runnable samples
- **AND** `parallelism_ratio` SHALL equal running workers divided by expected workers when expected workers is greater than zero

#### Scenario: Tail phase does not imply unhealthy parallelism
- **WHEN** fewer runnable samples remain than configured workers near the end of a run
- **THEN** the system SHALL calculate expected workers from remaining runnable samples
- **AND** the system SHALL NOT mark the run unhealthy solely because configured workers are not all occupied
