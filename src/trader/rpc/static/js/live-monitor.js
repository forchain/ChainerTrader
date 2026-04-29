(function () {
  const state = {
    strategies: [],
    selectedId: null,
    chart: null,
    candleSeries: null,
    markerApi: null,
    eventSource: null,
    markers: [],
    riskOverlays: [],
    strategyEvents: [],
    priceLines: [],
    eventSequence: 0,
  };

  const el = (id) => document.getElementById(id);

  function isLocalHost() {
    return ["localhost", "127.0.0.1", "::1"].includes(window.location.hostname);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function setConnection(text, tone = "secondary") {
    const node = el("live-connection-state");
    if (!node) return;
    node.className = `badge text-bg-${tone}`;
    node.textContent = text;
  }

  function toChartTime(time) {
    if (time == null) return time;
    if (typeof time === "string") {
      const parsed = Date.parse(time);
      if (!Number.isNaN(parsed)) {
        return Math.floor(parsed / 1000) - new Date(parsed).getTimezoneOffset() * 60;
      }
    }
    return Number(time) - new Date(Number(time) * 1000).getTimezoneOffset() * 60;
  }

  function normalizeCandleForChart(candle) {
    return {
      ...candle,
      raw_time: candle.time,
      time: toChartTime(candle.time),
    };
  }

  function normalizeMarkerForChart(marker) {
    return {
      ...marker,
      raw_time: marker.time,
      time: toChartTime(marker.time),
    };
  }

  async function loadStrategies() {
    const response = await fetch("/api/live/strategies");
    state.strategies = response.ok ? await response.json() : [];
    renderStrategyList();
    if (state.strategies.length > 0) {
      await selectStrategy(state.strategies[0].strategy_id);
    } else {
      el("live-strategy-list").innerHTML = '<div class="text-muted small p-3">暂无运行中的实盘策略</div>';
    }
  }

  function renderStrategyList() {
    const list = el("live-strategy-list");
    if (!list) return;
    list.innerHTML = "";
    state.strategies.forEach((strategy) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `list-group-item list-group-item-action ${strategy.strategy_id === state.selectedId ? "active" : ""}`;
      button.dataset.strategyId = strategy.strategy_id;
      button.innerHTML = `<div class="fw-semibold">${escapeHtml(strategy.symbol)} ${escapeHtml(strategy.interval)}</div>
        <div class="small">${escapeHtml(strategy.strategy_name)}</div>
        <div class="small opacity-75">${escapeHtml(strategy.execution_mode)} · ${escapeHtml(strategy.status)}</div>
        <div class="small opacity-75">任务 #${escapeHtml(strategy.task_id)}</div>`;
      button.addEventListener("click", () => selectStrategy(strategy.strategy_id));
      list.appendChild(button);
    });
  }

  async function selectStrategy(strategyId) {
    state.selectedId = strategyId;
    renderStrategyList();
    closeEventSource();
    const response = await fetch(`/api/live/strategies/${strategyId}/snapshot`);
    if (!response.ok) {
      appendDiagnostic("runtime_status", { error: "snapshot load failed" });
      return;
    }
    const snapshot = await response.json();
    renderSnapshot(snapshot);
    openEventSource(strategyId);
  }

  function renderSnapshot(snapshot) {
    el("active-strategy-title").textContent = `${snapshot.market} ${snapshot.interval}`;
    const paramLabel = snapshot.param_id || snapshot.parameter_fingerprint || "default";
    el("active-strategy-meta").textContent =
      `${snapshot.strategy_name} · ${snapshot.execution_mode} · 任务 #${snapshot.task_id} · 参数 ${paramLabel}`;
    renderStatus({
      ...(snapshot.runtime_status || {}),
      task_id: snapshot.task_id,
      parameter_fingerprint: snapshot.parameter_fingerprint,
    });
    renderStrategyParameters(snapshot);
    ensureChart();
    state.candleSeries.setData((snapshot.candles || []).map(normalizeCandleForChart));
    clearPriceLines();
    state.markers = [];
    state.riskOverlays = [];
    state.strategyEvents = [];
    state.eventSequence = 0;
    renderSnapshotOverlays(snapshot.overlays || {});
    appendDiagnostic("snapshot", {
      loaded: snapshot.history_window.loaded,
      insufficient: snapshot.history_window.insufficient,
      overlays: {
        signals: state.markers.length,
        risk: state.riskOverlays.length,
        strategy_events: state.strategyEvents.length,
      },
      parameter_summary: snapshot.parameter_summary,
      strategy_params: snapshot.strategy_params,
    });
  }

  function renderSnapshotOverlays(overlays) {
    state.markers = (overlays.signals || []).map(signalPayloadToMarker);
    state.riskOverlays = overlays.risk || [];
    state.strategyEvents = overlays.strategy_events || [];
    updateOverlayCounts();
    applyMarkers();
    applyRiskOverlays();
    if (el("overlay-macd")?.checked) {
      state.strategyEvents.forEach((payload) => appendDiagnostic("strategy_event", payload));
    }
  }

  function ensureChart() {
    if (state.chart) return;
    const host = el("live-chart");
    state.chart = LightweightCharts.createChart(host, {
      layout: { background: { color: "#ffffff" }, textColor: "#1f2937" },
      grid: { vertLines: { color: "#eef2f7" }, horzLines: { color: "#eef2f7" } },
      timeScale: { timeVisible: true, secondsVisible: false },
      rightPriceScale: { borderVisible: false },
      height: 520,
    });
    if (state.chart.addCandlestickSeries) {
      state.candleSeries = state.chart.addCandlestickSeries();
    } else {
      state.candleSeries = state.chart.addSeries(LightweightCharts.CandlestickSeries, {});
    }
    window.addEventListener("resize", () => {
      if (host.clientWidth > 0) state.chart.applyOptions({ width: host.clientWidth });
    });
  }

  function openEventSource(strategyId) {
    state.eventSource = new EventSource(`/api/live/strategies/${strategyId}/events`);
    setConnection("streaming", "success");
    state.eventSource.onmessage = (message) => {
      const event = JSON.parse(message.data);
      handleRealtimeEvent(event);
    };
    state.eventSource.onerror = () => setConnection("reconnecting", "warning");
  }

  function closeEventSource() {
    if (state.eventSource) {
      state.eventSource.close();
      state.eventSource = null;
    }
  }

  function handleRealtimeEvent(event) {
    if (event.event_type === "kline_update") {
      const candle = event.payload.candle;
      state.candleSeries.update(normalizeCandleForChart(candle));
    }
    if (event.event_type === "signal_marker") {
      state.markers.push(signalPayloadToMarker(event.payload));
      updateOverlayCounts();
      applyMarkers();
    }
    if (event.event_type === "risk_overlay") {
      state.riskOverlays.push(event.payload);
      updateOverlayCounts();
      applyRiskOverlays();
    }
    if (event.event_type === "macd_divergence") {
      state.strategyEvents.push(event.payload);
      updateOverlayCounts();
      applyMarkers();
      if (el("overlay-macd").checked) appendDiagnostic("strategy_event", event.payload);
    }
    if (event.event_type === "runtime_status") {
      renderStatus(event.payload);
    }
    if (shouldAppendDiagnostic(event)) {
      appendDiagnostic(event.event_type, {
        event_time: event.event_time,
        event_time_text: event.event_time_text,
        ...event.payload,
      });
    }
  }

  function shouldAppendDiagnostic(event) {
    if (event.event_type === "kline_update" && event.payload.closed === false) return false;
    return true;
  }

  function applyMarkers() {
    const markers = [];
    if (el("overlay-signals")?.checked) markers.push(...state.markers.map(normalizeMarkerForChart));
    if (el("overlay-macd")?.checked) {
      state.strategyEvents.forEach((payload) => {
        markers.push(...strategyEventPayloadToMarkers(payload).map(normalizeMarkerForChart));
      });
    }
    if (state.candleSeries.setMarkers) {
      state.candleSeries.setMarkers(markers);
    } else if (state.markerApi) {
      state.markerApi.setMarkers(markers);
    } else if (LightweightCharts.createSeriesMarkers) {
      state.markerApi = LightweightCharts.createSeriesMarkers(state.candleSeries, markers);
    }
  }

  function signalPayloadToMarker(payload) {
    return {
      time: payload.time,
      position: payload.side === "SELL" || payload.side === "SHORT" ? "aboveBar" : "belowBar",
      color: payload.side === "SELL" || payload.side === "SHORT" ? "#dc2626" : "#16a34a",
      shape: payload.side === "SELL" || payload.side === "SHORT" ? "arrowDown" : "arrowUp",
      text: `#${payload.signal_number || state.markers.length + 1} ${payload.side} ${payload.price}`,
    };
  }

  function strategyEventPayloadToMarkers(payload) {
    const metadata = payload.metadata || payload;
    if (Array.isArray(metadata.chart_markers)) return metadata.chart_markers;
    const direction = String(metadata.direction || payload.direction || "").toUpperCase();
    const isShort = direction === "SHORT" || metadata.signal_type === "top_divergence";
    const priceTimeKey = isShort ? "structure_price_high_kline_time" : "structure_price_low_kline_time";
    const priceValueKey = isShort ? "structure_price_high" : "structure_price_low";
    const macdTimeKey = isShort ? "macd_peak_time" : "macd_trough_time";
    const macdValueKey = isShort ? "macd_peak" : "macd_trough";
    const color = isShort ? "#dc2626" : "#2563eb";
    const position = isShort ? "aboveBar" : "belowBar";
    const shape = isShort ? "arrowDown" : "arrowUp";
    const markers = [];
    (metadata.legs || []).forEach((leg, index) => {
      if (leg[priceTimeKey]) {
        markers.push({
          time: leg[priceTimeKey],
          position,
          color,
          shape,
          text: `P${index + 1} ${leg[priceValueKey] ?? ""}`.trim(),
        });
      }
      if (leg[macdTimeKey]) {
        markers.push({
          time: leg[macdTimeKey],
          position,
          color: "#7c3aed",
          shape: "circle",
          text: `M${index + 1} ${leg[macdValueKey] ?? ""}`.trim(),
        });
      }
    });
    return markers;
  }

  function applyRiskOverlays() {
    clearPriceLines();
    if (!el("overlay-risk")?.checked) return;
    state.riskOverlays.forEach(renderRiskOverlay);
  }

  function renderRiskOverlay(payload) {
    if (!state.candleSeries || payload.price == null) return;
    const line = state.candleSeries.createPriceLine({
      price: payload.price,
      color: payload.overlay_type === "stop_loss" ? "#dc2626" : "#2563eb",
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dashed,
      axisLabelVisible: true,
      title: payload.overlay_type,
    });
    state.priceLines.push(line);
  }

  function clearPriceLines() {
    if (!state.candleSeries) return;
    state.priceLines.forEach((line) => state.candleSeries.removePriceLine(line));
    state.priceLines = [];
  }

  function updateOverlayCounts() {
    const counts = {
      "overlay-signals-count": state.markers.length,
      "overlay-risk-count": state.riskOverlays.length,
      "overlay-strategy-events-count": state.strategyEvents.length,
    };
    Object.entries(counts).forEach(([id, count]) => {
      const node = el(id);
      if (node) node.textContent = `(${count})`;
    });
  }

  async function sendDebugManualSignal(kind) {
    if (!state.selectedId) return;
    const button = el(kind === "exit" ? "live-debug-exit" : "live-debug-entry");
    if (button) button.disabled = true;
    try {
      const path = kind === "exit" ? "manual-exit" : "manual-entry";
      const response = await fetch(`/api/live/strategies/${state.selectedId}/debug/${path}`, { method: "POST" });
      const payload = await response.json();
      appendDiagnostic(`debug_${path}`, payload);
    } catch (error) {
      appendDiagnostic("debug_manual_signal", { ok: false, error: error.message });
    } finally {
      if (button) button.disabled = false;
    }
  }

  function renderStatus(status) {
    const node = el("runtime-status");
    node.innerHTML = "";
    Object.entries(status).forEach(([key, value]) => {
      const dt = document.createElement("dt");
      dt.className = "col-5";
      dt.textContent = key;
      const dd = document.createElement("dd");
      dd.className = "col-7 text-end";
      dd.textContent = String(value);
      node.appendChild(dt);
      node.appendChild(dd);
    });
  }

  function renderStrategyParameters(snapshot) {
    const node = el("strategy-parameters");
    if (!node) return;
    const params = snapshot.strategy_params || {};
    const entries = Object.entries(params).sort(([left], [right]) => left.localeCompare(right));
    const paramLabel = snapshot.param_id || snapshot.parameter_fingerprint || "default";
    node.innerHTML = `<div class="live-panel-title mb-2">参数</div>
      <div class="strategy-parameter-summary">ID: ${escapeHtml(paramLabel)}</div>
      <div class="strategy-parameter-grid">
        ${entries.map(([key, value]) => `<div class="strategy-parameter-row">
          <span class="strategy-parameter-key" title="${escapeHtml(key)}">${escapeHtml(key)}</span>
          <span class="strategy-parameter-value">${escapeHtml(value)}</span>
        </div>`).join("")}
      </div>`;
  }

  function formatEventTitle(type) {
    state.eventSequence += 1;
    return `事件 #${state.eventSequence} · ${type}`;
  }

  function appendDiagnostic(type, payload) {
    const box = el("diagnostic-events");
    const row = document.createElement("div");
    row.className = "diagnostic-event";
    row.innerHTML = `<div class="diagnostic-event-title">
      <span class="fw-semibold">${escapeHtml(formatEventTitle(type))}</span>
    </div><pre>${escapeHtml(JSON.stringify(payload, null, 2))}</pre>`;
    box.prepend(row);
    while (box.children.length > 40) box.removeChild(box.lastChild);
  }

  document.addEventListener("DOMContentLoaded", () => {
    if (!document.querySelector("[data-page='live-monitor']")) return;
    el("overlay-signals")?.addEventListener("change", applyMarkers);
    el("overlay-risk")?.addEventListener("change", () => {
      applyRiskOverlays();
    });
    el("overlay-macd")?.addEventListener("change", () => {
      applyMarkers();
      if (el("overlay-macd").checked) state.strategyEvents.forEach((payload) => appendDiagnostic("strategy_event", payload));
    });
    if (isLocalHost()) {
      el("live-debug-panel")?.classList.remove("d-none");
    }
    el("live-debug-entry")?.addEventListener("click", () => sendDebugManualSignal("entry"));
    el("live-debug-exit")?.addEventListener("click", () => sendDebugManualSignal("exit"));
    loadStrategies().catch((error) => {
      setConnection("error", "danger");
      appendDiagnostic("error", { message: error.message });
    });
  });
})();
