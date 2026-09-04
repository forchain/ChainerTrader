---
skill_id: blackbox-acceptance-orchestrator
skill_run_root: docs/acceptance/blackbox-orchestrator/2026-05-24-task-panel-visual-config
workflow_id: 2026-05-24-task-panel-visual-config
source_contract: docs/acceptance/blackbox-orchestrator/2026-05-24-task-panel-visual-config/acceptance-contract.md
status: accepted
---

# Testing Checklist

## TEST-1: Visual Form Replaces Raw JSON-Only Entry

Status: passed

Purpose: prove users can configure tasks from visible controls instead of mandatory free-form JSON input.

Setup:
- Request `/admin/tasks` as authenticated admin context in black-box HTTP test.

Steps:
1. Load page response.
2. Assert task type selector and dynamic field container exist.
3. Assert JSON preview and batch preview textareas exist.

Expected result:
- Page contains `task_type`, `taskDynamicFields`, `taskJsonPreview`, and `taskBatchPreview`.

Evidence:
- `tests/test_tasks_page_form_ui.py::test_admin_tasks_page_renders_visual_task_form_with_strategy_options`

## TEST-2: Strategy Options Render From Backend Injection

Status: passed

Purpose: prove backend-provided strategy list is exposed on page and consumed by frontend selector logic.

Setup:
- Monkeypatch backend strategy provider with deterministic list.

Steps:
1. Render `/admin/tasks`.
2. Verify embedded `STRATEGY_OPTIONS` JavaScript payload includes injected values.

Expected result:
- Embedded payload includes exact patched strategy names.

Evidence:
- same test as TEST-1; assert on `STRATEGY_OPTIONS = ["ShihunRSI2", "MACDRSI"]`

## TEST-3: Batch Draft Interaction Surfaces Are Present

Status: passed

Purpose: prove users can discover and use batch draft management affordances.

Steps:
1. Render `/admin/tasks`.
2. Assert presence of `appendDraftBtn`, `clearDraftsBtn`, and `taskDraftList`.
3. Assert edit-overwrite label text is present in page script.

Expected result:
- Batch controls and draft list container are present.
- Script includes overwrite mode text (`覆盖当前草稿`).

Evidence:
- `tests/test_tasks_page_form_ui.py`

## TEST-4: Datetime Input Uses User-Friendly Control

Status: passed

Purpose: prove start/end time use dedicated datetime controls to reduce format errors.

Steps:
1. Render `/admin/tasks`.
2. Assert `type="datetime-local"` exists in page output.

Expected result:
- Datetime-local inputs exist for time fields.

Evidence:
- `tests/test_tasks_page_form_ui.py`

## TEST-5: API Contract Safety Regression

Status: passed

Purpose: prove task API guardrails are unchanged by UI work.

Steps:
1. Run existing preflight and ownership regression tests.
2. Verify auth, conflict, and ownership checks still pass.

Expected result:
- All targeted existing tests pass.

Evidence:
- `tests/test_rpc_task_preflight.py`
- `tests/test_task_ownership.py`
- `tests/test_config.py`

## TEST-6: Pagination Surface Unchanged

Status: passed

Purpose: prove task list page behavior unrelated to form still works.

Steps:
1. Run tasks pagination tests.

Expected result:
- Pagination links and slicing behavior still pass.

Evidence:
- `tests/test_tasks_pagination.py`

## TEST-7: Config File Selection And Direct Run Path

Status: passed

Purpose: prove users can switch to config-file mode, see `configs/tasks` options, and use selected path as task submission input.

Steps:
1. Render `/admin/tasks` with deterministic backend config-file list.
2. Assert mode selector and config-file selector exist.
3. Assert embedded `TASK_CONFIG_OPTIONS` payload includes provided file paths.

Expected result:
- Page contains `taskInputMode`, `taskConfigPath`.
- Script includes backend-provided config paths for direct submission.

Evidence:
- `tests/test_tasks_page_form_ui.py::test_admin_tasks_page_renders_visual_task_form_with_strategy_options`
