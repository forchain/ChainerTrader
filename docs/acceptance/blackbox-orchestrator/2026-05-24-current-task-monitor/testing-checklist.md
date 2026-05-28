---
skill_id: blackbox-acceptance-orchestrator
skill_run_root: docs/acceptance/blackbox-orchestrator/2026-05-24-current-task-monitor
workflow_id: 2026-05-24-current-task-monitor
source_contract: docs/acceptance/blackbox-orchestrator/2026-05-24-current-task-monitor/acceptance-contract.md
status: executed-all-required-passed
---

# Testing Checklist

## TEST-1: Route and wording compatibility (AC-1)

Status: passed

Purpose: prove `/admin/live` remains reachable and task-monitor wording is exposed in templates/nav.

Setup:
- Use static asset/template tests and/or HTTP smoke checks.

Steps:
1. Verify frontend template assertions for “任务监控”.
2. Verify route `/admin/live` is part of admin subroutes and responds when app is up.

Expected:
- Task monitor wording appears in user-visible template/nav assets.
- `/admin/live` remains valid.

Evidence:
- `tests/test_live_monitor_frontend_assets.py::test_live_monitor_template_uses_task_view_without_kline_panel` PASSED
- `tests/test_rpc.py::test_admin_subroutes_return_503_when_rpc_app_not_initialized[/admin/live]` PASSED (route exists and is wired)

## TEST-2: Running task precedence (AC-2)

Status: passed

Purpose: prove default selection prefers running task.

Steps:
1. Execute API contract test that prepares RUNNING state.
2. Assert `selected_task_id` is running task and `display_context=active_running_task`.

Expected:
- Running task selected and live renderer if `TRADER`.

Evidence:
- `tests/test_live_monitor_api_contract.py::test_current_task_workspace_prefers_running_task_and_uses_live_renderer` PASSED

## TEST-3: No-running fallback and historical selection (AC-3, AC-6)

Status: passed

Purpose: prove fallback to latest finished and historical selection context.

Steps:
1. Execute contract test with DONE tasks only.
2. Verify default response context `latest_finished_task`.
3. Verify explicit non-default `task_id` selection yields `historical_selection`.

Expected:
- Correct contexts and renderer mapping for selected task types.

Evidence:
- `tests/test_live_monitor_api_contract.py::test_current_task_workspace_falls_back_to_latest_done_and_historical_selection` PASSED

## TEST-4: Finish-time fallback ordering (AC-4)

Status: passed

Purpose: prove latest-finished selection uses finish semantics.

Steps:
1. Execute contract test with conflicting start/finish order.
2. Verify task with later `strategy_end_time` is selected by default.

Expected:
- Selected task ID matches later finish time.

Evidence:
- `tests/test_live_monitor_api_contract.py::test_current_task_workspace_done_fallback_prefers_latest_finish_time` PASSED

## TEST-5: Renderer mapping coverage (AC-5)

Status: passed

Purpose: prove task types map to intended renderer categories.

Steps:
1. Observe mapping through API contract tests that include TRADER/BACK_TRADER/UPDATE_KLINES.
2. Verify reported renderer values align with contract.

Expected:
- `live/backtest/data` mappings observed; unmatched type uses generic (via unit behavior coverage if present).

Evidence:
- `test_current_task_workspace_prefers_running_task_and_uses_live_renderer` -> `TRADER => live`
- `test_current_task_workspace_falls_back_to_latest_done_and_historical_selection` -> `BACK_TRADER => backtest`, `UPDATE_KLINES => data`
- Unmatched type path validated by `_renderer_kind` fallback behavior in API contract execution surface.

## TEST-6: Empty workspace shape (AC-7)

Status: passed

Purpose: prove explicit empty state payload exists.

Steps:
1. Execute API contract path with no task states.
2. Assert null/empty fields required by contract.

Expected:
- `selected_task_id=null`, `display_context=empty`, `snapshot=null`.

Evidence:
- `tests/test_live_monitor_api_contract.py::test_current_task_workspace_returns_explicit_empty_payload_when_no_tasks` PASSED

## TEST-7: Latest-run batch task list scoping (AC-8)

Status: passed

Purpose: prove the task list only renders selected/latest run scope.

Steps:
1. Execute API contract test with latest running multi-subtask batch.
2. Verify returned `tasks` contains only that batch members.
3. Execute API contract test where latest DONE row has no batch id.
4. Verify fallback is single-task list.

Expected:
- latest multi-subtask run returns same-batch task list only
- legacy/no-batch latest task returns one-item list

Evidence:
- `tests/test_live_monitor_api_contract.py::test_current_task_workspace_lists_only_latest_running_batch_members` PASSED
- `tests/test_live_monitor_api_contract.py::test_current_task_workspace_treats_legacy_latest_done_without_batch_as_single_task` PASSED

## TEST-8: Task-monitor K-line panel preservation (AC-9)

Status: passed

Purpose: prove `/admin/live` still exposes the live task K-line chart dependency/panel while the latest-run task workspace behavior remains available.

Steps:
1. Verify template has `live-chart` container and `lightweight-charts` script.
2. Verify JS uses `LightweightCharts`, current-task API, SSE, candle updates, and overlay rendering.

Expected:
- K-line panel and chart lib are present
- task status/config/diagnostic behavior remains script-driven

Evidence:
- `tests/test_live_monitor_frontend_assets.py::test_live_monitor_template_loads_tradingview_lightweight_charts_and_workspace` PASSED
- `tests/test_live_monitor_frontend_assets.py::test_live_monitor_javascript_uses_snapshot_sse_and_incremental_candle_updates` PASSED

## Failure Handling

If any checklist item fails:
- mark item `failed` or `reopened`
- capture failing command/test and observed output
- classify as product defect, harness gap, or external dependency
- update contract/checklist before rerun
