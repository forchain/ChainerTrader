---
skill_id: blackbox-acceptance-orchestrator
skill_run_root: docs/acceptance/blackbox-orchestrator/2026-06-10-restart-running-task-recovery
workflow_id: 2026-06-10-restart-running-task-recovery
source_contract: docs/acceptance/blackbox-orchestrator/2026-06-10-restart-running-task-recovery/acceptance-contract.md
status: passed
---

# Execution Report

## Evidence Schema

Each executed checklist item must record:

- timestamp with timezone
- server URL and process ID
- user scope
- public endpoint or operator command
- task ID
- observed status and expected status
- artifact path for any saved response bodies or screenshots
- pass, fail, or blocked decision

## Planned Execution Mode

Black-box execution will validate:

- authenticated task creation
- pre-restart running state
- server restart
- post-restart running state with the same task identity

## Current Status

Passed.

## Exceptions And Blockers

- Initial black-box run was blocked by acceptance-environment contamination: inherited startup tasks triggered exchange startup work before the restart scenario began.
- A real product defect was discovered during black-box execution: `/api/tasks` returned `500 Internal Server Error` because `send_add_tasks_msg()` referenced `new_add_tasks_msg` after its import had been removed. This was fixed before the successful rerun.

## Final Decision

Accepted.

The required user-visible behavior is proven: a non-admin user's running live task remained `RUNNING` after a full server restart, and the same `task_id` remained visible on both the task list and live strategy surfaces.

## Run 2026-06-10 21:33:25 +0800

Status: `passed`

Checklist coverage:

- `TEST-1` Server Boot And Authentication: passed
- `TEST-2` Create A Running Task Before Restart: passed
- `TEST-3` Restart Server During Running Task: passed
- `TEST-4` Verify Same Running Task After Restart: passed

Execution evidence:

- Server URL: `http://127.0.0.1:65489`
- User scope: `restart_accept_1781098350`
- Pre-restart server PID: `33857`
- Post-restart server PID: `34254`
- Task source: `configs/tasks/live/manual_notify_btc_1m.json`
- Task ID before restart: `1781098369964`
- Task ID after restart: `1781098369964`
- Pre-restart task state: `RUNNING`
- Post-restart task state: `RUNNING`
- Pre-restart live strategy visible: `true`
- Post-restart live strategy visible: `true`
- Same task ID stayed running after restart: `true`

Public verification paths used:

- `GET /name`
- `POST /register`
- `POST /login`
- `POST /account/exchange-credentials`
- `POST /api/tasks`
- `GET /api/tasks`
- `GET /api/live/strategies`

Observed task payload before restart:

```json
{
  "task_id": 1781098369964,
  "state": "RUNNING",
  "name": "1781098369964.TRADER.BTCUSDT-1m",
  "user_id": 2
}
```

Observed task payload after restart:

```json
{
  "task_id": 1781098369964,
  "state": "RUNNING",
  "name": "1781098369964.TRADER.BTCUSDT-1m",
  "user_id": 2
}
```
