# Live Task Balance Preflight Design

## Status
Approved for implementation by user instruction.

## Date
2026-07-01

## Context
ChainerTrader can start a task set containing multiple live trading tasks. The previous account fund reservation model treated configured task capital as reserved account capacity. In a task set with two live tasks configured for 100 USDT each, the startup path required 200 USDT of account capacity even though the intended runtime model lets strategies take turns using the same account balance.

That behavior does not match the product intent. Task capital is a per-task sizing input, not an account-level lock. The startup requirement should be that every individual live task can be supported by the relevant exchange account if it needs to trade. It should not require the exchange account to cover the sum of every live task's configured capital.

Backtests and data tasks do not have an exchange account funding constraint and should continue to behave as if simulated capital is available from configuration.

## Goal
Replace startup-time account-level fund reservation for live tasks with a read-only per-task balance preflight:

- each live task is checked independently
- tasks are checked in configured order
- the first insufficient task fails the whole startup batch before any task starts
- task amounts are not accumulated across tasks
- the check uses the account surface required by each task
- failure logs explain exactly which task failed and why

## Non-Goals
- Reserving or locking exchange funds across concurrently running tasks.
- Summing all configured task capitals and requiring the exchange account to cover the total.
- Changing backtest sizing semantics.
- Changing strategy sizing or signal generation.
- Changing `TRADER_LEVERAGE_RATIO`; leverage ratio remains an exposure cap for leveraged and future futures paths, independent of task sizing.
- Building a full portfolio allocator or runtime capital scheduler.

## Recommended Approach
Add a dedicated live task balance preflight in `TaskManager` startup before task creation. This preflight replaces the existing startup fund reservation behavior for live tasks.

The preflight should be read-only. It should inspect each `TRADER` task that runs in a real live execution mode, resolve the exchange/account surface for that task, compute the task's required startup notional, read the account capacity from the resolved exchange, and fail fast if the task requirement exceeds that single account capacity.

This matches the requested semantics:

- Task A needs 100 USDT, Task B needs 100 USDT, account has 100 USDT: startup passes.
- Task A needs 1000 USDT, Task B needs 10000 USDT, account has 5000 USDT: Task A passes, Task B fails, and the batch exits before starting tasks.
- A long-only spot task checks the spot account.
- A short-capable task checks the cross-margin account.

## Scope Of Application
The rule applies to all live `TRADER` tasks, not only leveraged tasks.

It does not apply to:

- `BACK_TRADER`
- `UPDATE_KLINES`
- `CHECK_KLINES`
- `IMPORT_CSV`
- `CHECK_KLINES_NUM`
- `DEBUG`
- non-real or manual notification modes that do not submit exchange orders

The exact live mode filter should reuse the existing `is_real_auto_mode()` helper so the behavior stays aligned with the execution modes that can place real orders.

## Account And Market Routing
The preflight must use the same routing decision as real execution:

- long-only tasks use the spot exchange/account
- short-capable tasks use the cross-margin exchange/account
- user-owned live tasks must resolve the user's credential-backed exchange context before checking balance

This is important because a task set can contain mixed account surfaces. For example, a long-only task may be valid against spot funds while a short-capable task must be validated against cross-margin funds.

Futures account routing is not implemented in this change. Once a futures exchange mode exists, it should reuse this same task-local preflight contract against the futures account.

## Required Amount Definition
The preflight should use the same startup notional concept that currently drives task budget checks:

- capped `auto_trade`: use `live_trade_max_notional`
- uncapped `auto_trade`: use `task.free` when configured
- otherwise fall back to global `cfg.cash`

This is a startup eligibility check, not a promise that every order will use the full amount. The existing strategy and execution sizing layers remain responsible for deciding actual order size.

## Capacity Definition
For each task, capacity is read from the resolved exchange/account for the task's quote asset.

Spot long-only task:

- capacity is free quote balance in the spot account

Short-capable cross-margin task:

- capacity is cross-margin free quote balance plus borrowable quote capacity only when the existing margin borrow precheck is enabled
- if borrow precheck is disabled, capacity is free quote balance only

The preflight must not subtract amounts required by earlier tasks in the same startup batch. Existing active reservations, if any remain from old rows or older runtime versions, must not reduce the new per-task preflight capacity.

## Failure Behavior
The preflight is fail fast:

1. iterate task configs in order
2. skip non-live or non-real-order tasks
3. resolve the task exchange/account
4. compute the task's required amount
5. read the relevant account capacity
6. if `required_amount > capacity`, log a detailed rejection and raise an error
7. do not create or start any task after the first failure

Failure logs should include:

- `task_id`
- `symbol`
- `strategy`
- `live_execution_mode`
- `account_key`
- `market_mode` / margin mode
- `asset`
- `required_amount`
- `balance`
- `max_borrowable`
- `borrow_limit`
- `operable_capacity`
- `reason`

The raised error should be clear enough to persist on failed task states and to show the operator which task must be reconfigured or funded.

## Data Flow
1. `TaskManager.do_add_tasks()` receives a startup batch.
2. Routed exchanges are prepared for the batch.
3. Startup open orders are cancelled according to existing order cleanup rules.
4. The new live balance preflight checks eligible live tasks one by one.
5. If all checks pass, tasks are created and started normally.
6. If a check fails, failed task states are persisted and the process exits in non-server mode as it does today.

The recovery path is intentionally separate from fresh startup admission. `TaskManager.recover_task()` handles tasks whose exchange orders may already exist and must not reject recovery only because the current free balance is lower after those live orders were placed. This change should not add the new fresh-start balance preflight to `recover_task()`.

Recovered tasks should continue to reconstruct runtime state from persisted task and execution records. They should not create new account fund reservation rows as part of recovery.

For recovered real-auto live tasks, the remaining runtime budget should be reconstructed from persisted execution records, not from `account_fund_reservation` rows. The recovery contract is:

- compute the task startup budget using the same required amount definition as fresh startup
- read persisted submitted entry execution records for the task
- sum the submitted entry `quantity * price` or stored effective notional equivalent
- set `fund_reservation_amount` to the startup budget and `fund_reservation_remaining` to `max(startup_budget - submitted_entry_notional, 0)`
- do not fail recovery because the current free balance is lower than the startup budget

## Compatibility Notes
The existing `account_fund_reservation` database model may remain for historical rows or future runtime accounting, but fresh startup should not create account fund reservation rows for this preflight.

Current runtime execution still consumes `TaskConfig.fund_reservation_amount` and `TaskConfig.fund_reservation_remaining` as a per-task budget ceiling. To keep this change scoped, fresh startup should continue to populate those in-memory fields after a task passes preflight, but the fields are reinterpreted as task runtime budget metadata, not evidence of account-level reserved funds.

Startup must not call `account_fund_reservation.reserve()` for the new preflight. Runtime code may continue to tolerate `account_fund_reservation.mark_spent()` as a no-op when no active reservation row exists. Renaming these fields is outside this change and should be handled separately if the project decides to clean up the historical naming.

## Error Handling
- Missing balance reader on a live exchange should fail startup for that task.
- Non-positive required amounts should skip the balance check only if the live mode already treats the amount as disabled or invalid before order placement.
- Exchange API failures while reading balances should fail startup instead of allowing a potentially underfunded live task to start.
- Failures should not leave active reservation rows or partial task state behind.

## Testing
Automated coverage should include:

- two spot live tasks each requiring 100 USDT pass when spot balance is 100 USDT
- a batch with 1000 USDT then 10000 USDT requirements against 5000 USDT fails on the second task
- no tasks are started when any preflight task fails
- long-only tasks read spot balance
- short-capable tasks read cross-margin balance / borrowable capacity
- mixed spot and cross-margin task sets validate each task against its routed account
- backtest tasks are ignored by the live balance preflight
- preflight does not create active `account_fund_reservation` rows
- fresh startup populates per-task runtime budget fields without creating account reservations
- recovery does not run the fresh-start balance preflight and does not create account reservations
- recovery reconstructs remaining task runtime budget from persisted submitted entry execution records when no reservation row exists
- failure logs include at least task id, symbol, account, required amount, balance, borrowable amount, and operable capacity

## Rollout Notes
This is a behavior change to live startup admission. Operators should expect lower account funding requirements for multi-task live batches because task amounts are no longer summed.

The change should be implemented in the framework/task startup layer, not inside individual strategies.
