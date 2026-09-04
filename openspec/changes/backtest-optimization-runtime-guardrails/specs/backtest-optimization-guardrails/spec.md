## ADDED Requirements

### Requirement: Optimization dataset preparation fails fast
Optimization dataset preparation SHALL use an optimization-specific budget for missing data backfill and SHALL NOT inherit long retry behavior intended for ordinary data synchronization.

#### Scenario: Dataset backfill exceeds optimization budget
- **WHEN** a dataset needed by optimization samples cannot be prepared within the configured optimization budget
- **THEN** the system SHALL mark the dataset job as `failed` or `timed_out`
- **AND** the system SHALL skip samples that depend on that dataset
- **AND** the system SHALL continue running samples whose datasets are available

#### Scenario: Dataset backfill succeeds within optimization budget
- **WHEN** a missing dataset gap is resolved within the configured optimization budget
- **THEN** the system SHALL mark the dataset job as `succeeded`
- **AND** dependent samples SHALL remain runnable

### Requirement: Dataset-dependent skipped samples are structured
Samples not executed because of dataset preparation failure SHALL be recorded as skipped with a structured reason that distinguishes them from executed sample failures.

#### Scenario: Sample skipped because dataset failed
- **WHEN** a dataset job fails or times out before a dependent sample starts
- **THEN** the dependent sample SHALL be recorded as `skipped`
- **AND** the reason SHALL identify dataset preparation failure or timeout
- **AND** skipped samples SHALL NOT be counted as samples that executed and failed

### Requirement: Sample execution has a configurable timeout
Each optimization sample SHALL obey a configurable wall-clock execution timeout with a default value of 60 seconds.

#### Scenario: Sample exceeds timeout
- **WHEN** an optimization sample runs longer than the configured sample timeout
- **THEN** the system SHALL terminate or cancel that sample execution unit
- **AND** the sample SHALL be recorded as `timed_out`
- **AND** later runnable samples SHALL continue executing

#### Scenario: Sample finishes before timeout
- **WHEN** an optimization sample completes before the configured sample timeout
- **THEN** the system SHALL record the sample as `succeeded` or `failed` according to its execution result
- **AND** the system SHALL NOT record it as `timed_out`

### Requirement: Unhealthy optimization runs abort early
An optimization run SHALL automatically abort when configured health rules determine that continuing the run is not useful.

#### Scenario: Failure rate threshold aborts run
- **WHEN** completed samples meet the configured minimum observation window
- **AND** the failure rate exceeds the configured maximum failure rate
- **THEN** the system SHALL abort the optimization run
- **AND** the system SHALL record an abort reason for high failure rate

#### Scenario: No-progress timeout aborts run
- **WHEN** runnable dataset or sample work remains
- **AND** no dataset or sample lifecycle event has completed within the configured no-progress timeout
- **THEN** the system SHALL abort the optimization run
- **AND** the system SHALL record an abort reason for no progress

#### Scenario: Runnable ratio threshold aborts run
- **WHEN** the ratio of runnable samples to total samples drops below the configured minimum runnable ratio
- **THEN** the system SHALL abort the optimization run
- **AND** the system SHALL record an abort reason for insufficient runnable samples

#### Scenario: Parallelism collapse aborts run
- **WHEN** many runnable samples remain
- **AND** parallelism ratio stays below the configured threshold
- **AND** worker CPU efficiency stays below the configured threshold
- **AND** there is no effective progress
- **THEN** the system SHALL abort the optimization run
- **AND** the system SHALL record an abort reason for parallelism collapse

### Requirement: Aborted runs produce structured abort summaries
When an optimization run aborts early, the system SHALL produce a structured abort summary that identifies why and where the run stopped.

#### Scenario: Abort summary is written
- **WHEN** an optimization run aborts
- **THEN** the system SHALL write an abort summary containing the abort reason, stage, completed sample count, and relevant health metric values
- **AND** final report aggregation SHALL preserve partial successful results when available
