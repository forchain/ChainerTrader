# Task Fund Reservation Design

## Status
Approved for implementation by user instruction.

## Date
2026-06-17

## Context
One task set can contain multiple live trading tasks running at the same time. Those tasks can use the same Binance API key and therefore the same real account balance.

The existing code has useful safety controls, but it does not lock funds:

- `free` controls the task's intended strategy capital.
- `live_trade_max_notional` caps the notional for `auto_trade` orders when positive.
- live routing checks exchange free balance before submitting a spot long order.
- task and execution state are scoped by user/task.

None of those controls records that one running task has reserved part of an account balance. Two tasks can both read the same `USDT` free balance and both decide that their own order is affordable. That is a race against the same API-key account, not a strategy bug.

## Goal
Guarantee that each running live task using a shared API-key account has an exclusive quote-asset budget before it can submit live orders.

## Non-Goals
- Building a full multi-asset portfolio margin risk engine.
- Replacing Binance spot or margin validation.
- Locking base assets for close orders.
- Supporting multiple credentials per user beyond the existing default credential.
- Changing backtest or manual-notification behavior.

## Recommended Approach
Add a database-backed account fund reservation ledger.

The ledger is keyed by:

- `account_key`: stable account identity derived from the user credential, initially `BINANCE:credential:<exchange_credential.id>`.
- `task_id`
- `asset`, initially the quote asset such as `USDT`.

Each real-auto live task must reserve its configured quote budget before it starts. The task manager rejects a batch when the total active reservations plus requested reservations exceed the exchange free balance for that account and asset.

The auto execution router then spends against the task's reserved budget instead of the whole exchange account balance. This gives each task a local budget ceiling even when the exchange account contains more funds.

## Reservation Amount
For a task requiring live auto orders:

- capped `auto_trade`: reserve `live_trade_max_notional`.
- uncapped `auto_trade`: reserve `task.free` when configured, otherwise `Config.cash`.

The reserved asset is the task quote asset. For `BTC-USDT`, the reserved asset is `USDT`.

For cross-margin short-capable tasks, the first implementation still reserves quote notional. Margin borrow capacity and liability handling remain controlled by the existing margin borrow precheck and borrow-block policy.

## Lifecycle
1. Parse task configs and attach user ownership as today.
2. Before starting real-auto live tasks, resolve the account credential and quote asset.
3. Fetch current exchange free balance for that asset.
4. In one database transaction, compute active reservations for the same account and asset and insert the new reservation only if capacity is available.
5. Start the task only after reservation succeeds.
6. During order routing, skip new entry orders if the task's remaining reserved budget cannot cover the requested notional.
7. When the task completes, is stopped, fails startup, or is closed during shutdown, release the active reservation.
8. On service startup, stale active reservations for non-running tasks must not block new work. The first implementation should release reservations for tasks that are no longer marked `RUNNING`.

## Data Model
Create `account_fund_reservations`:

- `id`
- `account_key`
- `exchange`
- `credential_id`
- `user_id`
- `task_id`
- `asset`
- `reserved_amount`
- `spent_amount`
- `status`: `active`, `released`
- `reason`
- `created_at`
- `updated_at`
- `released_at`

Constraints and indexes:

- one active row per `task_id` / `asset`
- indexes on `account_key`, `asset`, `status`, and `task_id`

Use a repository under `src/trader/database/` so task management and live routing do not reach into ORM models directly.

## Error Handling
- If exchange balance cannot be fetched, reject the task before live start.
- If requested reservation exceeds available unreserved balance, reject the task with a clear conflict-style error.
- If task startup fails after reserving, release the reservation before returning.
- If reservation release fails, log an error; do not hide the original task failure.
- If the router cannot read a reservation, fail closed for real-auto entry orders.

## Current Mechanism Assessment
The current mechanism is not sufficient.

It prevents some unsafe single-task orders, but it does not prove shared-account fund exclusivity because:

- balance checks read the exchange account directly and do not subtract other running tasks' allocations;
- `free` is persisted as task metadata but not locked anywhere;
- execution state reserves idempotency keys, not money;
- the API preflight currently stops the same user's running task before submitting a new one, but a task set can still contain multiple live tasks, and different users or startup tasks can share one underlying API key.

## Testing
Automated coverage should prove:

- active reservations are summed by account and asset;
- a second task is rejected when active reservations would exceed exchange free balance;
- reservations from released tasks do not consume capacity;
- reservation is released when a task is stopped;
- real-auto routing skips entry orders that exceed the task's remaining reserved budget;
- small-live uses `live_trade_max_notional`;
- full-live uses `free` / configured cash;
- non-real-auto and backtest tasks do not reserve funds.

## Rollout Notes
This is a framework-layer fix. Strategies should continue to express signals and sizing intent; the shared task/execution layer enforces account-budget exclusivity.

README does not need an immediate update unless a user-facing task configuration field is added. If a future UI exposes reservation state, README/user manual should be updated then.
