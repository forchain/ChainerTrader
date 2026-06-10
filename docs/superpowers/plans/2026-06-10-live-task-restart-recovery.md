# Live Task Restart Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore persisted `RUNNING` live tasks after server restart by rebuilding and starting equivalent runtime tasks under the same task identity without blocking API startup on the whole recovery backlog.

**Architecture:** Persist enough live task configuration for exact recovery, parse persisted `RUNNING` rows into `TaskConfig` objects with original IDs, and schedule recovery after startup through a bounded async queue. Recovery uses the existing `TaskManager` task-start path so tasks actually run again instead of only changing database state.

**Tech Stack:** Python 3.13, FastAPI lifespan, asyncio, pytest/anyio, existing `TaskManager`, `App`, `BaseTask`, and `TaskConfig` modules.

---

## File Structure

- Modify `src/trader/task/base_task.py`
  - Responsibility: generate persisted task `config_json` that can faithfully recreate live task runtime config.
- Modify `src/trader/app/app.py`
  - Responsibility: load persisted `RUNNING` task rows, preserve identity, and schedule recovery without blocking all server startup.
- Modify `src/trader/rpc/rpc_app.py` if needed
  - Responsibility: own background tasks created by server mode startup and cancel/await them on stop.
- Modify `src/trader/task/task_manager.py` if needed
  - Responsibility: expose a recovery-safe path that starts long-running tasks without marking them `DONE` just because dispatch returned.
- Modify `tests/test_config.py`
  - Responsibility: config JSON round-trip tests.
- Modify `tests/test_cli_task_handling.py`
  - Responsibility: app recovery identity and scheduling tests.
- Modify `tests/test_rpc_app_lifecycle.py`
  - Responsibility: async startup and non-blocking recovery tests.

## Task 1: Preserve Live Runtime Config in Persisted JSON

**Files:**
- Modify: `src/trader/task/base_task.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing round-trip test**

Add a test that creates a `TaskConfig` with:

- `TaskType.TRADER`
- `live_execution_mode="small_live_auto"`
- `live_data_mode="realtime"`
- `live_trade_max_notional=12.0`
- `live_short_execution="margin_cross"`
- `live_margin_borrow_block_policy="repay_all"`
- `live_margin_borrow_precheck=False`
- auto-repay limits and excluded assets
- `strategy_params={"chainer_mode": "BOTH"}`
- `user_id` and `run_id`

Generate `BaseTask(...).ts.config_json`, parse it with `parse_task_config()`, and assert all listed fields round-trip.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run python -m pytest -q tests/test_config.py::test_base_task_config_json_preserves_live_runtime_controls
```

Expected: FAIL because one or more live runtime fields are lost.

- [ ] **Step 3: Implement minimal persistence fix**

In `BaseTask._generate_config_json()`, include non-default live runtime fields:

- `live_short_execution`
- `live_trade_max_notional`
- `live_margin_borrow_block_policy`
- `live_margin_borrow_precheck`
- `live_margin_auto_repay_max_total`
- `live_margin_auto_repay_max_per_asset`
- `live_margin_auto_repay_min_amount`
- `live_margin_auto_repay_excluded_assets`

Keep existing style: only write fields when they differ from parser defaults.

- [ ] **Step 4: Run the test to verify it passes**

Run:

```bash
uv run python -m pytest -q tests/test_config.py::test_base_task_config_json_preserves_live_runtime_controls
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/trader/task/base_task.py tests/test_config.py
git commit -m "fix: preserve live task recovery config"
```

## Task 2: Keep Persisted Identity During Recovery

**Files:**
- Modify: `src/trader/app/app.py`
- Test: `tests/test_cli_task_handling.py`

- [ ] **Step 1: Write the identity recovery test**

Add or extend a test so a persisted row with:

- `id=11`
- `state.name == "RUNNING"`
- `user_id=7`
- `config_json` containing a live `TRADER` task
- `run_id="run-11"`

produces a recovered `TaskConfig` whose `id == 11`, `user_id == 7`, and `run_id == "run-11"`.

- [ ] **Step 2: Run the test**

Run:

```bash
uv run python -m pytest -q tests/test_cli_task_handling.py::test_app_start_restores_running_tasks_from_database
```

Expected: PASS if current identity handling already covers this; otherwise FAIL and fix.

- [ ] **Step 3: Fix only if needed**

In `App._recover_running_task_msgs()` or its replacement helper, set parsed `TaskConfig.id` from the persisted row and restore `user_id`/`run_id` from row/config.

- [ ] **Step 4: Re-run the test**

Run the same pytest command.

Expected: PASS.

- [ ] **Step 5: Commit if implementation changed**

```bash
git add src/trader/app/app.py tests/test_cli_task_handling.py
git commit -m "fix: reuse persisted task identity on recovery"
```

## Task 3: Schedule Recovery Without Blocking API Startup

**Files:**
- Modify: `src/trader/app/app.py`
- Modify: `src/trader/rpc/rpc_app.py` if lifecycle ownership requires it
- Test: `tests/test_rpc_app_lifecycle.py`

- [ ] **Step 1: Write non-blocking startup test**

Add an async test where persisted `RUNNING` tasks exist and the task recovery worker is blocked by an `asyncio.Event`.

Assert:

- `await app.start_async()` returns without waiting for the blocked task to finish.
- A background recovery task is scheduled.
- The queued recovered `TaskConfig` preserves the original ID.

- [ ] **Step 2: Run the test to verify it fails**

Run:

```bash
uv run python -m pytest -q tests/test_rpc_app_lifecycle.py::test_rpc_app_async_start_schedules_recovery_without_waiting_for_tasks
```

Expected: FAIL because startup currently processes initial task messages directly during startup.

- [ ] **Step 3: Implement background recovery scheduling**

Add a server-mode startup path that:

- loads recovered task configs from DB,
- stores them in an internal recovery queue or recovery task list,
- starts a background coroutine after normal service startup,
- does not wait for every recovered live task to complete before returning from `start_async()`.

Use a small helper boundary such as:

```python
async def _load_running_task_configs(self) -> list[TaskConfig]:
    ...

def _schedule_recovery_tasks(self, taskcs: list[TaskConfig]) -> None:
    ...
```

Keep CLI behavior unchanged unless required by tests.

- [ ] **Step 4: Add bounded concurrency**

Use a conservative default concurrency, for example `10`, as a module constant if no config field exists. The recovery worker should start at most that many recovered tasks at once.

- [ ] **Step 5: Add bounded concurrency test**

Add a test that queues more recovered tasks than the default recovery concurrency and blocks task startup until the test releases an event.

Assert:

- active recovery starts never exceed the configured/default concurrency,
- the remaining tasks stay queued instead of being started with unbounded `create_task` fanout,
- startup readiness does not wait for all queued tasks to start.

- [ ] **Step 6: Run the non-blocking and concurrency tests**

Run:

```bash
uv run python -m pytest -q tests/test_rpc_app_lifecycle.py::test_rpc_app_async_start_schedules_recovery_without_waiting_for_tasks tests/test_rpc_app_lifecycle.py::test_rpc_app_recovery_limits_concurrent_task_starts
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/trader/app/app.py src/trader/rpc/rpc_app.py tests/test_rpc_app_lifecycle.py
git commit -m "fix: recover live tasks in background on startup"
```

## Task 4: Prevent Recovered Long-Running Tasks From Being Marked Done During Dispatch

**Files:**
- Modify: `src/trader/task/task_manager.py`
- Test: `tests/test_cli_task_handling.py` or `tests/test_rpc_app_lifecycle.py`

- [ ] **Step 1: Write regression test**

Create a fake long-running task whose `start()` waits on an event. Dispatch it through the recovery path and assert the task state remains `RUNNING` while the start coroutine is still active.

The test must inspect both:

- `TaskManager.tasks` / in-memory task state,
- persisted task state batches written through the fake task repository.

- [ ] **Step 2: Run the test to verify behavior**

Run the targeted pytest command.

Expected: FAIL if recovery dispatch marks tasks `DONE` after queue dispatch rather than after actual completion.

- [ ] **Step 3: Implement recovery-safe task start path**

If needed, add a method to `TaskManager` that starts recovered task configs and leaves long-running tasks registered in `self.tasks`:

```python
def recover_tasks(self, taskcs: list[TaskConfig], queue: Queue) -> None:
    ...
```

or update existing async task handling so recovered long-running tasks are not stopped and popped merely because dispatch returned.

- [ ] **Step 4: Run regression test**

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/trader/task/task_manager.py tests/test_cli_task_handling.py tests/test_rpc_app_lifecycle.py
git commit -m "fix: keep recovered live tasks running"
```

## Task 5: Verification and PR Update

**Files:**
- No required source modifications.

- [ ] **Step 1: Run targeted tests**

```bash
uv run python -m pytest -q tests/test_config.py tests/test_cli_task_handling.py tests/test_rpc_app_lifecycle.py tests/test_manual_live_trade_notifications.py tests/test_trader_task_backtrader_live_runtime.py
```

- [ ] **Step 2: Run syntax/diff checks**

```bash
uv run python -m compileall -q src tests
git diff --check
```

- [ ] **Step 3: Inspect git status and recent commits**

```bash
git status --short --branch
git log --oneline --decorate -6
```

- [ ] **Step 4: Push branch**

Before any PR command, inspect remote account per AGENTS.md:

```bash
git remote get-url origin
gh auth status
```

If the remote URL includes `OutlierChainer`, ensure `gh` is active as `OutlierChainer`.

Then:

```bash
git push origin fix/recover-running-tasks-on-restart
```

- [ ] **Step 5: Update PR if needed**

Use `gh pr view` or `gh pr edit` only after confirming the GitHub account rule.
