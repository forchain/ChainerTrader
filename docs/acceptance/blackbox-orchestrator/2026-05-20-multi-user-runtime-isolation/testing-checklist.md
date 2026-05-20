---
skill_id: blackbox-acceptance-orchestrator
skill_run_root: docs/acceptance/blackbox-orchestrator/2026-05-20-multi-user-runtime-isolation
workflow_id: 2026-05-20-multi-user-runtime-isolation
source_contract: docs/acceptance/blackbox-orchestrator/2026-05-20-multi-user-runtime-isolation/acceptance-contract.md
status: live-safe-and-mixed-safe-passed
---

# Testing Checklist

## TEST-1: Server Boot And Schema Readiness

Status: passed in safe, live-safe, and mixed-safe modes

Purpose: prove a real local server can start with the schema needed by user-owned tasks and execution-state task scoping.

Setup:
- Use an isolated SQL database.
- Run `uv run trader-db migrate`.
- Start the server through the normal CLI entry point.

Steps:
- Poll `/name` until it responds.
- Log in as the bootstrap admin.
- Record the database path, server URL, and process ID.

Expected result:
- `/name` returns `{"name": "trader"}`.
- Admin login succeeds and receives a session cookie.

Evidence:
- Server URL.
- PID.
- DB path.
- HTTP status codes.

## TEST-2: Two User Setup

Status: passed in safe, live-safe, and mixed-safe modes

Purpose: prove two users exist before task startup. In live/real-order mode, also prove they have separate default Binance credentials.

Setup:
- Create users `accept_user_a` and `accept_user_b`.
- Safe mode may skip credential insertion when Binance keys are not required.
- Live/real-order mode inserts encrypted credentials from `BINANCE_API_KEY_1/BINANCE_API_SECRET_1` and `BINANCE_API_KEY_2/BINANCE_API_SECRET_2`.

Steps:
- Log in as each user.
- Query `/account` or the database credential table for masked credential evidence.

Expected result:
- Both users can authenticate.
- In safe mode, both users can authenticate.
- In live/real-order mode, each user has exactly one default `BINANCE` credential and the masked API key values differ.

Evidence:
- User IDs.
- Masked API key values.
- Login HTTP statuses.

## TEST-3: Two Users Run Tasks Concurrently

Status: passed in safe and live-safe modes

Purpose: prove the runtime supports one running task per user while allowing different users to run tasks at the same time.

Setup:
- User A and User B are logged in.
- Safe mode uses long-running `DEBUG` tasks and disables `TRADER_EXCHANGE`.
- Live-safe mode uses `TRADER` tasks with `live_execution_mode=manual_notify` and does not place real orders.
- Real-order mode uses `TRADER` tasks and requires explicit User approval for real orders.

Steps:
- User A posts a long-running task to `/api/tasks`.
- User B posts a long-running task to `/api/tasks`.
- Poll `/api/tasks` for each user.
- Poll `/api/live/strategies` for each user.

Expected result:
- Both task creation calls return success.
- Each user sees one `RUNNING` task in `/api/tasks`.
- Safe mode does not require `/api/live/strategies` entries because `DEBUG` tasks are not live strategies.
- Live-safe and real-order modes require each user to see one matching live strategy in `/api/live/strategies`.
- Task IDs are different.

Evidence:
- User A task ID and status.
- User B task ID and status.
- Live strategy payloads.

## TEST-4: User Task Isolation

Status: passed in safe, live-safe, and mixed-safe modes

Purpose: prove public APIs do not leak another user's task list.

Steps:
- Query `/api/tasks` as User A.
- Query `/api/tasks` as User B.

Expected result:
- User A response includes User A's task and excludes User B's task.
- User B response includes User B's task and excludes User A's task.

Evidence:
- Redacted JSON payloads.
- Included and excluded task IDs.

## TEST-5: Single User Running Task Guard

Status: passed in safe and live-safe modes

Purpose: prove the single-user running task rule still holds while cross-user concurrency is enabled.

Steps:
- While User A's first live task is still running, User A posts another task to `/api/tasks`.

Expected result:
- The response is `409 Conflict`.
- Existing User A task remains running.

Evidence:
- HTTP status.
- Error detail.
- User A task status after rejection.

## TEST-6: Live And Backtest Cross-User Concurrency

Status: passed in mixed-safe mode

Purpose: prove concurrency is not limited to two live tasks and supports different task types across users without placing real orders.

Setup:
- Stop or restart after TEST-3 so each user has no running task.

Steps:
- User A starts a safe live `TRADER` task with `live_execution_mode=manual_notify`.
- User B starts a `BACK_TRADER` task using local CSV data.
- Poll `/api/tasks` for both users.

Expected result:
- User A live task is accepted and visible to User A.
- User B backtest task is accepted and visible to User B.
- User A does not see User B's backtest.
- User B does not see User A's live task.

Evidence:
- Task IDs.
- Task types or names.
- States observed over the polling window.

## Failure Handling

If a prerequisite fails three times, stop the run and record:
- failing checklist item
- command or HTTP path
- observed status or error
- likely owner: product, acceptance harness, or external dependency
