---
skill_id: blackbox-acceptance-orchestrator
skill_run_root: docs/acceptance/blackbox-orchestrator/20260528-current-run-monitor
workflow_id: 20260528-current-run-monitor
source_contract: docs/acceptance/blackbox-orchestrator/20260528-current-run-monitor/acceptance-contract.md
---

# Black-Box Testing Checklist

Testing Agent instruction: This contract is governed by blackbox-acceptance-orchestrator. Use only public UI/API behavior, command outputs, and operator-visible artifacts. Do not inspect implementation files while executing this checklist.

## TEST-01: PR State And Branch Name

Purpose: Prove the review target is the corrected Run monitor branch.

Setup:
- GitHub CLI authenticated as the account required by `origin`.

Steps:
1. Run `git remote get-url origin`.
2. Run `gh auth status -h github.com`.
3. Run `gh pr view 100 --json number,title,headRefName,baseRefName,state,mergeable,url`.

Expected:
- Remote URL identifies `OutlierChainer`.
- Active GitHub CLI account is `OutlierChainer`.
- PR #100 is open, mergeable, based on `main`, and head is `feature/current-run-monitor`.

Evidence:
- Command output copied into execution report.

## TEST-02: Public Template Navigation Smoke

Purpose: Prove user-visible top navigation no longer exposes the standalone K-line entry while keeping task monitor navigation.

Setup:
- Use the running app UI if available; otherwise use a rendered HTML response from the public `/admin` or `/admin/live` route in a test server.

Steps:
1. Open or request an admin page that renders the shared top navigation.
2. Inspect the visible navigation labels.

Expected:
- `任务监控` is visible.
- Standalone `K线` is not visible in the top navigation.
- Do not fail this test merely because `/admin/klines` still exists as a route; route removal is not required.

Evidence:
- Screenshot, response snippet, or automated public-response assertion.

## TEST-03: Monitor Layout Smoke

Purpose: Prove the monitor still exposes the required operator surface.

Setup:
- Open or request `/admin/live`.

Steps:
1. Inspect the monitor layout.

Expected:
- Left Run/task list area is visible.
- Central K-line chart panel exists.
- Right `状态` panel exists.
- Right `诊断事件` panel exists.

Evidence:
- Screenshot, response snippet, or automated public-response assertion.

## TEST-04: Running Run Selection And Batch List

Purpose: Prove a running Run takes priority and batch child runs are listed.

Setup:
- Public API/test server state with at least two running child runs sharing one batch ID, plus an older completed run.

Steps:
1. Request `GET /api/live/current-task`.
2. Inspect JSON response.

Expected:
- `display_context` is `active_running_task`.
- `selected_task_id` is the newest running child run.
- `tasks` contains only the selected batch's child runs.
- Each listed item exposes `task_batch_id` and `is_running`.

Evidence:
- API response or automated public API assertion.

## TEST-05: No Running Run Falls Back To Latest Completed Run

Purpose: Prove idle monitor does not show an empty list when historical runs exist.

Setup:
- Public API/test server state with no running runs and at least two completed runs with different finish times.

Steps:
1. Request `GET /api/live/current-task`.
2. Inspect JSON response.

Expected:
- `display_context` is `latest_finished_task`.
- `selected_task_id` is the latest completed run by finish time.
- `tasks` is non-empty.

Evidence:
- API response or automated public API assertion.

## TEST-06: Multi-Child Latest Run Switching

Purpose: Prove a latest Run that expanded from a JSON array can display and switch child run data.

Setup:
- Public API/test server state where the latest completed batch has at least two child runs.

Steps:
1. Request `GET /api/live/current-task`.
2. Request `GET /api/live/current-task?task_id=<other child run id>`.

Expected:
- Initial response lists all child runs from the latest batch.
- Second response keeps the same batch list.
- Second response changes `selected_task_id` and selected snapshot data to the requested child run.

Evidence:
- API responses or automated public API assertion.

## TEST-07: Standalone Legacy Run Handling

Purpose: Prove legacy runs without batch ID are not accidentally grouped with unrelated runs.

Setup:
- Public API/test server state where the latest completed run has no batch ID and another older run has a batch ID.

Steps:
1. Request `GET /api/live/current-task`.

Expected:
- `tasks` contains exactly the selected legacy run.

Evidence:
- API response or automated public API assertion.

## TEST-08: Backtest Run Chart Snapshot

Purpose: Prove completed or running backtest runs can provide chart data for the central K-line panel.

Setup:
- Public API/test server state with a completed `BACK_TRADER` run, saved config containing symbol/interval, persisted K-line data for that window, and optional result operations.

Steps:
1. Request `GET /api/live/current-task` or select that run by `task_id`.
2. Inspect JSON response.

Expected:
- `renderer` is `backtest`.
- `snapshot.market` and `snapshot.interval` are populated.
- `snapshot.candles` is non-empty when K-line data exists.
- `snapshot.history_window.loaded` matches loaded candle count.
- Optional operation overlays appear in `snapshot.overlays.signals` when result operations exist.

Evidence:
- API response or automated public API assertion.

## TEST-09: Backtest Frontend Uses K-Line Panel

Purpose: Prove backtest data is not rendered as a placeholder text panel when candles are available.

Setup:
- Browser/test harness with `/admin/live` and a selected backtest snapshot containing candles.

Steps:
1. Load monitor page.
2. Select the backtest run if needed.
3. Inspect the central panel.

Expected:
- Central panel renders candlestick chart content.
- It does not show the old placeholder `Backtest 视图（首期）`.

Evidence:
- Screenshot or browser DOM assertion.

## TEST-10: Rerun Action

Purpose: Prove the monitor can restart a displayed run using its saved configuration.

Setup:
- Public API/test server state with a completed run that has `config_json`.

Steps:
1. Click the run's `重新运行` button in the monitor, or call `POST /api/live/tasks/<task_id>/rerun`.
2. Inspect response and operator-visible diagnostic/API result.

Expected:
- Response indicates task submission success.
- Submitted payload uses the selected run's saved config.
- If authenticated, ownership and preflight checks still apply.

Evidence:
- API response, diagnostic entry, or automated public API assertion.

## TEST-11: Existing Live Run Behavior

Purpose: Prove the existing live monitor behavior is not regressed.

Setup:
- Public API/test server state with a running live `TRADER` run and K-line data.

Steps:
1. Request `GET /api/live/current-task`.
2. Inspect response.

Expected:
- `renderer` is `live`.
- Snapshot contains live candles, overlays, runtime status, and task identity fields.

Evidence:
- API response or automated public API assertion.

