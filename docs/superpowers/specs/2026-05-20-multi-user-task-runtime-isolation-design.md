# Multi-User Task Runtime Isolation Design

## Status
Draft

## Date
2026-05-20

## Context
ChainerTrader now has user accounts, sessions, user-owned exchange credentials, and task ownership fields. That is enough for database-level ownership, but it does not fully define how tasks should run when multiple users are active.

The immediate product goal is narrower than a full multi-tenant trading platform:

- Each user can have at most one running task at a time.
- Different users can run tasks concurrently.
- A task can be live trading, backtesting, data download, or another supported task type.
- Administrator-owned startup tasks should follow the same ownership model as normal user tasks.
- The UI does not need administrator cross-user task filtering because administrators do not need to inspect other users' task history in this phase.

This design turns task ownership into a required runtime boundary instead of a best-effort database annotation.

## Goals
- Require every newly created task to have a `user_id`.
- Hide legacy tasks that do not have `user_id`, including from administrators.
- Create or confirm the administrator account before starting configured startup tasks.
- Attach configured startup tasks to the administrator user on every service restart.
- Treat each restart's configured startup tasks as a new run, not as a continuation of old tasks.
- Enforce one running task per user.
- Allow different users to run tasks concurrently.
- Keep administrator and normal user flows aligned except for administrator-only account-management permissions.
- Keep the current FastAPI, Jinja, Bootstrap, and lightweight JavaScript stack.

## Non-Goals
- Multi-exchange user credential management.
- Multiple API keys per user.
- Administrator task browsing across all users.
- UI-level user filters for task lists.
- A SPA rewrite.
- Full worker or process isolation per user.
- Retaining visibility for legacy ownerless task rows.

## Product Rules

### Task Ownership
Tasks are user-owned runtime records.

New task creation must resolve a user before the task is accepted:

- Web/API requests use the authenticated current user.
- Startup-configured tasks use the administrator user.
- Ownerless task creation is invalid.

Legacy rows where `tasks.user_id IS NULL` remain in the database but are ignored by user-facing task queries. Administrators do not get an exception for these rows because that would reintroduce a second task visibility model.

### Startup Tasks
Service startup must follow this sequence:

1. Initialize database access.
2. Create or confirm the administrator account.
3. Initialize administrator default exchange credentials if missing.
4. Parse configured startup tasks.
5. Attach the administrator `user_id` to each startup task.
6. Start those tasks as a new run for this service restart.

Every restart creates a new run because it reflects a new process lifetime, code version, environment, and market context. This makes restart-to-restart comparison possible without reusing stale task state.

### Per-User Concurrency
Each user can have at most one running task.

The system must reject a new task for a user when that user already has a running task. This applies equally to administrator and normal users.

Different users can run tasks at the same time. For example:

- User A can run a live trading task.
- User B can run a long backtest task.
- The two tasks must not block each other at the task scheduling layer.

### Default Exchange Credential
Current product scope supports one default exchange and one default API credential set per user.

The existing database schema can keep `exchange` and `label` fields for future extension, but the product flow should expose only the default credential:

- `exchange = "BINANCE"` for the current phase.
- `label = "default"`.
- One API key and one API secret per user.

For the administrator:

- When the administrator account or default credential is first created, the API key and secret are read from configuration and encrypted into the database.
- Later service restarts must not overwrite the stored administrator credential.
- If the administrator manually updates the credential, the database value becomes authoritative.
- A reset action restores the administrator default credential from configuration.

The same stored API key is reused by different exchange objects required by execution mode, for example spot and margin clients.

## Current Task View
The current `Live Monitoring` concept should become `Current Task`.

Live trading is an important task type, but it should not be the page-level concept. The page should display the current task using task-type-specific rendering.

Rules:

- If the current user has a running task, the main panel displays that task.
- If the current user has no running task, the main panel displays the user's most recent task.
- The recent task list is for historical navigation only.
- Selecting items in the recent task list does not change the running task.
- Starting a task from the list creates a new run and makes that new run the current running task.
- Stopping a task stops only the current user's running task.

Task-type rendering:

- Live task: chart, signal, order, risk, execution, and runtime status panels.
- Backtest task: progress, logs, stage status, and final report when available.
- Data task: progress, coverage, missing ranges, and error details.
- Completed task: read-only result view.

## Runtime Isolation Requirements
The first implementation does not need process-level isolation, but it must remove runtime paths that make one user's task affect another user's task.

Required boundaries:

- Task lookup, close, delete, and list operations must filter by the current user's `user_id`.
- Administrator task pages use the administrator's own `user_id`, not a global unfiltered task query.
- Running-task checks must be scoped by `user_id`.
- Execution state used for live reconciliation must be scoped by task identity, not only by symbol.
- Market data streams may share the external data source, but per-task runtime context must remain task-local.
- A later-started task must not overwrite exchange context used by an already-running task.

Known risk in the current code:

- Live execution reconciliation currently queries open execution state by symbol. That can mix two users running the same market.
- The global market stream hub currently allows the polling connector exchange to be overwritten by a task's exchange instance. That can make concurrent live tasks depend on whichever task initialized last.

These risks should be addressed before claiming multi-user live trading is isolated.

## Data Model Notes
The existing `tasks.user_id` field becomes required for new records, even if the database column remains nullable during migration.

The execution-state model should gain enough ownership data to support isolated reconciliation. The preferred boundary is:

- `task_id`
- `user_id`
- `symbol`

If schema migration is staged, the first code-level improvement should at least stop live reconciliation from using symbol-only state for user-owned tasks.

## Error Handling
- Starting a task without an authenticated user returns an authentication error.
- Starting a task when the user already has a running task returns a clear conflict error.
- Starting a live task without the user's default credential returns a credential error.
- Starting a startup-configured task before administrator bootstrap succeeds must fail startup rather than create ownerless tasks.
- Resetting administrator credentials without usable configured credentials returns a clear configuration error.

## Testing Plan
Automated tests should cover:

- New task creation rejects ownerless tasks.
- Legacy ownerless tasks are hidden from normal users and administrators.
- Startup bootstrap creates or confirms administrator before parsing startup tasks.
- Startup-configured tasks receive the administrator `user_id`.
- Restarting service startup creates a new task run instead of reusing a previous one.
- A user cannot start a second task while one of that user's tasks is running.
- Two different users can run tasks concurrently.
- User A live task and User B backtest task can run concurrently.
- Administrator default credential initializes from configuration only when missing.
- Administrator manual credential update survives restart.
- Administrator reset restores configured credential.
- Live reconciliation does not read another user's execution state for the same symbol.
- Concurrent live tasks do not overwrite each other's exchange context.

## Rollout Plan
Implement in focused slices:

1. Ownership hardening.
   - Make new task creation require `user_id`.
   - Hide ownerless tasks from all user-facing task queries.
   - Ensure administrator pages use administrator-owned task queries.

2. Startup bootstrap.
   - Ensure administrator exists before configured tasks are parsed and started.
   - Attach administrator `user_id` to configured startup tasks.
   - Treat every restart as a new run.

3. Credential lifecycle.
   - Initialize administrator default credential from configuration only when missing.
   - Add administrator credential reset from configuration.
   - Keep user-facing credential flow as one default credential.

4. Per-user concurrency.
   - Enforce one running task per user.
   - Preserve concurrent execution for different users.

5. Current Task view.
   - Rename live monitoring to current task.
   - Route rendering by task type.
   - Keep history selection read-only unless the user explicitly starts a task.

6. Live isolation hardening.
   - Scope execution state reconciliation by task/user.
   - Remove global exchange overwrites from shared market stream polling.

## Open Decisions
- Whether `task_id` remains globally unique or becomes unique per run namespace.
- Whether restart run metadata should be an explicit table now or captured through task records first.
- Whether the current task page should initially support only live/backtest renderers and show a generic state panel for other task types.
