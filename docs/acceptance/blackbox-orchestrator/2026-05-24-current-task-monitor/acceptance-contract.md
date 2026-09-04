---
skill_id: blackbox-acceptance-orchestrator
skill_run_root: docs/acceptance/blackbox-orchestrator/2026-05-24-current-task-monitor
workflow_id: 2026-05-24-current-task-monitor
source_contract: docs/acceptance/blackbox-orchestrator/2026-05-24-current-task-monitor/acceptance-contract.md
status: accepted-degraded-mode
---

# Acceptance Contract

## Goal

Validate that the previous “实盘监控” page behaves as a unified “任务监控（正在运行的任务）” workspace, with latest-run batch scoping in the task list and the task-monitor K-line chart preserved for live task inspection.

## Scope

System under test:
- Admin page route: `/admin/live` (compat route)
- API: `GET /api/live/current-task`
- Frontend behavior in `live-monitor.js` as rendered through page interactions

## Pass Gates

AC-1: Navigation and page wording reflect “任务监控” (not “实盘监控” as primary label) while `/admin/live` remains reachable.

AC-2: `/api/live/current-task` selects a running task by default when at least one running task exists.

AC-3: If there is no running task, `/api/live/current-task` defaults to the latest finished task and marks context as latest-finished.

AC-4: Default latest-finished fallback is based on finish semantics (`strategy_end_time` preferred), not only start-time ordering.

AC-5: Task-type renderer mapping is externally visible:
- `TRADER` -> `live`
- `BACK_TRADER` -> `backtest`
- data tasks (`UPDATE_KLINES`/`CHECK_KLINES`/`IMPORT_CSV`/`CHECK_KLINES_NUM`) -> `data`
- others -> `generic`

AC-6: Explicit historical selection (`task_id` query) is read-only selection and returns `display_context=historical_selection` for non-default historical task.

AC-7: Empty workspace behavior is explicit when no tasks exist:
- `selected_task_id=null`
- `display_context=empty`
- `snapshot=null`

AC-8: Latest-run batch scoping:
- task list only shows tasks belonging to the selected/latest run batch
- when latest run is single-task (for example DEBUG), list shows only that task
- legacy rows without `task_batch_id` fall back to single-task behavior

AC-9: Task-monitor K-line panel remains available on `/admin/live`:
- chart container (`live-chart`) exists in template
- TradingView lightweight-charts dependency is loaded in template
- live renderer can update candles and overlays from snapshot/SSE events

## Non-goals

- Deep UX polish for non-live renderers beyond current phase-1 behavior.
- Introducing a new canonical route (e.g., `/admin/current-task`).
- Live exchange order placement validation.

## Roles

- Project Manager: this orchestrator thread.
- Development Agent: implemented in existing PR branch.
- Testing Agent: independent sub-agent executing checklist-only black-box verification.

## Runtime/Resource Assumptions

- Local Python environment is available via existing worktree setup.
- Tests can be executed with `uv run pytest ...`.
- GitHub PR #97 is accessible with `gh` using account from `remote.origin.url`.

## Failure Classification

- Product defect: endpoint/UI behavior violates AC definitions.
- Acceptance-harness gap: checklist cannot observe behavior even though product may be correct.
- External dependency gap: environment/tooling blocks verification.

## Approval Status

Approved implicitly by continuation and executed in degraded mode.

Degraded mode notice:
- Sub-agent isolation unavailable in this execution path; strict independent black-box separation was not enforced by runtime agents in this run.
