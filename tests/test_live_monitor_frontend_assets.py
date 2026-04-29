from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_live_monitor_template_loads_tradingview_lightweight_charts_and_workspace():
    template = (ROOT / "src/trader/rpc/templates/live.html").read_text(encoding="utf-8")

    assert "lightweight-charts" in template
    assert "live-strategy-list" in template
    assert "live-chart" in template
    assert "overlay-signals" in template
    assert "strategy-parameters" in template
    assert "diagnostic-events" in template


def test_live_monitor_javascript_uses_snapshot_sse_and_incremental_candle_updates():
    script = (ROOT / "src/trader/rpc/static/js/live-monitor.js").read_text(encoding="utf-8")

    assert "LightweightCharts" in script
    assert "/api/live/strategies" in script
    assert "EventSource" in script
    assert ".update(" in script
    assert "signal_marker" in script
    assert "risk_overlay" in script
    assert "macd_divergence" in script
    assert "renderSnapshotOverlays(snapshot.overlays || {})" in script


def test_live_monitor_javascript_reuses_marker_api_and_filters_noisy_diagnostics():
    template = (ROOT / "src/trader/rpc/templates/live.html").read_text(encoding="utf-8")
    script = (ROOT / "src/trader/rpc/static/js/live-monitor.js").read_text(encoding="utf-8")

    assert "markerApi" in script
    assert "createSeriesMarkers(state.candleSeries, markers)" in script
    assert "state.markerApi.setMarkers(markers)" in script
    assert "shouldAppendDiagnostic(event)" in script
    assert "event.payload.closed === false" in script
    assert "overlay-signals" in script
    assert "addEventListener(\"change\"" in script
    assert "state.riskOverlays" in script
    assert "state.strategyEvents" in script
    assert "strategyEventPayloadToMarkers" in script
    assert "updateOverlayCounts" in script
    assert "overlay-risk-count" in template


def test_live_monitor_uses_generic_strategy_event_layer_label_and_email_smoke_control():
    template = (ROOT / "src/trader/rpc/templates/live.html").read_text(encoding="utf-8")
    script = (ROOT / "src/trader/rpc/static/js/live-monitor.js").read_text(encoding="utf-8")

    assert "Strategy events" in template
    assert "MACD divergence</label>" not in template
    assert "live-debug-panel" in template
    assert "live-debug-entry" in template
    assert "live-debug-exit" in template
    assert "debug/${path}" in script
    assert "manual-entry" in script
    assert "manual-exit" in script
    assert "sendDebugManualSignal" in script
    assert "isLocalHost" in script


def test_live_monitor_javascript_surfaces_task_and_parameter_identity():
    script = (ROOT / "src/trader/rpc/static/js/live-monitor.js").read_text(encoding="utf-8")

    assert "strategy.task_id" in script
    assert "snapshot.parameter_fingerprint" in script
    assert "snapshot.parameter_summary" in script
    assert "任务 #" in script
    assert "参数" in script
    assert "snapshot.strategy_params" in script
    assert "renderStrategyParameters(snapshot)" in script
    assert "strategy-parameter-summary\">${escapeHtml(snapshot.parameter_summary" not in script


def test_live_monitor_javascript_uses_local_chart_time_and_numbered_events():
    script = (ROOT / "src/trader/rpc/static/js/live-monitor.js").read_text(encoding="utf-8")

    assert "eventSequence" in script
    assert "toChartTime" in script
    assert "getTimezoneOffset() * 60" in script
    assert "formatEventTitle" in script
    assert "事件 #" in script
    assert "normalizeCandleForChart" in script
    assert "normalizeMarkerForChart" in script
    assert "Date.parse(time)" in script
