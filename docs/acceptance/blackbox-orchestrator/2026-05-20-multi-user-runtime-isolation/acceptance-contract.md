---
skill_id: blackbox-acceptance-orchestrator
skill_run_root: docs/acceptance/blackbox-orchestrator/2026-05-20-multi-user-runtime-isolation
workflow_id: 2026-05-20-multi-user-runtime-isolation
source_contract: docs/acceptance/blackbox-orchestrator/2026-05-20-multi-user-runtime-isolation/acceptance-contract.md
status: live-safe-and-mixed-safe-passed
---

# Acceptance Contract

## Goal

Verify that ChainerTrader can run user-owned tasks concurrently after the multi-user runtime isolation changes:

- User A and User B can each run a user-owned task at the same time.
- The safe acceptance mode proves task ownership, startup admin binding, task-list isolation, and the single-running-task guard with long-running `DEBUG` tasks that do not contact Binance.
- Safe live `TRADER` and mixed live/backtest paths are acceptance gates that require valid Binance credentials but use `manual_notify` to avoid real orders.
- Each user sees only their own tasks through the public task API.
- The runtime uses user-scoped exchange credentials, not one global credential shared across users.

## Scope

The system under test is a real local ChainerTrader API server started through the normal application entry point with a SQL database and session authentication enabled.

The acceptance setup may create users and credentials directly in the SQL database because database state is an approved operator setup surface for this run.

## Required Resources

- Safe mode does not require Binance credentials and explicitly disables `TRADER_EXCHANGE`.
- Live-safe, mixed-safe, and real-order modes require `.env` to provide `BINANCE_API_KEY_1`, `BINANCE_API_SECRET_1`, `BINANCE_API_KEY_2`, and `BINANCE_API_SECRET_2`.
- A service encryption key is required as `TRADER_SECRET_KEY`; if `.env` does not provide it, the acceptance harness may inject a local run-only value.
- SQL database URL is required as `TRADER_DB`; the harness may use an isolated SQLite database under `tmp/acceptance/`.
- Bootstrap admin credentials are required as `TRADER_AUTH_USERNAME` and `TRADER_AUTH_PASSWORD`.

## Safety Gate

Live `TRADER` tasks may contact Binance. Tasks configured with `small_live_auto` can place real orders if the strategy emits a live signal. The default safe acceptance run uses `DEBUG` tasks and must not contact Binance. Live-safe and mixed-safe runs use `manual_notify` and must not place real orders. Real-order mode must not run unless the User explicitly approves it for this workflow.

If real-order mode is approved, the run must cap notional using `live_trade_max_notional`, record the task IDs and any exchange order identifiers observed through public APIs, and stop on the first unexpected order or credential error.

## Pass Gates

AC-1: The server starts from the normal product entry point and exposes authenticated HTTP APIs.

AC-2: Two non-admin users are created. In live-safe, mixed-safe, or real-order mode, both users have encrypted default Binance credentials.

AC-3: User A and User B can start user-owned long-running tasks concurrently. In live-safe or real-order mode, both tasks must also appear as running live strategies through `/api/live/strategies`.

AC-4: User A sees only User A's task list through `/api/tasks`; User B sees only User B's task list through `/api/tasks`.

AC-5: User A can run a safe live `TRADER` task while User B runs a `BACK_TRADER` task. This is a live-exchange acceptance gate and is blocked if Binance credentials, permissions, rate limits, network availability, or account state fail.

AC-6: A single user cannot start a second concurrent task while one of their tasks is running. The public API must reject it with a conflict response.

## Non-Goals

- Proving strategy profitability.
- Proving every Binance order type.
- Proving long-term production stability.
- UI redesign validation.

## Failure Classification

- Product defect: public API accepts or leaks cross-user task state, uses the wrong credential scope, or fails to run cross-user tasks concurrently.
- Acceptance harness gap: the harness cannot create users, login, observe tasks, or collect evidence even though product behavior may be correct.
- External dependency gap: Binance credentials, permissions, rate limits, network availability, or account state block live startup.

## Approval Status

Live-safe and mixed-safe acceptance passed. Do not run real-order live acceptance until the User approves the safety gate.
