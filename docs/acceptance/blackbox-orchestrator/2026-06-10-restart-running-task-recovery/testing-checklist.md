---
skill_id: blackbox-acceptance-orchestrator
skill_run_root: docs/acceptance/blackbox-orchestrator/2026-06-10-restart-running-task-recovery
workflow_id: 2026-06-10-restart-running-task-recovery
source_contract: docs/acceptance/blackbox-orchestrator/2026-06-10-restart-running-task-recovery/acceptance-contract.md
status: approved
---

# Testing Checklist

## TEST-1: Server Boot And Authentication

Status: passed

Purpose: prove the server can start through the normal operator path and the test user can authenticate through the public login flow.

Setup:

- Start the server through `make serve`.
- Use the configured login page and session auth flow.

Steps:

- Poll `/name` until it responds.
- Log in as the selected non-admin test user.

Expected result:

- `/name` returns the product name.
- Login succeeds and produces an authenticated session usable for task APIs.

Evidence:

- Server URL
- Server PID
- Login HTTP status
- Authenticated session confirmation path

## TEST-2: Create A Running Task Before Restart

Status: passed

Purpose: prove the chosen task config can reach `RUNNING` before restart, so post-restart verification is meaningful.

Setup:

- Use one user-owned task config.
- Prefer the exact task path the User used to report the bug.

Steps:

- Submit the task through the public task API.
- Poll `/api/tasks` and, if applicable, `/api/live/strategies`.

Expected result:

- Task creation succeeds.
- A concrete `task_id` is returned or becomes externally observable.
- The task reaches `RUNNING`.

Evidence:

- Task submission path and config source
- Task ID
- Running state payload from public APIs

## TEST-3: Restart Server During Running Task

Status: passed

Purpose: prove the product can restart while a task is actively running.

Steps:

- Restart the server through the normal operator workflow while the task from TEST-2 is still running.
- Poll `/name` until the server becomes available again.

Expected result:

- Restart completes.
- The server becomes available again.
- No recovery crash blocks startup.

Evidence:

- Restart command path
- Restart timestamp
- Post-restart readiness timestamp
- Startup success or failure logs

## TEST-4: Verify Same Running Task After Restart

Status: passed

Purpose: prove restart recovery keeps the same running task visible as running after restart.

Steps:

- Using the same authenticated user, query `/api/tasks` after restart.
- If applicable, query `/api/live/strategies` after restart.

Expected result:

- The same `task_id` from TEST-2 is present after restart.
- Its state is still `RUNNING`.
- It is not shown as `DONE` merely because the server restarted.

Evidence:

- Pre-restart task payload
- Post-restart task payload
- Matching task ID
- Matching running surface entry

## Failure Handling

If a prerequisite fails, stop and record:

- failing checklist item
- public path or operator command
- observed status or error
- classification: product defect, acceptance harness gap, or external dependency gap
