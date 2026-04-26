## 1. Run Identity

- [x] 1.1 Add tests proving one background optimization launch keeps the same `optimization_run_id` through runtime status and final report paths
- [x] 1.2 Stabilize `optimization_run_id` generation so execution reuses the launch id instead of regenerating during task parsing

## 2. Runtime Status Artifacts

- [x] 2.1 Add tests for `status.json` and `events.jsonl` fields, event ordering, and terminal status behavior
- [x] 2.2 Implement a runtime status/event writer used by optimization run startup, dataset preparation, sample execution, abort, and finish
- [x] 2.3 Update `scripts/check_optimization_status.py` to consume terminal status instead of treating an existing run directory as active

## 3. Dataset Guardrails

- [x] 3.1 Add tests for optimization dataset fail-fast behavior, dataset timeout/failure states, dependent sample skipping, and continued execution of runnable samples
- [x] 3.2 Add optimization-specific dataset preparation budget configuration and result states
- [x] 3.3 Propagate dataset failures/timeouts into structured skipped sample results without counting skipped samples as executed failures

## 4. Sample Guardrails

- [x] 4.1 Add tests for configurable sample wall-clock timeout, timeout result recording, and continued execution after a timed-out sample
- [x] 4.2 Add sample timeout configuration with a default of 60 seconds
- [x] 4.3 Enforce per-sample timeout at the scheduler execution boundary and record `timed_out` separately from ordinary failures

## 5. Health Metrics And Early Termination

- [x] 5.1 Add tests for failure-rate abort, no-progress abort, runnable-ratio abort, and parallelism-collapse metric semantics
- [x] 5.2 Implement progress, failure-rate, runnable-ratio, expected-worker, running-worker, and parallelism-ratio calculations in runtime status
- [x] 5.3 Implement early termination rules with structured abort reasons and `abort_summary.json`

## 6. Artifact Compatibility

- [x] 6.1 Add tests for mixed succeeded/failed/timed-out/skipped/aborted runs preserving aggregate, ranking, manifest, and failure contracts
- [x] 6.2 Ensure final report generation preserves existing main contracts while including structured timeout, skipped, and abort reasons
- [x] 6.3 Run targeted automated tests and OpenSpec validation, then mark the change ready for archive if all tasks pass
