---
skill_id: blackbox-acceptance-orchestrator
skill_run_root: docs/acceptance/blackbox-orchestrator/2026-05-24-task-panel-visual-config
workflow_id: 2026-05-24-task-panel-visual-config
source_contract: docs/acceptance/blackbox-orchestrator/2026-05-24-task-panel-visual-config/acceptance-contract.md
status: accepted
---

# Acceptance Contract

## Goal

Verify that `/admin/tasks` provides a complete visual task configuration workflow for all supported task types, with black-box user-observable behavior:

1. No mandatory raw JSON authoring is required to add tasks.
2. All task types are configurable through visible form controls.
3. Batch draft flow supports append, edit-overwrite, remove, and clear.
4. Strategy options are injected from backend and rendered as a selector.
5. Symbol input is validated and normalized.
6. Datetime input uses user-friendly controls while preserving backend payload contract.
7. Users can directly select and run task configs from `configs/tasks/**/*.json`.

## Scope

- HTTP-rendered admin task page (`/admin/tasks`)
- Public task API submission path (`/api/tasks`)
- Server-side page rendering context
- Black-box tests and reports proving externally observable behavior

## Non-Goals

- Strategy profitability correctness
- Exchange-side order execution semantics
- Styling overhaul unrelated to task configuration capabilities

## Roles

- User: acceptance owner and final decision maker
- Project Manager: acceptance orchestration and evidence synchronization
- Development Agent: implementation and fixes (completed in this run)
- Testing Agent: black-box verification by page/API behavior and test artifacts

## Required Resources

- Local repo checkout and Python virtual environment
- `uv` runtime available
- Test runner support for existing FastAPI black-box tests

## Pass Gates

- AC-1: `/admin/tasks` renders visual task form primitives for all task types.
- AC-2: Backend injects strategy options; frontend renders strategy dropdown.
- AC-3: Batch draft features are present and wired (append, edit-overwrite, remove, clear).
- AC-4: Symbol format validation and normalization are enforced before submission.
- AC-5: Datetime controls render as `datetime-local` and convert to backend-compatible format.
- AC-6: Existing task API preflight and ownership behavior remains unchanged.
- AC-7: `/admin/tasks` provides config-file mode that lists `configs/tasks` options and submits selected path directly to `/api/tasks`.

## Failure Classification

- Product defect: missing/incorrect UI behavior, broken payload shape, or API regression.
- Harness gap: test cannot observe required user-visible behavior.
- External dependency gap: local runtime/tooling unavailable.

## Approval Status

Accepted. User approved continuation of this acceptance workflow after document publication and evidence execution.
