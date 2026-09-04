## Why

Parameter optimization runs can waste substantial time when a bad network, bad sample, or bad configuration causes the run to hang, drift across artifact directories, or continue after the result set is no longer useful. The execution layer now needs runtime guardrails so failures become fast, structured, and explainable instead of turning into stalled or misleading optimization runs.

## What Changes

- Generate and reuse a single stable `optimization_run_id` from launch through execution, status output, logs, and final reports.
- Add optimization-specific dataset preparation guardrails that prefer cache or database coverage and fail fast when limited backfill budgets are exceeded.
- Add a configurable per-sample wall-clock timeout, defaulting to 60 seconds, and record sample timeouts separately from ordinary execution failures.
- Add live runtime status artifacts: a current `status.json` snapshot and append-only `events.jsonl` lifecycle event stream.
- Add automatic termination rules for high failure rate, no progress, low runnable sample ratio, and sustained parallelism collapse.
- Preserve existing parameter search semantics, scoring semantics, and main report contracts while adding structured skipped, timed-out, and aborted reasons.

## Capabilities

### New Capabilities

- `backtest-optimization-run-identity`: Stable optimization run identity shared by background metadata, runtime directories, reports, and status artifacts.
- `backtest-optimization-guardrails`: Runtime guardrails for optimization dataset preparation, sample execution timeout, skip propagation, and early termination.
- `backtest-optimization-runtime-status`: Live optimization status snapshots and lifecycle event streams for monitoring and post-run analysis.

### Modified Capabilities

<!-- None. Existing archived specs do not currently define these optimization runtime contracts. -->

## Impact

- `src/trader/task/task_config.py`
- `src/trader/task/task_manager.py`
- `src/trader/task/dataset_resolver.py`
- `src/trader/task/backtrader_task.py`
- `src/trader/task/optimization_report.py`
- `scripts/run_optimization_background.py`
- `scripts/check_optimization_status.py`
- `tests/`
