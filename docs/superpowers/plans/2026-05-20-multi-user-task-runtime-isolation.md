# Multi-User Task Runtime Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make tasks required-user-owned, allow one running task per user while different users run concurrently, attach startup tasks to the administrator, and align the live panel around the current task concept.

**Architecture:** Harden ownership at the task creation/query boundary first, then move startup bootstrap before configured task startup. Keep the existing FastAPI/Jinja/TaskManager structure, but remove global runtime assumptions that would let one user's live task affect another user's task.

**Tech Stack:** Python, FastAPI, Jinja2, Tortoise ORM, pytest, asyncio.

---

## File Map

- Modify: `src/trader/database/user.py`
  - Add a way to fetch the administrator account selected by bootstrap.
- Modify: `src/trader/database/manager.py`
  - Return or expose the bootstrapped administrator.
  - Initialize administrator default exchange credentials only when missing.
- Modify: `src/trader/app/app.py`
  - Delay startup task ownership assignment until after database startup.
  - Attach configured startup tasks to administrator `user_id`.
- Modify: `src/trader/rpc/models.py`
  - Treat admin task pages as administrator-owned task pages, not global task pages.
- Modify: `src/trader/rpc/api/tasks.py`
  - Require authenticated user-owned task creation.
  - Add per-user running task conflict validation.
- Modify: `src/trader/rpc/api/task.py`
  - Stop giving admins global task read/close/delete access in user-facing task APIs.
- Modify: `src/trader/task/task_manager.py`
  - Add reusable running-task checks by user.
  - Keep different users' tasks concurrent.
- Modify: `src/trader/database/task.py`
  - Hide ownerless legacy task rows from user-facing queries.
- Modify: `src/trader/database/execution_state.py`, `src/trader/database/models.py`, migrations under `src/trader/database/migrations/`
  - Add task/user ownership to execution state or introduce scoped query methods.
- Modify: `src/trader/execution/state.py`, `src/trader/live/auto_execution.py`, `src/trader/task/trader_task.py`
  - Carry task/user identity into live execution state and reconciliation.
- Modify: `src/trader/live/stream.py`, `src/trader/task/trader_task.py`
  - Remove task-level exchange overwrite from the global stream polling adapter.
- Modify: `src/trader/rpc/templates/base.html`, `src/trader/rpc/templates/live.html`
  - Rename the user-facing live entry to Current Task.
- Create or modify tests:
  - `tests/test_task_ownership.py`
  - `tests/test_rpc_task_preflight.py`
  - `tests/test_tasks_pagination.py`
  - `tests/test_execution_state_store.py`
  - `tests/test_live_credential_routing.py`
  - `tests/test_realtime_market_stream.py`
  - New targeted tests if a behavior does not fit existing files.

---

### Task 1: Ownership Hardening

**Files:**
- Modify: `src/trader/rpc/models.py`
- Modify: `src/trader/rpc/api/tasks.py`
- Modify: `src/trader/rpc/api/task.py`
- Modify: `src/trader/database/task.py`
- Modify: `src/trader/task/task_manager.py`
- Test: `tests/test_task_ownership.py`
- Test: `tests/test_rpc_task_preflight.py`
- Test: `tests/test_tasks_pagination.py`

- [ ] **Step 1: Write failing tests for admin-owned visibility**

Add tests proving that administrators see only their own tasks and ownerless rows are hidden.

Expected behavior:

```python
page = await get_taskinfo(app, user=SimpleNamespace(id=1, is_admin=True))
assert [task["task_id"] for task in page.tasks] == [owned_admin_task_id]
```

- [ ] **Step 2: Write failing tests for ownerless task creation rejection**

In `tests/test_rpc_task_preflight.py`, add a request without an authenticated current user and assert task creation is rejected before `send_add_tasks_msg`.

Expected:

```python
assert response.status_code in (401, 403)
assert app.state.app.send_add_tasks_msg was not called
```

- [ ] **Step 3: Write failing tests for ownerless legacy rows hidden**

Use the task repository or task manager with one `user_id=None` row and one owned row. Assert user-facing queries return only the owned row.

- [ ] **Step 4: Run the targeted failing tests**

Run:

```bash
uv run pytest tests/test_task_ownership.py tests/test_rpc_task_preflight.py tests/test_tasks_pagination.py -q
```

Expected: FAIL on the new assertions.

- [ ] **Step 5: Implement user-scoped query semantics**

Change admin page/task API behavior from:

```python
user_id = None if user is None or user.is_admin else user.id
```

to:

```python
user_id = user.id if user is not None else None
```

For user-facing endpoints, no authenticated user means reject instead of falling back to global task access.

- [ ] **Step 6: Hide ownerless task rows**

Ensure `get_all_tasks_for_user(user_id)` remains the user-facing path, and do not use `get_all_tasks()` for user pages. If keeping `get_all_tasks()` for internal/admin tooling, document that it is not for user-facing views.

- [ ] **Step 7: Run targeted tests**

Run:

```bash
uv run pytest tests/test_task_ownership.py tests/test_rpc_task_preflight.py tests/test_tasks_pagination.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/trader/rpc/models.py src/trader/rpc/api/tasks.py src/trader/rpc/api/task.py src/trader/database/task.py src/trader/task/task_manager.py tests/test_task_ownership.py tests/test_rpc_task_preflight.py tests/test_tasks_pagination.py
git commit -m "fix: require user-owned task access"
```

---

### Task 2: Startup Administrator Ownership

**Files:**
- Modify: `src/trader/database/user.py`
- Modify: `src/trader/database/manager.py`
- Modify: `src/trader/app/app.py`
- Test: `tests/test_app.py` or new `tests/test_startup_task_ownership.py`

- [ ] **Step 1: Write failing test for bootstrap ordering**

Create a test proving configured startup tasks receive the administrator `user_id` after `db_manager.start()` bootstraps the admin.

Use a fake database manager with:

```python
admin = SimpleNamespace(id=11, username="admin", role="admin")
```

Expected startup message data contains task configs where `taskc.user_id == 11`.

- [ ] **Step 2: Write failing test that startup fails without administrator**

When `cfg.tasks` exists in server mode but no administrator can be resolved, startup should not create ownerless tasks.

Expected: an explicit runtime error or failed start with a logged error.

- [ ] **Step 3: Run failing startup tests**

Run:

```bash
uv run pytest tests/test_app.py tests/test_startup_task_ownership.py -q
```

Expected: FAIL on new tests.

- [ ] **Step 4: Add administrator lookup**

Add repository method in `src/trader/database/user.py`:

```python
async def get_first_admin(self) -> UserModel | None:
    return await UserModel.filter(role="admin", status="active").order_by("id").first()
```

- [ ] **Step 5: Expose bootstrapped administrator**

In `DatabaseManager`, after `_bootstrap_admin()`, expose a method:

```python
async def get_startup_admin(self):
    if not self.user:
        return None
    return await self.user.get_first_admin()
```

- [ ] **Step 6: Move startup task ownership assignment after DB start**

In `App.handler()`, after `await self.db_manager.start()`, resolve the startup admin and attach `user_id` before enqueueing startup task messages.

Avoid parsing `cfg.tasks` in `App.__init__` as the authoritative startup task list when a database-backed server needs administrator ownership.

- [ ] **Step 7: Run targeted startup tests**

Run:

```bash
uv run pytest tests/test_app.py tests/test_startup_task_ownership.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/trader/database/user.py src/trader/database/manager.py src/trader/app/app.py tests/test_app.py tests/test_startup_task_ownership.py
git commit -m "fix: attach startup tasks to admin"
```

---

### Task 3: Default Credential Lifecycle

**Files:**
- Modify: `src/trader/database/manager.py`
- Modify: `src/trader/rpc/app.py`
- Modify: `src/trader/rpc/templates/account.html`
- Test: `tests/test_user_repositories.py`
- Test: new `tests/test_admin_credential_bootstrap.py`

- [ ] **Step 1: Write failing tests for administrator credential initialization**

Given admin exists and default credential is missing, database startup initializes `BINANCE/default` from configured exchange credentials.

Expected:

```python
credential = await db.exchange_credential.get_default(admin.id, "BINANCE")
assert credential is not None
```

- [ ] **Step 2: Write failing test that restart does not overwrite manual update**

Seed an administrator credential with `masked_api_key="manual***key"`, run bootstrap again, assert the stored credential remains unchanged.

- [ ] **Step 3: Write failing test for reset action**

Add a route-level test for administrator reset. It should overwrite the administrator's default credential from configuration and redirect back to `/account`.

- [ ] **Step 4: Run credential tests**

Run:

```bash
uv run pytest tests/test_user_repositories.py tests/test_admin_credential_bootstrap.py -q
```

Expected: FAIL on new tests.

- [ ] **Step 5: Implement config-to-default credential bootstrap**

In `DatabaseManager`, after admin bootstrap, if admin default `BINANCE` credential is missing and config has usable exchange credentials plus `TRADER_SECRET_KEY`, encrypt and store it.

Do not overwrite existing administrator credentials.

- [ ] **Step 6: Add reset route**

In `src/trader/rpc/app.py`, add administrator-only POST route:

```python
@app.post("/account/exchange-credentials/reset-default")
```

It should require admin, read the configured default exchange credential, encrypt it, upsert the admin default credential, and redirect to `/account`.

- [ ] **Step 7: Add reset button**

In `account.html`, show the reset button only when `user.is_admin` and configured credential reset is available.

- [ ] **Step 8: Run credential tests**

Run:

```bash
uv run pytest tests/test_user_repositories.py tests/test_admin_credential_bootstrap.py tests/test_rpc_session_auth.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/trader/database/manager.py src/trader/rpc/app.py src/trader/rpc/templates/account.html tests/test_user_repositories.py tests/test_admin_credential_bootstrap.py
git commit -m "feat: manage admin default exchange credential"
```

---

### Task 4: Per-User Running Task Limit

**Files:**
- Modify: `src/trader/task/task_manager.py`
- Modify: `src/trader/rpc/api/tasks.py`
- Test: `tests/test_task_ownership.py`
- Test: `tests/test_rpc_task_preflight.py`

- [ ] **Step 1: Write failing test for same-user conflict**

Create a fake task manager with one running task for `user_id=5`. POST another task as user 5 and assert HTTP 409.

- [ ] **Step 2: Write failing test for different-user concurrency**

Create running task for `user_id=7`; POST as `user_id=5` and assert the task is accepted.

- [ ] **Step 3: Run failing tests**

Run:

```bash
uv run pytest tests/test_task_ownership.py tests/test_rpc_task_preflight.py -q
```

Expected: FAIL on new conflict behavior.

- [ ] **Step 4: Add running task query**

In `TaskManager`, add:

```python
async def has_running_task_for_user(self, user_id: int) -> bool:
    for task in self.tasks.values():
        if getattr(task.ts, "user_id", None) == user_id and task.ts.is_running():
            return True
    for ts in await self.db_manager.task.get_all_tasks_for_user(user_id):
        if ts.is_running():
            return True
    return False
```

Guard for missing `db_manager`.

- [ ] **Step 5: Validate before enqueue**

In `rpc/api/tasks.py`, before `send_add_tasks_msg`, call the running-task check for the current user. Return 409 with a clear message if already running.

- [ ] **Step 6: Run targeted tests**

Run:

```bash
uv run pytest tests/test_task_ownership.py tests/test_rpc_task_preflight.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/trader/task/task_manager.py src/trader/rpc/api/tasks.py tests/test_task_ownership.py tests/test_rpc_task_preflight.py
git commit -m "fix: enforce one running task per user"
```

---

### Task 5: Live Runtime Isolation

**Files:**
- Modify: `src/trader/database/models.py`
- Create: migration under `src/trader/database/migrations/`
- Modify: `src/trader/database/execution_state.py`
- Modify: `src/trader/execution/state.py`
- Modify: `src/trader/live/auto_execution.py`
- Modify: `src/trader/task/trader_task.py`
- Modify: `src/trader/live/stream.py`
- Test: `tests/test_execution_state_store.py`
- Test: `tests/test_live_credential_routing.py`
- Test: `tests/test_realtime_market_stream.py`
- Test: `tests/test_trader_task_backtrader_live_runtime.py`

- [ ] **Step 1: Write failing test for execution state scoped by task/user**

Create two execution records for the same symbol but different `task_id`/`user_id`. Assert scoped reconciliation for task A returns only task A.

- [ ] **Step 2: Write failing test for stream exchange context**

Create two polling stream subscriptions with different task exchange objects. Assert the second task does not mutate the first task's market data exchange context.

- [ ] **Step 3: Run failing live isolation tests**

Run:

```bash
uv run pytest tests/test_execution_state_store.py tests/test_realtime_market_stream.py tests/test_trader_task_backtrader_live_runtime.py -q
```

Expected: FAIL on new isolation assertions.

- [ ] **Step 4: Extend execution state identity**

Add nullable migration fields first:

```python
task_id = fields.IntField(null=True)
user_id = fields.IntField(null=True)
```

Add indexes for:

```python
("task_id", "user_id", "symbol")
```

- [ ] **Step 5: Carry task/user into execution records**

Extend `ExecutionStateRecord` to carry optional `task_id` and `user_id`. When `AutoExecutionRouter` creates records for a task, fill both from `tcfg`.

- [ ] **Step 6: Add scoped execution state query**

Add:

```python
async def list_open_for_task(self, task_id: int, user_id: int, symbol: str) -> list[ExecutionStateRecord]
```

Keep `list_open_by_symbol` only for legacy/internal fallback.

- [ ] **Step 7: Use scoped reconciliation**

In `TraderTask._reconcile_execution_state`, for user-owned tasks call `list_open_for_task(self.tcfg.id, self.tcfg.user_id, symbol)`.

- [ ] **Step 8: Remove global exchange overwrite**

Replace the global `set_exchange(self.exchange)` pattern with an adapter design that does not mutate shared connector state per task. Acceptable first implementation:

- Market data polling uses a market-data-only exchange configured at app startup.
- Task-specific trading exchanges remain inside `TraderTask` and `AutoExecutionRouter`.
- Shared market stream hub only emits market data; it does not carry account credentials.

- [ ] **Step 9: Run live isolation tests**

Run:

```bash
uv run pytest tests/test_execution_state_store.py tests/test_realtime_market_stream.py tests/test_trader_task_backtrader_live_runtime.py tests/test_live_credential_routing.py -q
```

Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add src/trader/database/models.py src/trader/database/migrations src/trader/database/execution_state.py src/trader/execution/state.py src/trader/live/auto_execution.py src/trader/task/trader_task.py src/trader/live/stream.py tests/test_execution_state_store.py tests/test_realtime_market_stream.py tests/test_trader_task_backtrader_live_runtime.py tests/test_live_credential_routing.py
git commit -m "fix: isolate live execution runtime state"
```

---

### Task 6: Current Task Page

**Files:**
- Modify: `src/trader/rpc/app.py`
- Modify: `src/trader/rpc/templates/base.html`
- Modify: `src/trader/rpc/templates/live.html`
- Possibly create: `src/trader/rpc/templates/current_task.html`
- Modify: `src/trader/rpc/static/js/live-monitor.js` if route names or DOM ids change.
- Test: `tests/test_rpc.py`
- Test: `tests/test_live_monitor_api_contract.py`

- [ ] **Step 1: Write failing route/template tests**

Assert `/admin/live` still works during transition, but page title/nav text now says current task.

Expected:

```python
assert "当前任务" in response.text
```

- [ ] **Step 2: Write current-task selection tests**

Add model/helper tests for:

- Running task wins.
- If no running task exists, most recent task wins.
- Selecting a historical task does not mutate running task state.

- [ ] **Step 3: Run failing UI tests**

Run:

```bash
uv run pytest tests/test_rpc.py tests/test_live_monitor_api_contract.py -q
```

Expected: FAIL on new current-task expectations.

- [ ] **Step 4: Rename user-facing page**

Change nav label from `实盘监控` to `当前任务`. Keep `/admin/live` route as a compatibility path unless a route rename is explicitly required.

- [ ] **Step 5: Add current task helper**

Add a small helper in `rpc/models.py` or a focused module that selects:

1. current user's running task
2. otherwise current user's most recent task

Use existing task state data first; do not introduce a new table in this slice.

- [ ] **Step 6: Route render by task type**

Keep live rendering for `TaskType.TRADER`. Show a generic task state panel for unsupported task types until backtest/data-specific renderers are implemented.

- [ ] **Step 7: Run UI tests**

Run:

```bash
uv run pytest tests/test_rpc.py tests/test_live_monitor_api_contract.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/trader/rpc/app.py src/trader/rpc/templates/base.html src/trader/rpc/templates/live.html src/trader/rpc/templates/current_task.html src/trader/rpc/static/js/live-monitor.js src/trader/rpc/models.py tests/test_rpc.py tests/test_live_monitor_api_contract.py
git commit -m "feat: show current task workspace"
```

---

## Final Verification

- [ ] Run repository layout guard:

```bash
uv run python scripts/check_repo_layout.py
```

- [ ] Run focused backend tests:

```bash
uv run pytest tests/test_task_ownership.py tests/test_rpc_task_preflight.py tests/test_tasks_pagination.py tests/test_user_repositories.py tests/test_execution_state_store.py tests/test_live_credential_routing.py tests/test_realtime_market_stream.py tests/test_trader_task_backtrader_live_runtime.py tests/test_rpc.py tests/test_live_monitor_api_contract.py -q
```

- [ ] Run the broader relevant suite if time allows:

```bash
uv run pytest tests/test_rpc*.py tests/test_*task*.py tests/test_*live*.py tests/test_execution_state_store.py -q
```

- [ ] Review diff:

```bash
git diff --stat
git diff
```

- [ ] Confirm docs:

The implementation should remain consistent with:

- `docs/superpowers/specs/2026-05-20-multi-user-task-runtime-isolation-design.md`
- `AGENTS.md`

