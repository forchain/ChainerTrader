# Live Task Restart Recovery Design

## Context

Live tasks are long-running in-memory task objects. After a server process restart, the original Python objects and coroutines are gone, so recovery cannot mean resuming the exact same process state. Recovery means rebuilding equivalent task runtime from persisted task state and configuration, then starting those tasks again under the same persisted task identity.

The observed bug is that a live task created by a user is `RUNNING` before restart, but becomes `DONE` after restart. The recovery path must not merely flip database state. It must enqueue the recovered task into `TaskManager` so the live trading loop is actually running again.

## Goals

- Restarting the server does not permanently stop persisted `RUNNING` live tasks.
- Recovered tasks reuse the original persisted `task_id` when possible.
- Recovered tasks preserve the original `user_id`, `run_id`, strategy, symbol, interval, live execution mode, and live margin/short controls.
- API startup is not blocked by restoring every running task.
- Recovery is bounded so a large backlog, for example 10,000 running tasks, does not start with unbounded parallelism.

## Non-Goals

- Recovering in-memory-only strategy internals that were never persisted.
- Replaying every missed realtime tick while the server was down.
- Introducing a distributed scheduler.
- Changing strategy-specific behavior to paper over framework recovery defects.

## Recovery Semantics

Recovery reconstructs a `TaskConfig` from the persisted task row and starts a new runtime task object from that configuration. This is a restart of the runtime under the same task identity, not a brand-new user task.

The recovery path should:

1. Load persisted task rows whose state is `RUNNING`.
2. Parse each row's `config_json`.
3. Set the parsed `TaskConfig.id` to the persisted row task ID.
4. Restore persisted identity fields such as `user_id` and `run_id`.
5. Enqueue the task for actual startup through `TaskManager`.

If exact reuse is not possible because persisted data is incomplete, the acceptable fallback is to start from the same task configuration. The fallback should still avoid generating a user-visible new task ID when the old task ID is known.

## Startup Model

The API server should become available before all recovery work completes.

Startup should:

1. Bootstrap database and exchange dependencies.
2. Start the normal API service.
3. Run a background recovery coordinator.
4. Let the coordinator scan persisted `RUNNING` tasks incrementally or in bounded batches.
5. Let recovery workers start queued tasks with bounded concurrency.

This avoids coupling server availability to the number of live tasks that existed before restart. Both scanning and task startup must avoid requiring all recoverable rows to be processed before the API is considered ready.

## Recovery Queue

Recovery should be asynchronous and concurrency-bounded.

The first implementation can keep the queue in process memory because the source of truth is still the database rows marked `RUNNING`. If the process crashes again during recovery, the next process scan sees the same rows and retries.

Recommended behavior:

- Use an internal async queue or batched worker loop.
- Use a configurable concurrency limit with a conservative default.
- Each queued item contains the recovered `TaskConfig`.
- Each worker starts tasks through the same framework path used by normal task creation.
- Do not call a path that marks tasks `DONE` after the startup coroutine returns unless the task actually completed.

## State Handling

For recovered long-running live tasks:

- Keep state as `RUNNING` when the task is enqueued or successfully started.
- Do not mark a recovered task `DONE` just because recovery dispatch finished.
- If task startup fails before the task begins running, log the error with task ID and user ID.

The current state model may not have a dedicated `FAILED` or `RECOVERING` state. If adding one is too large for this change, the first implementation should keep the row `RUNNING` and provide clear logs for failed recovery. A follow-up can add explicit recovery status if the UI needs to show partial recovery progress.

## Configuration Persistence

The recovery path depends on `config_json`, so `config_json` must preserve live runtime controls. Persisted live task config must round-trip through `parse_task_config()` without losing:

- `live_execution_mode`
- `live_trade_max_notional`
- `live_short_execution`
- `live_margin_borrow_block_policy`
- `live_margin_borrow_precheck`
- `live_margin_auto_repay_max_total`
- `live_margin_auto_repay_max_per_asset`
- `live_margin_auto_repay_min_amount`
- `live_margin_auto_repay_excluded_assets`
- `strategy_params`
- `user_id`
- `run_id`

This is required because losing live execution, sizing, or short/margin settings can make a recovered live task run with different semantics or exit early.

## Testing

Automated tests should cover:

- `BaseTask` persisted `config_json` round-trips live runtime controls through `parse_task_config()`.
- Recovery reuses persisted task IDs instead of generating new task IDs.
- Server async startup does not use nested event loops.
- Startup can schedule recovery work without waiting for all recovered tasks to finish.
- Startup does not wait for a large recovery scan or recovery backlog to finish before becoming ready.
- Recovery honors the configured concurrency bound and does not start an unbounded number of tasks at once.
- A recovered live task remains `RUNNING` when its runtime task is long-lived.

Manual or smoke verification should cover:

- Create a live task from the UI.
- Confirm it is running.
- Restart the server.
- Confirm the API becomes available quickly.
- Refresh UI and confirm the same task ID is still running.

## Risks

- Existing historical task rows may have incomplete `config_json`; recovery should log those rows instead of crashing startup.
- Starting many real live tasks can trigger exchange rate limits; bounded concurrency is required.
- If recovery fails but state remains `RUNNING`, UI can temporarily overstate task health. A dedicated recovery failure state can be added later if needed.
