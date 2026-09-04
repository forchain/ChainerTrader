## Context

Parameter optimization now has a controlled parallel execution layer, but the runtime still lacks hard operational boundaries. A single optimization run can drift across multiple generated `optimization_run_id` values, spend too long attempting dataset backfills that are inappropriate for optimization, allow slow samples to occupy workers indefinitely, and leave users without a reliable view of whether the run is healthy.

This change treats optimization as a bounded batch workflow. The system should produce enough trustworthy results quickly, record why work did not run, and stop once continuing is unlikely to add value.

## Goals / Non-Goals

**Goals:**

- Preserve one stable `optimization_run_id` across background metadata, runtime directories, status artifacts, and reports.
- Apply optimization-specific dataset preparation budgets that fail fast instead of inheriting slow data-sync retry semantics.
- Enforce a configurable per-sample wall-clock timeout with a default of 60 seconds.
- Emit live `status.json` and append-only `events.jsonl` artifacts for monitoring and replay.
- Abort unhealthy runs when configured failure, liveness, runnable-ratio, or parallelism-collapse rules trigger.
- Keep existing search, scoring, and report contracts compatible while adding structured skip, timeout, and abort reasons.

**Non-Goals:**

- Do not change parameter expansion, ranking, scoring, or strategy performance calculations.
- Do not convert local execution into distributed scheduling.
- Do not redesign the existing web/admin UI.
- Do not make optimization runs responsible for exhaustive historical data synchronization.
- Do not require CPU metrics to be available on every platform before the core guardrails can operate.

## Decisions

### Decision 1: Generate run identity once and pass it explicitly

`optimization_run_id` will be generated before execution begins and passed through the run context, task execution, status writer, and report writer. Execution code must not generate a replacement run id after background launch.

Alternatives considered:

- Generate ids lazily in the task parser. This is the current source of drift when the same task file is parsed multiple times.
- Derive ids from task filenames. This is stable but loses uniqueness across repeated launches of the same task.

The explicit context approach keeps repeated launches unique while making every artifact from one launch correlate cleanly.

### Decision 2: Split optimization dataset policy from data-sync policy

Optimization dataset preparation will use a small request/backfill budget. Cache and database coverage are preferred; missing coverage beyond the optimization budget marks the dataset job as `failed` or `timed_out` and skips dependent samples.

Alternatives considered:

- Reuse normal resolver retries. This favors completeness over optimization throughput and can stall a batch run.
- Disable all backfill attempts. This is fast but too brittle when a tiny gap can be filled cheaply.

The bounded policy gives optimization a chance to repair small gaps without letting network problems dominate the run.

### Decision 3: Treat sample timeout as a first-class result

Each sample will have a wall-clock timeout, defaulting to 60 seconds. Timeout results will be recorded as `timed_out`, not merged into ordinary `failed`, and execution will continue for later samples.

Alternatives considered:

- Only log slow samples after completion. This does not protect worker capacity.
- Use strategy-internal timeout checks. This depends on strategy behavior and does not provide a hard execution boundary.

The scheduler-level timeout creates a clear batch contract: one pathological sample cannot consume the entire run.

### Decision 4: Emit both snapshot and event stream artifacts

The runtime will maintain:

- `status.json` for the latest view of run identity, stage, progress counters, health, liveness, and abort reason.
- `events.jsonl` for lifecycle events including run start/finish, dataset transitions, sample transitions, skips, timeouts, and aborts.

Snapshots are easy for status checks to consume; events are better for replay and postmortem analysis.

### Decision 5: Define parallelism relative to runnable work

`expected_workers = min(configured_workers, remaining_runnable_samples)` during sample execution. `parallelism_ratio = running_workers / expected_workers` when expected workers is non-zero.

This avoids false alarms near the natural tail of a run or when the runnable sample set is smaller than the configured worker pool.

### Decision 6: Automatic termination uses multiple signals

The scheduler will abort when any configured rule determines the run is no longer useful:

- High failure rate after a minimum completed sample window.
- No dataset or sample completion event for longer than the no-progress timeout.
- Runnable sample ratio below the configured minimum.
- Sustained parallelism collapse while runnable work remains and CPU efficiency is low.

Single-signal aborts are intentionally limited to clear, configured thresholds. Parallelism collapse must account for remaining runnable samples and progress to avoid confusing a normal tail phase with a broken run.

## Risks / Trade-offs

- Fail-fast dataset policy can abandon data that might have succeeded with longer retries -> keep the policy configurable per optimization task and record skipped dependencies explicitly.
- Hard sample timeouts require genuinely terminable execution units -> enforce timeout at the scheduler/future/process boundary and record if termination fails.
- CPU efficiency metrics may be unavailable or noisy -> make CPU-dependent collapse checks degrade safely and avoid blocking core status output.
- More status artifacts increase write frequency -> write compact JSON, update atomically, and append JSONL events only at lifecycle transitions.
- Existing status scripts may assume directory existence means running -> update them to read terminal status and final artifacts instead of inferring solely from process metadata.

## Migration Plan

1. Add configuration fields and defaults for optimization runtime budgets, sample timeout, liveness timeout, failure-rate threshold, runnable-ratio threshold, and parallelism-collapse checks.
2. Stabilize run identity propagation in background launch and execution entry points.
3. Add runtime status/event writer models and use them from dataset preparation, sample execution, and finalization.
4. Add dataset fail-fast and sample timeout handling with structured result reasons.
5. Add early termination checks and abort summary output.
6. Update the status check script to consume `status.json` and terminal run states.
7. Add automated tests for identity stability, guardrail behavior, status output, abort rules, and mixed-result report compatibility.
