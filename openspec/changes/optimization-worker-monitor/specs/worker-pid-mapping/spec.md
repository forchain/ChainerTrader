## ADDED Requirements

### Requirement: OS PID to Task ID Mapping
The execution framework must securely track the OS PID for each executing optimization sample without requiring complex IPC communication.

#### Scenario: A new backtest sample is started by a worker
- **WHEN** `run_backtest_sample` begins execution.
- **THEN** it must write a JSON file named `<pid>.json` in the `tmp/optimization_runs/<run_id>/workers/` directory containing the `task_id`.

#### Scenario: A backtest sample completes or crashes gracefully
- **WHEN** `run_backtest_sample` finishes execution (success or exception).
- **THEN** it must remove its `<pid>.json` mapping file from the directory before returning to the executor pool.
