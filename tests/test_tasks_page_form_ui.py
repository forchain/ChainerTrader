from types import SimpleNamespace
from pathlib import Path

from fastapi.testclient import TestClient

from trader.rpc.app import app

ROOT = Path(__file__).resolve().parents[1]


def test_admin_tasks_page_renders_visual_task_form_with_strategy_options(monkeypatch):
    async def _fake_current_user(_request):
        return SimpleNamespace(id=1, is_admin=True)

    async def _fake_get_taskinfo(_app, _user, page=1, per_page=None):
        return SimpleNamespace(total=0, completed=0, tasks=[], page=page, per_page=20, total_pages=1)

    monkeypatch.setattr("trader.rpc.app.current_user", _fake_current_user)
    monkeypatch.setattr("trader.rpc.app.get_taskinfo", _fake_get_taskinfo)
    monkeypatch.setattr("trader.rpc.app._list_strategy_options", lambda: ["ShihunRSI2", "MACDRSI"])
    monkeypatch.setattr(
        "trader.rpc.app._list_task_config_options",
        lambda: ["configs/tasks/live/binance_smoke_test.json", "configs/tasks/downloads/update_klines.json"],
    )
    app.state.app = SimpleNamespace()

    client = TestClient(app)
    response = client.get("/admin/tasks")

    assert response.status_code == 200
    html = response.text
    assert "id=\"task_type\"" in html
    assert "id=\"taskDynamicFields\"" in html
    assert "id=\"taskBatchPreview\"" in html
    assert "id=\"taskDraftList\"" in html
    assert "id=\"taskInputMode\"" in html
    assert "<option value=\"config_file\" selected>配置文件</option>" in html
    assert "id=\"taskListFilterType\"" in html
    assert "id=\"taskListFilterSymbol\"" in html
    assert "id=\"taskListFilterInterval\"" in html
    assert "id=\"taskListFilterStrategy\"" in html
    assert "id=\"quickAddForm\" autocomplete=\"off\"" in html
    assert "id=\"taskConfigPath\"" in html
    assert "id=\"taskConfigEditor\"" in html
    assert "id=\"taskConfigFilterType\"" in html
    assert "id=\"taskConfigFilterSymbol\"" in html
    assert "id=\"taskConfigFilterInterval\"" in html
    assert "id=\"taskConfigFilterStrategy\"" in html
    assert "保存任务集" in html
    assert "id=\"saveTaskSetBtn\"" in html
    assert "configs/tasks/live/binance_smoke_test.json" in html
    assert "TASK_CONFIG_OPTIONS = [\"configs/tasks/live/binance_smoke_test.json\", \"configs/tasks/downloads/update_klines.json\"]" in html
    assert "parseTaskConfigPathMeta" in html
    assert "formatTaskConfigOptionLabel" in html
    assert "extractMetaFromTemplateContent" in html
    assert "ensureTaskConfigMetaLoaded" in html
    assert "initTaskConfigPathFilters" in html
    assert "applyTaskConfigPathFilters" in html
    assert "parseTaskItemMeta" in html
    assert "applyTaskListFilters" in html
    assert "initTaskListFilters" in html
    assert "STRATEGY_OPTIONS = [\"ShihunRSI2\", \"MACDRSI\"]" in html
    assert "type=\"datetime-local\"" in html
    assert "覆盖当前草稿" in html
    assert "loadSelectedTaskConfigTemplate" in html
    assert "enforceDefaultTaskInputMode" in html
    assert "window.addEventListener('pageshow'" in html
    assert "TASK_INPUT_MODE_STORAGE_KEY" in html
    assert "readTaskInputMode" in html
    assert "writeTaskInputMode" in html
    assert "setTimeout(enforceDefaultTaskInputMode, 300);" not in html
    assert "当前任务" in html
    assert "JSON.stringify(buildTaskConfigFromForm()[0], null, 2)" in html
    assert "const effectiveTaskSet = taskDrafts.length > 0 ? taskDrafts.slice() : [current];" in html
    assert "stopTask(taskId)" in html
    assert "rerunTask(taskId)" in html
    assert "task-stop-btn" in html
    assert "task-rerun-btn" in html
    assert "用户ID(可选)" not in html
    assert "fetch(`/api/tasks/config-template?path=${encodeURIComponent(selected)}`" in html
    assert "addTask(editorValue)" in html
    assert "body: json_str" in html
    assert "const errorPayload = await response.json()" in html


def test_tasks_page_loads_operation_records_on_demand_in_paginated_modal():
    template = (ROOT / "src/trader/rpc/templates/tasks.html").read_text(encoding="utf-8")

    assert "renderOperationRecordsButton" in template
    assert "id=\"operationRecordsModal\"" in template
    assert "loadOperationRecords" in template
    assert "fetch(`/api/task/${encodeURIComponent(taskId)}/operations?page=${page}&per_page=${OPERATION_RECORDS_PAGE_SIZE}`)" in template
    assert "operationTypeMeta" in template
    assert "'LONG': { className: 'opts-long', label: '做多' }" in template
    assert "'SHORT': { className: 'opts-short', label: '做空' }" in template
    assert "'CLOSE': { className: 'opts-close', label: '平仓' }" in template
    assert "'RISK_UPDATE': { className: 'opts-risk', label: '风控更新' }" in template
    assert "tret.opts.map" not in template


def test_tasks_page_persists_config_file_form_state_before_submit_reload():
    template = (ROOT / "src/trader/rpc/templates/tasks.html").read_text(encoding="utf-8")

    assert "TASK_CONFIG_FORM_STATE_STORAGE_KEY" in template
    assert "writeTaskConfigFormState" in template
    assert "restoreTaskConfigFormState" in template
    assert "writeTaskConfigFormState();" in template
    assert "restoreTaskConfigFormState();" in template
    assert "editor.value = savedState.editorValue || '';" in template
    assert "taskConfigFilterState.type = savedState.filters?.type || '';" in template
    assert "if (savedState.selectedPath && filteredPaths.includes(savedState.selectedPath))" in template
