from pathlib import Path

from trader.tools.optimization_workbench_server import build_workbench_url


def test_build_workbench_url_points_to_shared_static_app():
    url = build_workbench_url("http://127.0.0.1:8765", "run-123")

    assert url == (
        "http://127.0.0.1:8765/src/trader/rpc/static/optimization-workbench/index.html"
        "?run_id=run-123"
    )


def test_static_workbench_assets_expect_run_id_and_workbench_json():
    root = Path(__file__).resolve().parents[1]
    index_html = (root / "src" / "trader" / "rpc" / "static" / "optimization-workbench" / "index.html").read_text(encoding="utf-8")
    app_js = (root / "src" / "trader" / "rpc" / "static" / "optimization-workbench" / "app.js").read_text(encoding="utf-8")
    style_css = (root / "src" / "trader" / "rpc" / "static" / "optimization-workbench" / "style.css").read_text(encoding="utf-8")

    assert "Optimization Validation Workbench" in index_html
    assert 'id="candidate-list"' in index_html
    assert 'id="detail-view"' in index_html
    assert 'id="filter-input"' in index_html
    assert 'id="param-filters"' in index_html
    assert 'id="prev-page"' in index_html
    assert 'id="next-page"' in index_html
    assert 'new URLSearchParams(window.location.search).get("run_id")' in app_js
    assert 'fetch(`/reports/optimizations/${runId}/workbench.json`)' in app_js
    assert "window.__WORKBENCH_DATA__" in app_js
    assert "const pageSize = 25;" in app_js
    assert "function renderParamFilters()" in app_js
    assert "function applyFilters()" in app_js
    assert 'trade.report_path || ""' not in app_js
    assert 'item.links.report_paths' in app_js
    assert "function resolveReportHref(path)" in app_js
    assert 'href="${escapeAttr(resolveReportHref(path))}"' in app_js
    assert 'tabButton("parameter_observability", "参数观察")' in app_js
    assert 'tabButton("trade_details", "交易明细")' in app_js
    assert 'tabButton("audit_context", "审计上下文")' in app_js
    assert "function formatStopRange(trade)" in app_js
    assert "${formatStopRange(trade)}" in app_js
    assert "framework_initial_stop_price ?? \"-\"))} →" not in app_js
    assert ".hidden { display: none !important; }" in style_css
