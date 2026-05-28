(function () {
  const DEFAULT_MAX_CANDLES = 500;

  const state = {
    strategies: [],
    strategiesLoading: false,
    selectedContext: "empty",
    runningTaskId: null,
    renderer: "generic",
    selectedId: null,
    canStream: false,
    chart: null,
    candleSeries: null,
    markerApi: null,
    eventSource: null,
    markers: [],
    riskOverlays: [],
    strategyEvents: [],
    priceLines: [],
    eventSequence: 0,
    candles: [],
    visibleRange: null,
    candleLimit: DEFAULT_MAX_CANDLES,
    candleTimes: [],
  };

  const el = (id) => document.getElementById(id);

  function initialTaskIdFromUrl() {
    const value = new URLSearchParams(window.location.search).get("task_id");
    if (!value) return null;
    const parsed = Number(value);
    return Number.isFinite(parsed) && parsed > 0 ? parsed : null;
  }

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

  function clampRecentCandles(candles) {
    const limit = Math.max(1, Number(state.candleLimit || DEFAULT_MAX_CANDLES));
    if (!Array.isArray(candles) || candles.length === 0) return [];
    if (candles.length <= limit) return candles;
    return candles.slice(-limit);
  }

  function setCandles(candles) {
    state.candles = clampRecentCandles(candles);
    rebuildCandleTimes(state.candles);
    state.candleSeries.setData(state.candles.map(normalizeCandleForChart));
  }

  function upsertCandle(candle) {
    const time = Number(candle?.time);
    if (!Number.isFinite(time)) return;
    const candles = state.candles.slice();
    if (candles.length > 0 && Number(candles[candles.length - 1].time) === time) {
      candles[candles.length - 1] = candle;
    } else {
      candles.push(candle);
    }
    state.candles = clampRecentCandles(candles);
    upsertCandleTime(time);
    state.candleSeries.update(normalizeCandleForChart(candle));
  }

  function normalizeMarkerForChart(marker) {
    const snappedTime = snapMarkerTimeToCandle(marker.time);
    return {
      ...marker,
      raw_time: marker.time,
      time: toChartTime(snappedTime),
    };
  }

  function currentVisibleRange() {
    const range = state.visibleRange;
    if (!range) return null;
    const from = Number(range.from);
    const to = Number(range.to);
    if (!Number.isFinite(from) || !Number.isFinite(to)) return null;
    return { from, to };
  }

  function inVisibleRange(unixTime) {
    const range = currentVisibleRange();
    if (!range) return true;
    const time = Number(unixTime);
    if (!Number.isFinite(time)) return false;
    const chartTime = toChartTime(time);
    return chartTime >= range.from && chartTime <= range.to;
  }

  function rebuildCandleTimes(candles) {
    const unique = new Set();
    (candles || []).forEach((candle) => {
      const t = Number(candle?.time);
      if (Number.isFinite(t)) unique.add(t);
    });
    state.candleTimes = [...unique].sort((a, b) => a - b);
  }

  function upsertCandleTime(candleTime) {
    const t = Number(candleTime);
    if (!Number.isFinite(t)) return;
    if (state.candleTimes.length === 0) {
      state.candleTimes = [t];
      return;
    }
    const last = state.candleTimes[state.candleTimes.length - 1];
    if (t > last) {
      state.candleTimes.push(t);
      return;
    }
    if (t === last || state.candleTimes.includes(t)) return;
    state.candleTimes.push(t);
    state.candleTimes.sort((a, b) => a - b);
  }

  function snapMarkerTimeToCandle(time) {
    const raw = Number(time);
    if (!Number.isFinite(raw) || state.candleTimes.length === 0) return time;
    let left = 0;
    let right = state.candleTimes.length - 1;
    while (left <= right) {
      const mid = Math.floor((left + right) / 2);
      const current = state.candleTimes[mid];
      if (current === raw) return raw;
      if (current < raw) left = mid + 1;
      else right = mid - 1;
    }
    if (right < 0) return state.candleTimes[0];
    return state.candleTimes[right];
  }

  async function loadStrategies() {
    state.strategiesLoading = true;
    renderStrategyList();
    const response = await fetch("/api/live/current-task");
    state.strategiesLoading = false;
    if (!response.ok) {
      state.strategies = [];
      renderStrategyList();
      appendDiagnostic("workspace_error", { error: "current task workspace load failed" });
      return;
    }
    const payload = await response.json();
    state.strategies = payload.tasks || [];
    state.selectedId = payload.selected_task_id || null;
    state.selectedContext = payload.display_context || "empty";
    state.runningTaskId = payload.running_task_id || null;
    state.renderer = payload.renderer || "generic";
    state.canStream = Boolean(payload.can_stream);
    renderStrategyList();
    renderWorkspace(payload.snapshot);
  }

  function renderStrategyList() {
    const list = el("live-strategy-list");
    const runNode = el("live-run-id");
    if (!list) return;
    if (runNode) {
      const first = state.strategies[0];
      const runId = first?.run_id;
      runNode.textContent = runId ? `Run ${runId}` : "";
    }
    if (state.strategiesLoading) {
      list.innerHTML = '<div class="text-muted small p-3">任务列表加载中...</div>';
      return;
    }
    list.innerHTML = "";
    state.strategies.forEach((strategy) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `list-group-item list-group-item-action ${strategy.task_id === state.selectedId ? "active" : ""}`;
      button.dataset.strategyId = strategy.task_id;
      const marker = strategy.is_running ? "运行中" : "历史";
      const rerunDisabled = Boolean(strategy.is_running);
      const rerunLabel = rerunDisabled ? "运行中" : "重新运行";
      const rerunClass = rerunDisabled ? "btn btn-sm btn-outline-secondary disabled live-rerun-task" : "btn btn-sm btn-outline-primary live-rerun-task";
      const symbol = strategy.symbol || "-";
      const interval = strategy.interval || "-";
      const strategyName = strategy.strategy || "-";
      const runBadge = strategy.run_id
        ? `<div class="small opacity-75">Run ${escapeHtml(strategy.run_id)}${
            strategy.run_index && strategy.run_total ? ` · ${escapeHtml(strategy.run_index)}/${escapeHtml(strategy.run_total)}` : ""
          }</div>`
        : "";
      button.innerHTML = `<div class="fw-semibold">任务 #${escapeHtml(strategy.task_id)}</div>
        <div class="small">${escapeHtml(strategy.task_type)}</div>
        <div class="small opacity-75">币种 ${escapeHtml(symbol)} · 周期 ${escapeHtml(interval)} · 策略 ${escapeHtml(strategyName)}</div>
        ${runBadge}
        <div class="small opacity-75">${escapeHtml(marker)} · ${escapeHtml(strategy.state)}</div>
        ${rerunDisabled ? "" : `<div class="mt-2">
          <span class="${rerunClass}" data-task-id="${escapeHtml(strategy.task_id)}" data-rerun-disabled="0">${rerunLabel}</span>
        </div>`}`;
      button.addEventListener("click", () => selectStrategy(strategy.task_id));
      list.appendChild(button);
    });
    if (state.strategies.length === 0) {
      list.innerHTML = '<div class="text-muted small p-3">暂无可展示任务</div>';
    }
  }

  async function selectStrategy(taskId) {
    const response = await fetch(`/api/live/current-task?task_id=${encodeURIComponent(taskId)}`);
    if (!response.ok) {
      appendDiagnostic("runtime_status", { error: "snapshot load failed" });
      return;
    }
    const payload = await response.json();
    state.selectedId = payload.selected_task_id || taskId;
    state.selectedContext = payload.display_context || "historical_selection";
    state.runningTaskId = payload.running_task_id || null;
    state.renderer = payload.renderer || "generic";
    state.canStream = Boolean(payload.can_stream);
    renderStrategyList();
    renderWorkspace(payload.snapshot);
  }

  function renderWorkspace(snapshot) {
    closeEventSource();
    if (!snapshot) {
      renderGenericSnapshot({ name: "暂无任务", state: "EMPTY", task_id: "-" }, "empty");
      return;
    }
    if (state.renderer === "live") {
      renderSnapshot(snapshot);
      if (state.selectedContext === "active_running_task" && state.canStream) {
        openEventSource(state.selectedId || snapshot.task_id);
      }
      return;
    }
    if (state.renderer === "backtest") {
      renderBacktestSnapshot(snapshot);
      return;
    }
    if (state.renderer === "data") {
      renderDataSnapshot(snapshot);
      return;
    }
    renderGenericSnapshot(snapshot, state.renderer);
  }

  function renderSnapshot(snapshot) {
    state.candleLimit = Math.max(1, Number(snapshot?.history_window?.limit || DEFAULT_MAX_CANDLES));
    const marketLabel = snapshot.market ? `${snapshot.market} ${snapshot.interval || ""}`.trim() : `任务 #${snapshot.task_id}`;
    el("active-strategy-title").textContent = marketLabel;
    const paramLabel = snapshot.param_id || snapshot.parameter_fingerprint || "default";
    const displayContextText = state.selectedContext || "active_running_task";
    el("active-strategy-meta").textContent =
      `${snapshot.strategy_name} · ${snapshot.execution_mode} · 任务 #${snapshot.task_id} · 参数 ${paramLabel} · ${displayContextText}`;
    renderStatus({
      ...(snapshot.runtime_status || {}),
      task_id: snapshot.task_id,
      parameter_fingerprint: snapshot.parameter_fingerprint,
    });
    renderStrategyParameters(snapshot);
    ensureChart();
    setCandles(snapshot.candles || []);
    clearPriceLines();
    state.markers = [];
    state.riskOverlays = [];
    state.strategyEvents = [];
    state.eventSequence = 0;
    renderSnapshotOverlays(snapshot.overlays || {});
    appendDiagnostic("snapshot", {
      loaded: snapshot.history_window?.loaded,
      insufficient: snapshot.history_window?.insufficient,
      overlays: {
        signals: state.markers.length,
        risk: state.riskOverlays.length,
        strategy_events: state.strategyEvents.length,
      },
      parameter_summary: snapshot.parameter_summary,
      strategy_params: snapshot.strategy_params,
    });
  }

  function renderBacktestSnapshot(snapshot) {
    if (Array.isArray(snapshot.candles)) {
      renderSnapshot(snapshot);
      return;
    }
    renderGenericSnapshot(snapshot, "backtest");
  }

  function renderDataSnapshot(snapshot) {
    el("active-strategy-title").textContent = `Data 任务 #${snapshot.task_id}`;
    el("active-strategy-meta").textContent = `${state.selectedContext} · ${snapshot.state}`;
    renderStatus(snapshot.runtime_status || { state: snapshot.state, task_type: snapshot.task_type });
    const chart = el("live-chart");
    chart.innerHTML = `<div class="p-3 text-muted small">Data 视图（首期）：显示任务状态、参数和事件。任务名称：${escapeHtml(snapshot.name || "-")}</div>`;
    el("strategy-parameters").innerHTML = `<div class="live-panel-title mb-2">任务配置</div><pre class="small mb-0">${escapeHtml(snapshot.config_json || "{}")}</pre>`;
  }

  function renderGenericSnapshot(snapshot, renderer) {
    el("active-strategy-title").textContent = `任务 #${snapshot.task_id || "-"}`;
    el("active-strategy-meta").textContent = `${state.selectedContext} · ${snapshot.state || "UNKNOWN"} · ${renderer}`;
    renderStatus(snapshot.runtime_status || { state: snapshot.state, task_type: snapshot.task_type });
    const chart = el("live-chart");
    chart.innerHTML = `<div class="p-3 text-muted small">通用任务视图：${escapeHtml(snapshot.name || "-")}</div>`;
    el("strategy-parameters").innerHTML = `<div class="live-panel-title mb-2">任务配置</div><pre class="small mb-0">${escapeHtml(snapshot.config_json || "{}")}</pre>`;
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
    state.chart.timeScale().subscribeVisibleTimeRangeChange((range) => {
      state.visibleRange = range;
      applyMarkers();
      applyRiskOverlays();
    });
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
      upsertCandle(candle);
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
    if (el("overlay-signals")?.checked) {
      markers.push(...state.markers.filter((marker) => inVisibleRange(marker.time)).map(normalizeMarkerForChart));
    }
    if (el("overlay-macd")?.checked) {
      state.strategyEvents.forEach((payload) => {
        markers.push(
          ...strategyEventPayloadToMarkers(payload)
            .filter((marker) => inVisibleRange(marker.time))
            .map(normalizeMarkerForChart)
        );
      });
    }
    if (state.candleSeries.setMarkers) {
      state.candleSeries.setMarkers(markers);
    } else if (state.markerApi) {
      state.markerApi.setMarkers(markers);
    } else if (LightweightCharts.createSeriesMarkers) {
      state.markerApi = LightweightCharts.createSeriesMarkers(state.candleSeries, markers, { zOrder: "top" });
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
    const isShort = direction === "SHORT" || metadata.signal_type === "top_divergence" || metadata.signal_type === "SHORT";
    const priceTimeKey = isShort ? "structure_price_high_kline_time" : "structure_price_low_kline_time";
    const priceValueKey = isShort ? "structure_price_high" : "structure_price_low";
    const macdTimeKey = isShort ? "macd_peak_time" : "macd_trough_time";
    const macdValueKey = isShort ? "macd_peak" : "macd_trough";
    const color = isShort ? "#dc2626" : "#2563eb";
    const position = isShort ? "aboveBar" : "belowBar";
    const shape = isShort ? "arrowDown" : "arrowUp";
    const markers = [];
    (metadata.legs || []).forEach((leg, index) => {
      const priceTime = leg[priceTimeKey] ?? leg.price_kline_time ?? leg.price_time ?? leg.time;
      const priceValue = leg[priceValueKey] ?? leg.price_extreme ?? leg.price;
      const macdTime = leg[macdTimeKey] ?? leg.macd_peak_time ?? leg.macd_trough_time ?? leg.macd_time ?? leg.macd_kline_time;
      const macdValue = leg[macdValueKey] ?? leg.extreme_val ?? leg.macd;
      if (priceTime) {
        markers.push({
          time: priceTime,
          position,
          color,
          shape,
          text: `P${index + 1} ${priceValue != null ? Number(priceValue).toFixed(2) : ""}`.trim(),
        });
      }
      if (macdTime) {
        markers.push({
          time: macdTime,
          position,
          color: "#7c3aed",
          shape: "circle",
          text: `M${index + 1} ${macdValue != null ? Number(macdValue).toFixed(6) : ""}`.trim(),
        });
      }
    });
    return markers;
  }

  function applyRiskOverlays() {
    clearPriceLines();
    if (!el("overlay-risk")?.checked) return;
    state.riskOverlays.filter((payload) => inVisibleRange(payload.time)).forEach(renderRiskOverlay);
  }

  function riskLineStyle() {
    if (LightweightCharts.LineStyle && LightweightCharts.LineStyle.Dashed != null) {
      return LightweightCharts.LineStyle.Dashed;
    }
    return 2;
  }

  function renderRiskOverlay(payload) {
    if (!state.candleSeries || payload.price == null) return;
    const price = Number(payload.price);
    if (!Number.isFinite(price) || price <= 0) {
      appendDiagnostic("risk_overlay_invalid_price", payload);
      return;
    }
    const overlayType = String(payload.overlay_type || "risk");
    const color = overlayType === "stop_loss" ? "#dc2626" : "#2563eb";
    const line = state.candleSeries.createPriceLine({
      price,
      color,
      lineWidth: 1,
      lineStyle: riskLineStyle(),
      axisLabelVisible: true,
      title: overlayType,
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

  async function rerunSelectedTask(taskId) {
    if (!taskId) return;
    const response = await fetch(`/api/live/tasks/${encodeURIComponent(taskId)}/rerun`, { method: "POST" });
    if (!response.ok) {
      let message = `重跑失败：HTTP ${response.status}`;
      try {
        const payload = await response.json();
        if (payload?.detail) message = `重跑失败：${payload.detail}`;
      } catch (_err) {}
      appendDiagnostic("rerun_task", { ok: false, task_id: taskId, error: message });
      return;
    }
    const payload = await response.json();
    appendDiagnostic("rerun_task", { ok: true, task_id: taskId, result: payload });
    await loadStrategies();
  }

  function renderStatus(status) {
    const node = el("runtime-status");
    node.innerHTML = "";
    Object.entries(status).forEach(([key, value]) => {
      const dt = document.createElement("dt");
      dt.className = "col-5";
      dt.textContent = key;
      const dd = document.createElement("dd");
      if (value != null && typeof value === "object") {
        const itemCount = Array.isArray(value) ? value.length : Object.keys(value).length;
        dd.className = "col-7";
        dd.innerHTML = `${escapeHtml(itemCount)} items`;
        const details = document.createElement("details");
        details.className = "mt-1";
        details.innerHTML = `<summary>查看详情</summary>${renderStructuredValue(value, key)}`;
        dd.appendChild(details);
      } else {
        dd.className = "col-7 text-end";
        dd.textContent = String(value);
      }
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

  function renderStructuredValue(value, label = "payload") {
    if (value == null || typeof value !== "object") {
      return `<span>${escapeHtml(value)}</span>`;
    }
    const entries = Array.isArray(value) ? value.map((item, index) => [String(index), item]) : Object.entries(value);
    const isLarge = JSON.stringify(value).length > 240 || entries.length > 5;
    const rows = entries.map(([key, item]) => {
      const rendered = item != null && typeof item === "object"
        ? renderStructuredValue(item, key)
        : `<span class="diagnostic-json-scalar">${escapeHtml(item)}</span>`;
      return `<div class="diagnostic-json-row">
        <span class="diagnostic-json-key">${escapeHtml(key)}</span>
        <div class="diagnostic-json-value">${rendered}</div>
      </div>`;
    }).join("");
    const raw = `<pre>${escapeHtml(JSON.stringify(value, null, 2))}</pre>`;
    return `<details class="diagnostic-json-details" ${isLarge ? "" : "open"}>
      <summary>${escapeHtml(label)}</summary>
      <div class="diagnostic-json-tree">${rows}</div>
      <details class="diagnostic-json-raw">
        <summary>raw JSON</summary>
        ${raw}
      </details>
    </details>`;
  }

  function appendDiagnostic(type, payload) {
    const box = el("diagnostic-events");
    const row = document.createElement("div");
    row.className = "diagnostic-event";
    row.innerHTML = `<div class="diagnostic-event-title">
      <span class="fw-semibold">${escapeHtml(formatEventTitle(type))}</span>
    </div>${renderStructuredValue(payload, type)}`;
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
    el("live-strategy-list")?.addEventListener("click", (event) => {
      const button = event.target.closest(".live-rerun-task");
      if (!button) return;
      event.stopPropagation();
      if (button.dataset.rerunDisabled === "1") {
        appendDiagnostic("rerun_task", { ok: false, task_id: button.dataset.taskId, error: "当前任务正在运行，不能重跑" });
        return;
      }
      rerunSelectedTask(button.dataset.taskId);
    });
    el("live-debug-entry")?.addEventListener("click", () => sendDebugManualSignal("entry"));
    el("live-debug-exit")?.addEventListener("click", () => sendDebugManualSignal("exit"));
    loadStrategies().then(() => {
      const initialTaskId = initialTaskIdFromUrl();
      if (initialTaskId != null) {
        const match = state.strategies.find((item) => Number(item.task_id) === initialTaskId);
        if (match) {
          selectStrategy(match.task_id).catch((error) => {
            setConnection("error", "danger");
            appendDiagnostic("error", { message: error.message });
          });
        }
      }
    }).catch((error) => {
      setConnection("error", "danger");
      appendDiagnostic("error", { message: error.message });
    });
  });
})();
