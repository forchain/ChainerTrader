# Current Task Monitor Design

## Status
Draft

## Date
2026-05-24

## Context
The current web UI exposes a page named `Live Monitoring` / `实盘监控`. That page is useful for live strategy tasks, but live trading is only one task type in ChainerTrader. Users also run backtests, data preparation tasks, and other operational jobs. Treating the page-level concept as live trading makes the navigation and empty state misleading when the user has no running live task or when the active task is not a live strategy.

The product direction is to make this page a task-centered monitoring workspace:

- A task is the top-level runtime concept.
- Live trading is a specialized task renderer, not the whole page.
- The user should see the currently running task when one exists.
- If no task is currently running, the user should see the most recent finished task and its final status.
- Different task types should render interfaces that match their operational shape.

This design builds on the existing FastAPI, Jinja, Bootstrap, and lightweight JavaScript stack. It keeps the current three-column workbench structure because it already maps well to task selection, main task content, and status/event inspection.

## Goals
- Rename the page concept from live monitoring to current task monitoring.
- Keep one unified current task page instead of splitting each task type into a separate route.
- Prefer the current user's running task as the default displayed task.
- When no task is running, default to the user's most recent finished task.
- Show the displayed task's runtime status prominently, including whether it is active, the latest finished run, or a manually selected historical run.
- Render task-type-specific main views for `live`, `backtest`, and `data` tasks.
- Render unsupported or future task types through a generic task detail view.
- Keep historical task selection read-only: selecting a past task changes only what is displayed, not what is running.
- Preserve the existing left/main/right information structure.

## Non-Goals
- A full SPA rewrite.
- A new design system.
- Administrator cross-user task monitoring.
- Process-level runtime isolation.
- Changing task execution semantics.
- Adding new task types.
- Building every future task renderer in the first implementation.
- Removing compatibility for existing `/admin/live` links unless a separate routing decision requires it.

## Product Rules

### Page Concept
The navigation label and page title should describe the page as a current task workspace, not as live trading.

Recommended user-facing wording:

- Navigation: `任务监控`
- Page title: `任务监控`
- Subtitle: `Current task workspace`

The page can still use the existing route initially for compatibility, but the visible concept should be task-centric.

### Default Display Selection
When the page loads, it selects one task for display using this priority:

1. The current user's running task.
2. If no running task exists, the current user's most recently finished `DONE` task.
3. If no `DONE` task exists, an empty state.

The existing runtime rule allows at most one running task per user. If stale data ever exposes more than one running task, the display should choose the running task with the latest `start_time`, then the highest `task_id` as a final tie-breaker, and surface a diagnostic event.

The most recently finished task should be selected by `finished_at` descending, then `start_time` descending, then `task_id` descending. If the current persistence model does not expose `finished_at`, the implementation should add or derive that field in the current-task API contract instead of treating `start_time` as the completion order.

`READY` tasks are not auto-selected because they are not active work and do not represent a finished run. They may appear in history and may be selected manually, in which case the main panel should render them through the appropriate renderer with display context `historical selection` and action availability determined by the backend.

The displayed task can be the active running task, the most recent finished task, or a manually selected historical task. The status and display context must be visible in the top task summary so the user can tell why this task is being shown.

### Historical Task Selection
The left column should include a history list for switching the displayed task.

Historical task selection is read-only:

- Clicking a task changes the displayed task details.
- Clicking a task does not restart it.
- Clicking a task does not make it the running task.
- Clicking a task does not stop or mutate any other task.

Task actions such as stop, rerun, or open report should be explicit controls, not side effects of selection.

History should be ordered by `start_time` descending, then `task_id` descending. It should include recent user-owned tasks regardless of state, including the running task when one exists. The currently displayed task should be visually selected, and the active running task should remain marked even when the user is viewing an older historical task.

### Layout
The page keeps the existing three-column structure:

- Left column: task selection and task-level controls.
- Main column: task-type-specific primary view.
- Right column: status, parameters, events, and diagnostics.

The layout should remain responsive. On narrow screens, the columns can stack in the same order: task controls, main view, status/events.

### Task Type Rendering
The central view should route by task type.

#### Live Task Renderer
The live task renderer should preserve the useful parts of the existing live monitor:

- Price chart.
- Signal overlays.
- Risk lines.
- Strategy events.
- Execution mode and task identity.
- Runtime status.
- Diagnostics.

Live-specific labels should remain inside the live renderer. The page title and navigation should not imply that every displayed task is live trading.

#### Backtest Task Renderer
The backtest renderer should focus on the work shape of a backtest:

- Progress or completion state.
- Stage status.
- Runtime logs or event summaries.
- Final result summary when available.
- Report links or artifacts when available.
- Failure details when the backtest fails.

It should not show live-only controls or empty chart layers.

#### Data Task Renderer
The data renderer should focus on data preparation and coverage:

- Progress or completion state.
- Exchange, symbol, interval, and time range.
- Coverage summary.
- Missing ranges when available.
- Download or preparation errors.
- Produced artifacts or updated ranges when available.

It should not reuse live strategy controls that have no data-task meaning.

#### Generic Task Renderer
Unknown, unsupported, or newly added task types should render through a generic read-only view:

- Task identity.
- Task type.
- Status.
- Created, started, finished, and updated timestamps when available.
- Parameters.
- Recent events or diagnostics.
- Error details when available.

This keeps the page useful while new specialized renderers are added incrementally.

## Interface Boundaries

### Current Task Summary
The top summary should be task-centric and common to every renderer. It should include:

- Task name or fallback task ID.
- Task type.
- Task state: `READY`, `RUNNING`, or `DONE`.
- Result outcome: `success`, `failed`, `canceled`, `skipped`, or `unknown`.
- Display context: active running task, latest finished task, or historical selection.
- Start and finish time when available.

The connection/SSE state can remain visible, but it should be secondary to the displayed task's runtime status.

When the displayed task is historical and a different task is currently running, the shell should still expose the active running task in the left column so the user can return to it without losing the historical view.

### Renderer Contract
The front end should not guess task semantics from arbitrary fields. The server or a small client-side adapter should provide enough structured data for the selected renderer:

- Task metadata.
- Runtime snapshot.
- Parameters.
- Recent events.
- Available actions.
- Renderer kind: `live`, `backtest`, `data`, or `generic`.
- `finished_at`: canonical completion timestamp for `DONE` fallback ordering, or `null` for unfinished tasks.
- `result_outcome`: canonical normalized value derived server-side from task result data or events. Allowed values are `success`, `failed`, `canceled`, `skipped`, and `unknown`. Use `canceled`, not `cancelled`, for UI/API normalization.

The first implementation can map existing task types to renderer kinds in the RPC layer or in a focused JavaScript module, but the mapping should be explicit and tested.

### Actions
Actions should be scoped to the displayed task and should communicate whether they affect runtime state.

Expected initial actions:

- Stop: available only for the current user's running task.
- Rerun: available for `DONE` tasks when the task type supports rerun.
- Open report: available for completed backtest tasks with a report artifact.
- Refresh: available for any displayed task.

Actions that are not available should be hidden or disabled with clear state, following the existing Bootstrap style.

## Empty States

### No Running Task, Has Finished Task
The page should show the most recent `DONE` task as the selected task. The top summary should make the task state visible and, when available, show the backend-provided result outcome to distinguish a successful completion from a failed, canceled, skipped, or unknown outcome.

### No Task History
The page should show an empty state in the main panel:

- No selected task.
- Short message that no task has run yet.
- Link or button to the task creation page if that route already exists.

The left history list should not show live-specific empty copy.

## Error Handling
- If the current task API fails, show a page-level error state and keep the last successfully displayed task if available.
- If a specialized renderer receives incomplete data, it should render the common summary and then show a renderer-level missing-data message instead of failing the whole page.
- If task history cannot be loaded, the main selected task can still render when available, while the history panel shows an error state.
- If a task action fails, show the returned error near the action area and do not mutate the displayed task optimistically unless the backend confirms the change.

## Testing Plan
Automated tests should cover:

- The page title and navigation use current-task wording instead of live-only wording.
- The default task selection prefers a running task.
- The default task selection falls back to the most recently finished `DONE` task when no task is running.
- The `DONE` fallback is ordered by `finished_at` descending, then `start_time` descending, then `task_id` descending.
- The default task selection uses latest `start_time`, then highest `task_id`, if stale data exposes multiple running tasks.
- The empty state appears when the user has no running or `DONE` tasks.
- `READY` tasks are not auto-selected but can be selected manually from history.
- Historical task selection changes only the displayed task.
- Historical task selection shows a distinct historical display context.
- `result_outcome` is provided by the backend contract as one of `success`, `failed`, `canceled`, `skipped`, or `unknown`, and is not inferred by renderer-specific JavaScript.
- The history list is ordered by `start_time` descending, then `task_id` descending.
- `live` tasks render the live task renderer.
- `backtest` tasks render the backtest renderer.
- `data` tasks render the data renderer.
- Unknown task types render the generic renderer.
- Stop actions are available only for the current user's running task.
- Completed task status is visible when displaying the fallback task.

Targeted tests should extend the existing RPC and frontend asset tests rather than adding a separate browser framework unless interaction complexity requires it.

## Rollout Plan
Implement in focused slices:

1. Establish the current task API contract.
   - Add or adapt an endpoint that returns the selected task, task history, renderer kind, runtime snapshot, events, and available actions.
   - Cover running-task preference, stale multi-running tie-breaks, `finished_at`-ordered `DONE` fallback, and canonical `result_outcome` values in tests.

2. Rename the visible page concept.
   - Update navigation, page title, empty copy, and common labels.
   - Keep compatibility route behavior unless explicitly changed later.

3. Extract the common current task shell.
   - Keep left/main/right layout.
   - Move live-only labels and controls into live-specific rendering.

4. Add renderer routing.
   - Preserve the existing live monitor behavior through the `live` renderer.
   - Add initial `backtest`, `data`, and `generic` renderers with focused read-only content.

5. Add task history switching.
   - Let users switch the displayed task without mutating runtime state.
   - Keep running task status visible when the selected task is historical.

6. Verify and document.
   - Run targeted automated tests.
   - Update user-facing docs only if navigation, operation, or exposed behavior changes enough to affect the user manual or README responsibilities.

## Open Decisions
- Whether the route should remain `/admin/live` as a compatibility path or gain a new canonical route such as `/admin/current-task`.
- Whether backtest and data task artifacts already have stable URLs or need a separate artifact-link contract.
- Whether rerun should be in scope for the first implementation or deferred until the display-only view is stable.
