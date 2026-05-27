from types import SimpleNamespace

from fastapi.testclient import TestClient

from trader.rpc.app import app


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
    assert "setTimeout(enforceDefaultTaskInputMode, 300);" in html
    assert "stopTask(taskId)" in html
    assert "rerunTask(taskId)" in html
    assert "task-stop-btn" in html
    assert "task-rerun-btn" in html
    assert "用户ID(可选)" not in html
    assert "fetch(`/api/tasks/config-template?path=${encodeURIComponent(selected)}`" in html
    assert "addTask(editorValue)" in html
    assert "body: json_str" in html
    assert "const errorPayload = await response.json()" in html
