# Live Task Balance Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace startup account-level fund reservation with read-only per-live-task balance preflight while preserving per-task runtime budget enforcement.

**Architecture:** `TaskManager` owns fresh startup admission. It checks eligible live `TRADER` tasks one by one using the task-routed exchange, writes only in-memory runtime budget fields, and never creates `account_fund_reservation` rows during fresh startup or recovery. Recovery reconstructs remaining runtime budget from persisted submitted entry execution records.

**Tech Stack:** Python, asyncio, pytest, Tortoise test DB helpers already used in `tests/test_account_fund_reservation.py`.

---

### Task 1: Fresh Startup Preflight Semantics

**Files:**
- Modify: `tests/test_account_fund_reservation.py`
- Modify: `src/trader/task/task_manager.py`

- [ ] **Step 1: Write failing tests**

Add tests proving:
- two spot live tasks requiring 100 USDT each pass with only 100 USDT balance
- a 1000 USDT then 10000 USDT batch against 5000 USDT fails on the second task before any task starts
- fresh startup does not create active `account_fund_reservation` rows
- fresh startup still populates `fund_reservation_amount` and `fund_reservation_remaining` as runtime budget fields

- [ ] **Step 2: Run focused tests and verify red**

Run:

```bash
pytest tests/test_account_fund_reservation.py -q
```

Expected: new tests fail because current code still sums active reservations and creates reservation rows.

- [ ] **Step 3: Implement read-only preflight**

In `TaskManager`:
- replace fresh startup call to `_reserve_task_funds(taskcs)` with `_preflight_live_task_balances(taskcs)`
- keep `_reservation_requirement()` / `_reservation_amount()` / capacity snapshot helpers where useful
- implement preflight to iterate task configs in order, validate `amount <= operable_capacity`, log detailed failures, and set task runtime budget fields
- do not call `account_fund_reservation.reserve()` from fresh startup
- adjust exception cleanup so no reservation rollback is required for fresh startup

- [ ] **Step 4: Run focused tests and verify green**

Run:

```bash
pytest tests/test_account_fund_reservation.py -q
```

Expected: pass.

### Task 2: Market Routing And Mixed Accounts

**Files:**
- Modify: `tests/test_account_fund_reservation.py`
- Modify: `src/trader/task/task_manager.py`

- [ ] **Step 1: Write failing tests**

Add tests proving:
- long-only live task reads spot exchange balance
- short-capable live task reads cross-margin exchange balance and borrowable quote capacity
- mixed spot and cross-margin tasks validate against their own routed exchange/account

- [ ] **Step 2: Run focused tests and verify red**

Run:

```bash
pytest tests/test_account_fund_reservation.py -q
```

Expected: tests fail if routing or capacity details are wrong.

- [ ] **Step 3: Implement routing details**

Ensure `_preflight_live_task_balances()` uses `_exchange_for_task(cfg)` and `_reservation_account_key(cfg)` for each task, so user credentials and margin-mode routing match execution.

- [ ] **Step 4: Run focused tests and verify green**

Run:

```bash
pytest tests/test_account_fund_reservation.py -q
```

Expected: pass.

### Task 3: Recovery Runtime Budget Reconstruction

**Files:**
- Modify: `tests/test_account_fund_reservation.py`
- Modify: `src/trader/task/task_manager.py`

- [ ] **Step 1: Write failing test**

Add a recovery test where:
- task startup budget is 100 USDT
- no active reservation row exists
- persisted submitted entry execution records total 40 USDT
- `recover_task()` does not run balance preflight
- recovered task config has `fund_reservation_amount=100` and `fund_reservation_remaining=60`

- [ ] **Step 2: Run focused tests and verify red**

Run:

```bash
pytest tests/test_account_fund_reservation.py -q
```

Expected: recovery test fails because current code calls `_reserve_task_funds([cfg])`.

- [ ] **Step 3: Implement recovery budget loader**

In `TaskManager.recover_task()`:
- remove fresh startup reservation/preflight call
- compute startup budget using `_reservation_amount(cfg)`
- query `db_manager.execution_state.list_open_by_task(task_id)` when available
- sum submitted entry records using `quantity * price`
- set runtime budget fields on `cfg`
- continue recovery without balance rejection

- [ ] **Step 4: Run focused tests and verify green**

Run:

```bash
pytest tests/test_account_fund_reservation.py -q
```

Expected: pass.

### Task 4: Regression And Documentation Verification

**Files:**
- Modify: `docs/superpowers/specs/2026-07-01-live-task-balance-preflight-design.md` only if implementation reveals a spec mismatch

- [ ] **Step 1: Run targeted regression tests**

Run:

```bash
pytest tests/test_account_fund_reservation.py tests/test_task_manager_order_lifecycle.py tests/test_live_auto_execution.py -q
```

Expected: pass.

- [ ] **Step 2: Inspect git diff**

Run:

```bash
git diff --stat
git diff -- src/trader/task/task_manager.py tests/test_account_fund_reservation.py
```

Expected: changes are scoped to live startup preflight and tests.

- [ ] **Step 3: Commit implementation**

Run:

```bash
git add src/trader/task/task_manager.py tests/test_account_fund_reservation.py docs/superpowers/plans/2026-07-01-live-task-balance-preflight.md
git commit -m "fix: preflight live task balances independently"
```
