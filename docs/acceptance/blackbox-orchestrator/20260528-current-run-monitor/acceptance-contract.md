---
skill_id: blackbox-acceptance-orchestrator
skill_run_root: docs/acceptance/blackbox-orchestrator/20260528-current-run-monitor
workflow_id: 20260528-current-run-monitor
source_contract: docs/acceptance/blackbox-orchestrator/20260528-current-run-monitor/acceptance-contract.md
system_under_test: ChainerTrader PR #100
mode: existing implementation acceptance
orchestration_mode: sub-agent-isolated
---

# Acceptance Contract: Current Run Monitor

## Goal

Accept PR #100, `feat: monitor current run workspace`, from a user-visible perspective. The task monitor must behave as a current Run monitor, not only a live-trading task monitor.

## Scope

- The `/admin/live` page and `/api/live/current-task` workspace behavior.
- Run grouping by batch ID when a JSON task launch expands into multiple child runs.
- Historical fallback when there is no running run.
- Backtest and live run rendering in the central K-line panel.
- Run rerun action from the monitor list.
- Navigation behavior for the standalone K-line page link.

## Non-Goals

- Replacing the existing full task list page.
- Removing the `/admin/klines` route or K-line data page.
- Real exchange order placement.
- Full end-to-end browser validation with a production database unless a runnable environment is explicitly provided.

## Roles

- User: owns acceptance decision and approval to run the black-box checklist.
- Project Manager: maintains this contract, checklist, and execution report.
- Development Agent: adjusts implementation only if acceptance fails.
- Testing Agent: validates only externally observable behavior from approved checklist.

## Runtime Capability Disclosure

Sub-agent capability is available. Black-box checklist execution must be delegated to a Testing Agent sub-agent that receives only this contract, the testing checklist, public setup instructions, and allowed evidence paths.

User approval is required before handing the checklist to the Testing Agent.

## Acceptance Criteria

- AC-01: The top navigation does not show a standalone `K线` entry, while `任务监控` remains visible.
- AC-02: The task monitor page preserves the central K-line chart panel and the right-side status/diagnostic panels.
- AC-03: If at least one run is running, the monitor selects the newest running run and lists only that run's batch members.
- AC-04: If no run is running, the monitor selects the latest completed run.
- AC-05: If the selected latest run belongs to a batch with multiple child runs, the monitor list shows those child runs and switching a child run changes the selected run data.
- AC-06: If the selected latest run is standalone or legacy without a batch ID, the monitor list shows only that run.
- AC-07: Completed or running backtest runs can render chart data in the central K-line panel when K-line data exists.
- AC-08: Live trading runs continue to render the live K-line panel, overlays, runtime status, and debug controls as before.
- AC-09: Each displayed run exposes a user-visible rerun action that submits the saved run configuration through the public API.
- AC-10: PR #100 uses the corrected branch name `feature/current-run-monitor`, is open, and is mergeable.

## Pass Gates

- All required checklist items pass, or the User explicitly accepts a documented exception.
- Execution evidence is recorded in `execution-report.md`.
- No checklist item relies solely on code inspection as proof of user-visible behavior.

## Failure Classification

- Product defect: user-visible behavior contradicts an acceptance criterion.
- Acceptance harness gap: the implementation may be correct, but the approved black-box method cannot observe it.
- External dependency gap: verification requires unavailable database, credentials, browser session, or service state.
