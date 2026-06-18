# Task Fund Reservation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add account-level quote-asset fund reservations so concurrent live tasks sharing one API-key account cannot consume the same funds.

**Architecture:** Add a Tortoise-backed reservation model and repository, reserve task budgets in `TaskManager` before live startup, release reservations on task completion/stop/failure, and make `AutoExecutionRouter` enforce task-local remaining budget for real-auto entries.

**Tech Stack:** Python, asyncio, Tortoise ORM, FastAPI task lifecycle, pytest.

---

## File Structure

- Create `src/trader/database/account_fund_reservation.py`: repository for reservation acquire/release/query behavior.
- Modify `src/trader/database/models.py`: add `AccountFundReservationModel`.
- Modify `src/trader/database/migrations/0006_account_fund_reservations.py`: migration for the reservation table.
- Modify `src/trader/database/manager.py`: wire repository and required schema table.
- Modify `src/trader/task/task_config.py`: expose helper-level fields through existing config JSON only if needed; no new public config field.
- Modify `src/trader/task/task_manager.py`: compute live reservation needs, reserve before starting live tasks, release on stop/completion/failure.
- Modify `src/trader/task/base_task.py`: keep config JSON and state intact; no reservation logic here unless cleanup hooks need it.
- Modify `src/trader/live/auto_execution.py`: enforce remaining reserved budget when routing entry orders.
- Add `tests/test_account_fund_reservation.py`: repository behavior.
- Add or extend `tests/test_live_auto_execution.py`: router budget enforcement.
- Add or extend `tests/test_rpc_task_preflight.py` / task manager tests: lifecycle reservation and release behavior.

## Tasks

### Task 1: Reservation Data Model

**Files:**
- Modify: `src/trader/database/models.py`
- Create: `src/trader/database/migrations/0006_account_fund_reservations.py`
- Modify: `src/trader/database/manager.py`
- Create: `src/trader/database/account_fund_reservation.py`
- Test: `tests/test_account_fund_reservation.py`

- [ ] Write repository tests for reserve, reject-over-capacity, release, and remaining budget.
- [ ] Run `uv run python -m pytest tests/test_account_fund_reservation.py -q` and confirm it fails because the repository does not exist.
- [ ] Add `AccountFundReservationModel`.
- [ ] Add migration `0006_account_fund_reservations.py`.
- [ ] Add `AccountFundReservationCol` with acquire/release/list/remaining helpers.
- [ ] Wire the repository in `DatabaseManager`.
- [ ] Run `uv run python -m pytest tests/test_account_fund_reservation.py -q`.

### Task 2: Task Lifecycle Reservations

**Files:**
- Modify: `src/trader/task/task_manager.py`
- Test: add focused tests in `tests/test_account_fund_reservation.py` or existing task manager tests.

- [ ] Write tests proving real-auto live tasks reserve quote budgets before start.
- [ ] Write tests proving a task batch is rejected if combined reservations exceed free balance.
- [ ] Write tests proving reservations release when tasks stop or startup fails.
- [ ] Implement helper methods in `TaskManager`: `_reservation_requirement`, `_reserve_task_funds`, `_release_task_funds`, `_release_stale_reservations`.
- [ ] Use exchange routing already present in `TaskManager` so reservation balance checks use the correct user credential and mode.
- [ ] Run the focused lifecycle tests.

### Task 3: Router Budget Enforcement

**Files:**
- Modify: `src/trader/live/auto_execution.py`
- Test: `tests/test_live_auto_execution.py`

- [ ] Write tests proving router skips a spot long entry when remaining reserved budget is below requested notional even if exchange balance is high.
- [ ] Write tests proving router allows entry when reservation store reports enough remaining budget.
- [ ] Add an optional reservation store dependency to `AutoExecutionRouter`.
- [ ] Before real-auto entry submit, read remaining budget for `task_id` and quote asset; fail closed if unavailable.
- [ ] Mark spent budget after successful submit.
- [ ] Run `uv run python -m pytest tests/test_live_auto_execution.py -q`.

### Task 4: Integration Verification

**Files:**
- Existing tests only unless gaps appear.

- [ ] Run `uv run python -m pytest tests/test_account_fund_reservation.py tests/test_live_auto_execution.py tests/test_rpc_task_preflight.py -q`.
- [ ] Run `uv run python -m pytest tests/test_execution_state_store.py tests/test_live_credential_routing.py -q`.
- [ ] Run `uv run python -m pytest tests/test_database_manager.py -q`.
- [ ] Check `git diff --stat` and confirm no unrelated files changed.

### Task 5: PR

**Files:**
- No code files unless PR checks reveal a defect.

- [ ] Run `git remote get-url origin`.
- [ ] If the remote URL contains a GitHub username, ensure `gh` is authenticated as that account before any `gh pr ...` command.
- [ ] Create a branch if needed.
- [ ] Commit the implementation.
- [ ] Push and create a GitHub PR with a summary of mechanism, tests, and remaining risk.
