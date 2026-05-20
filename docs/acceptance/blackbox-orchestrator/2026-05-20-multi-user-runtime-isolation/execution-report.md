---
skill_id: blackbox-acceptance-orchestrator
skill_run_root: docs/acceptance/blackbox-orchestrator/2026-05-20-multi-user-runtime-isolation
workflow_id: 2026-05-20-multi-user-runtime-isolation
source_contract: docs/acceptance/blackbox-orchestrator/2026-05-20-multi-user-runtime-isolation/acceptance-contract.md
status: live-safe-and-mixed-safe-passed
---

# Execution Report

## Evidence Schema

Each executed checklist item must record:

- timestamp with timezone
- server URL and process ID
- database path
- user scope
- public endpoint or operator command
- task IDs
- observed status and expected status
- artifact path for logs or JSON snapshots
- pass, fail, or blocked decision

## Chronology

Black-box acceptance has been executed against a real local server through `uv run python scripts/acceptance/multi_user_runtime_isolation.py`.

## Current Preflight Findings

- `.env` contains `BINANCE_API_KEY_1`, `BINANCE_API_SECRET_1`, `BINANCE_API_KEY_2`, and `BINANCE_API_SECRET_2`.
- `.env` does not currently contain `TRADER_SECRET_KEY`; the harness may inject a run-local service key unless the User prefers adding one to `.env`.
- Migration support for `execution_states.task_id` was added before acceptance execution because the real server relies on `trader-db migrate`.

## Exceptions And Blockers

- Real-order acceptance remains blocked pending explicit User approval. No real-order task was run in this workflow.
- Earlier live-safe attempts exposed startup and exchange-loading issues. Those issues were fixed before the passing `live-safe` and `mixed-safe` runs recorded below.

## Final Decision

Multi-user runtime isolation is accepted for:

- startup tasks bound to the bootstrap admin user
- user A and user B running safe live `TRADER` tasks concurrently with separate Binance credentials
- user A running a safe live `TRADER` task while user B runs a `BACK_TRADER` task
- per-user task-list isolation
- single-user running-task conflict rejection
- per-user task shutdown and persisted `DONE` state

The accepted live path uses `manual_notify` and does not place real orders. Real-order acceptance remains out of scope until explicitly approved.

## Run 2026-05-20 01:32:22 +0800

Evidence artifact: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/evidence.json`

Status: `failed`

Error: `task creation did not return task ids: {
  "http_status": 409,
  "body": "{\"detail\":\"user_id=1 already has a running task\"}"
}`


## Run 2026-05-20 01:43:32 +0800

Evidence artifact: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/evidence.json`

Status: `failed`

Error: `server exited early with code 3`


## Run 2026-05-20 01:45:30 +0800

Evidence artifact: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/evidence.json`

Status: `failed`

Error: `server exited early with code 3`


## Run 2026-05-20 01:52:37 +0800

Evidence artifact: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/evidence.json`

Status: `failed`

Error: `bootstrap administrator default exchange credential was not created`


## Run 2026-05-20 01:54:46 +0800

Evidence artifact: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/evidence.json`

Status: `failed`

Error: `HTTPConnectionPool(host='127.0.0.1', port=1082): Read timed out. (read timeout=20)`


## Run 2026-05-20 02:06:27 +0800

Evidence artifact: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/evidence.json`

Status: `passed`


## Run 2026-05-20 02:07:04 +0800

Evidence artifact: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/evidence.json`

Status: `passed`

Safe-mode evidence summary:

- Server URL: `http://127.0.0.1:60191`
- Database: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/runtime-1779214020.db`
- Startup admin task: `1779214022060`, `user_id=3`, state `RUNNING`
- User A task: `1779214022731`, `user_id=1`, state `RUNNING`, then `DONE` after close
- User B task: `1779214022733`, `user_id=2`, state `RUNNING`, then `DONE` after close
- Duplicate User A task request returned `409 Conflict`
- User A task list excluded User B's task; User B task list excluded User A's task

## Run 2026-05-20 02:16:40 +0800

Evidence artifact: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/evidence.json`

Status: `passed`


## Run 2026-05-20 02:17:57 +0800

Evidence artifact: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/evidence.json`

Status: `passed`


## Run 2026-05-20 02:21:49 +0800

Evidence artifact: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/evidence.json`

Status: `failed`

Error: `task 1779214829301 stayed RUNNING after close; latest={
  "task_id": 1779214829301,
  "state": "RUNNING",
  "name": "1779214829301.TRADER.BTCUSDT-1m",
  "start_time": "2026-05-20 02:20:29",
  "commission": 0.001,
  "strategy_start_time": "2000-01-01 00:00:00",
  "strategy_end_time": "2026-05-20 02:20:29",
  "initial_cash": 10000.0,
  "config_json": "[\n  {\n    \"task_type\": \"TRADER\",\n    \"symbol\": \"BTCUSDT\",\n    \"interval\": \"1m\",\n    \"start_time\": \"2000-01-01 00:00:00\",\n    \"end_time\": \"2026-05-20 02:20:29\",\n    \"strategy\": \"macd_triple_divergence\",\n    \"free\": 10000.0,\n    \"live_execution_mode\": \"manual_notify\",\n    \"live_data_mode\": \"realtime\",\n    \"live_trade_max_notional\": 1.0,\n    \"user_id\": 1\n  }\n]",
  "user_id": 1
}`


## Run 2026-05-20 02:23:57 +0800

Evidence artifact: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/evidence.json`

Status: `failed`

Error: `server did not become ready: HTTP 503`


## Run 2026-05-20 02:26:46 +0800

Evidence artifact: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/evidence.json`

Status: `passed`


## Run 2026-05-20 02:27:39 +0800

Evidence artifact: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/evidence.json`

Status: `passed`

Live-safe evidence summary:

- Mode: `live-safe`
- User A: `user_id=1`, masked key `ECaw***AFgu`
- User B: `user_id=2`, masked key `9pBY***4On2`
- User A and User B both started safe live `TRADER` tasks with `live_execution_mode=manual_notify`.
- Both live tasks reached `RUNNING` and appeared only in the owning user's `/api/live/strategies` response.
- Duplicate User A task request returned `409 Conflict`.
- Both tasks reached `DONE` after shutdown.

## Run 2026-05-20 mixed-safe +0800

Evidence artifact: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/evidence.json`

Status: `passed`

Mixed-safe evidence summary:

- Mode: `mixed-safe`
- User A started a safe live `TRADER` task with `live_execution_mode=manual_notify`.
- User B started a `BACK_TRADER` task.
- Both tasks reached `RUNNING` during the observation window.
- User A did not see User B's backtest task; User B did not see User A's live task.

## Run 2026-05-20 02:32:31 +0800

Evidence artifact: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/evidence.json`

Status: `passed`

Live-safe rerun summary:

- Server URL: `http://127.0.0.1:63107`
- Database: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/runtime-1779215551.db`
- User A: `user_id=1`, masked key `ECaw***AFgu`
- User B: `user_id=2`, masked key `9pBY***4On2`
- User A task `1779215553398` and User B task `1779215562827` both reached `RUNNING`.
- Both tasks used `live_execution_mode=manual_notify` and appeared in only the owning user's live strategy response.
- Duplicate User A task request returned `409 Conflict`.
- Both tasks reached `DONE` after close.

## Run 2026-05-20 02:33:23 +0800

Evidence artifact: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/evidence.json`

Status: `passed`

Mixed-safe rerun summary:

- Server URL: `http://127.0.0.1:63189`
- Database: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/runtime-1779215603.db`
- User A task `1779215606369` was a safe live `TRADER` task and reached `RUNNING`.
- User B task `1779215610504` was a `BACK_TRADER` task and reached `RUNNING`.
- User A saw only User A's live task; User B saw only User B's backtest task.

## Run 2026-05-20 02:33:01 +0800

Evidence artifact: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/evidence.json`

Status: `passed`


## Run 2026-05-20 02:33:30 +0800

Evidence artifact: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/evidence.json`

Status: `passed`

## Run 2026-05-20 02:35:26 +0800

Evidence artifact: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/evidence.json`

Status: `passed`

Safe rerun summary:

- Server URL: `http://127.0.0.1:63375`
- Database: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/runtime-1779215726.db`
- Startup task `1779215727907` was created as `DEBUG`, reached `RUNNING`, and was assigned to administrator `user_id=3`.
- User A task `1779215728338` and User B task `1779215728340` both reached `RUNNING`.
- Duplicate User A task request returned `409 Conflict`.
- User A and User B task lists remained isolated.
- User A and User B tasks reached `DONE` after close.

## Run 2026-05-20 02:35:32 +0800

Evidence artifact: `/Users/tonyoutlier/.warp/worktrees/ChainerTrader/wash-granite/tmp/acceptance/multi_user_runtime_isolation/evidence.json`

Status: `passed`
