(async function () {
  const runId = new URLSearchParams(window.location.search).get("run_id");
  const embeddedWorkbench = window.__WORKBENCH_DATA__ || null;
  const filterInput = document.getElementById("filter-input");
  const symbolFilter = document.getElementById("symbol-filter");
  const intervalFilter = document.getElementById("interval-filter");
  const paramFilters = document.getElementById("param-filters");
  const sortSelect = document.getElementById("sort-select");
  const runMeta = document.getElementById("run-meta");
  const summaryGrid = document.getElementById("summary-grid");
  const candidateList = document.getElementById("candidate-list");
  const candidateCount = document.getElementById("candidate-count");
  const detailEmpty = document.getElementById("detail-empty");
  const detailView = document.getElementById("detail-view");
  const prevPageButton = document.getElementById("prev-page");
  const nextPageButton = document.getElementById("next-page");
  const pageIndicator = document.getElementById("page-indicator");
  const pageSize = 25;

  if (!runId && !embeddedWorkbench) {
    detailEmpty.textContent = "缺少 run_id 参数。";
    return;
  }

  let workbench = embeddedWorkbench;
  if (!workbench) {
    const response = await fetch(`/reports/optimizations/${runId}/workbench.json`);
    if (!response.ok) {
      detailEmpty.textContent = `无法加载 run 数据：${response.status}`;
      return;
    }
    workbench = await response.json();
  }
  const state = {
    items: workbench.items || [],
    filteredItems: workbench.items || [],
    selectedRank: (workbench.items[0] || {}).rank || null,
    activeTab: "parameter_observability",
    activeSampleId: ((workbench.items[0] || {}).samples || [])[0]?.sample_id || null,
    symbolFilter: "",
    intervalFilter: "",
    activeFilters: {},
    currentPage: 1,
    sortMode: "return_desc",
  };

  renderSummary(workbench);
  renderDimensionFilters();
  renderParamFilters();
  renderCandidates();
  renderDetail();

  filterInput.addEventListener("input", () => {
    applyFilters();
  });

  if (sortSelect) {
    sortSelect.value = state.sortMode;
    sortSelect.addEventListener("change", () => {
      state.sortMode = sortSelect.value || "score_desc";
      state.currentPage = 1;
      renderCandidates();
    });
  }

  if (symbolFilter) {
    symbolFilter.addEventListener("change", () => {
      state.symbolFilter = symbolFilter.value;
      applyFilters();
    });
  }

  if (intervalFilter) {
    intervalFilter.addEventListener("change", () => {
      state.intervalFilter = intervalFilter.value;
      applyFilters();
    });
  }

  prevPageButton.addEventListener("click", () => {
    if (state.currentPage <= 1) return;
    state.currentPage -= 1;
    renderCandidates();
  });

  nextPageButton.addEventListener("click", () => {
    const totalPages = Math.max(1, Math.ceil(state.filteredItems.length / pageSize));
    if (state.currentPage >= totalPages) return;
    state.currentPage += 1;
    renderCandidates();
  });

  function renderDimensionFilters() {
    if (!symbolFilter || !intervalFilter) return;
    renderSelectOptions(symbolFilter, "币种", uniqueValues("symbol"));
    renderSelectOptions(intervalFilter, "周期", uniqueValues("interval"));
  }

  function uniqueValues(key) {
    return [...new Set(state.items.map((item) => item[key]).filter(Boolean))]
      .map(String)
      .sort((a, b) => a.localeCompare(b, "zh-Hans-CN", { numeric: true }));
  }

  function renderSelectOptions(select, label, values) {
    select.innerHTML = `
      <option value="">${escapeHtml(label)}: 全部</option>
      ${values.map((value) => `<option value="${escapeAttr(value)}">${escapeHtml(value)}</option>`).join("")}
    `;
  }

  function renderParamFilters() {
    const valuesByKey = new Map();
    state.items.forEach((item) => {
      Object.entries(item.params || {}).forEach(([key, value]) => {
        if (!valuesByKey.has(key)) valuesByKey.set(key, new Set());
        valuesByKey.get(key).add(String(value));
      });
    });

    const keys = [...valuesByKey.keys()].sort();
    paramFilters.innerHTML = keys.map((key) => {
      const options = [...valuesByKey.get(key)].sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
      return `
        <label>
          <select data-param-key="${escapeAttr(key)}">
            <option value="">${escapeHtml(shortName(key))}: 全部</option>
            ${options.map((value) => `<option value="${escapeAttr(value)}">${escapeHtml(value)}</option>`).join("")}
          </select>
        </label>
      `;
    }).join("");

    paramFilters.querySelectorAll("select").forEach((node) => {
      node.addEventListener("change", () => {
        const key = node.dataset.paramKey;
        const value = node.value;
        if (!value) delete state.activeFilters[key];
        else state.activeFilters[key] = value;
        applyFilters();
      });
    });
  }

  function applyFilters() {
    const needle = filterInput.value.trim().toLowerCase();
    state.filteredItems = state.items.filter((item) => {
      if (state.symbolFilter && item.symbol !== state.symbolFilter) return false;
      if (state.intervalFilter && item.interval !== state.intervalFilter) return false;
      const haystack = [
        item.symbol,
        item.interval,
        item.strategy,
        item.param_id,
      ].join(" ").toLowerCase();
      if (!haystack.includes(needle)) return false;
      return Object.entries(state.activeFilters).every(([key, value]) => String((item.params || {})[key]) === value);
    });
    state.currentPage = 1;
    if (!state.filteredItems.some((item) => item.rank === state.selectedRank)) {
      state.selectedRank = (state.filteredItems[0] || {}).rank || null;
      state.activeSampleId = ((state.filteredItems[0] || {}).samples || [])[0]?.sample_id || null;
    }
    renderCandidates();
    renderDetail();
  }

  function renderSummary(payload) {
    const blockers = (payload.run.blockers || []).join(", ") || "无";
    runMeta.textContent = `run_id: ${payload.run.run_id} | 状态: ${payload.run.status} | 阻断: ${blockers}`;
    const stats = [
      ["完成样本", payload.summary.completed_samples],
      ["失败", payload.summary.failed_samples],
      ["跳过/超时", payload.summary.skipped_samples + payload.summary.timed_out_samples],
      ["未分类退出率", formatPct(payload.summary.unclassified_exit_rate)],
      ["可疑簇", payload.summary.cluster_count],
      ["候选数", payload.summary.shortlist_count],
    ];
    summaryGrid.innerHTML = stats.map(([label, value]) => `
      <article class="stat">
        <div class="stat-label">${escapeHtml(String(label))}</div>
        <div class="stat-value">${escapeHtml(String(value))}</div>
      </article>
    `).join("");
  }

  function renderCandidates() {
    const sortedItems = sortItems(state.filteredItems, state.sortMode);
    const totalPages = Math.max(1, Math.ceil(state.filteredItems.length / pageSize));
    state.currentPage = Math.min(state.currentPage, totalPages);
    const start = (state.currentPage - 1) * pageSize;
    const visibleItems = sortedItems.slice(start, start + pageSize);
    candidateCount.textContent = `显示 ${state.filteredItems.length} / ${state.items.length}`;
    pageIndicator.textContent = `第 ${state.currentPage} / ${totalPages} 页`;
    prevPageButton.disabled = state.currentPage <= 1;
    nextPageButton.disabled = state.currentPage >= totalPages;
    candidateList.innerHTML = visibleItems.map((item) => {
      const observationSummary = summarizeObservations(item.parameter_observations || []);
      const winRate = (item.summary || {}).avg_win_rate_pct;
      const winRateText = (winRate === null || winRate === undefined) ? "" : ` | 胜率 ${formatPct(winRate)}`;
      const openTradeText = item.summary.open_trades ? ` | 未平仓 ${item.summary.open_trades}` : "";
      return `
        <article class="candidate ${item.rank === state.selectedRank ? "active" : ""}" data-rank="${escapeAttr(String(item.rank))}">
          <div class="candidate-top">
            <div class="candidate-title">#${item.rank} ${escapeHtml(item.symbol)} / ${escapeHtml(item.interval)}</div>
            <div class="candidate-score">${formatNumber(item.score)}</div>
          </div>
          <div class="candidate-meta">
            收益 ${formatPct(item.summary.avg_total_return_pct)} | 拿住 ${formatPct(item.summary.avg_hold_return_pct)} | 超额 ${formatPct(item.summary.avg_excess_return_pct)} | 持仓回撤 ${formatPct(item.summary.avg_max_dd_pct)} | 交易 ${item.summary.total_trades}${openTradeText}${winRateText}
          </div>
          <div class="candidate-observation">
            ${escapeHtml(observationSummary)}<br>
            ${escapeHtml(item.param_id)}
          </div>
        </article>
      `;
    }).join("");

    candidateList.querySelectorAll(".candidate").forEach((node) => {
      node.addEventListener("click", () => {
        state.selectedRank = Number(node.dataset.rank);
        const selected = getSelectedItem();
        state.activeSampleId = ((selected || {}).samples || [])[0]?.sample_id || null;
        state.activeTab = "parameter_observability";
        renderCandidates();
        renderDetail();
      });
    });
  }

  function renderDetail() {
    const item = getSelectedItem();
    if (!item) {
      detailView.classList.add("hidden");
      detailEmpty.classList.remove("hidden");
      return;
    }

    detailEmpty.classList.add("hidden");
    detailView.classList.remove("hidden");
    detailView.innerHTML = `
      <section class="detail-head">
        <h2>${escapeHtml(item.symbol)} / ${escapeHtml(item.interval)} / ${escapeHtml(item.strategy)}</h2>
        <div class="detail-sub">
          <span>param_id: ${escapeHtml(item.param_id)}</span>
          <span>score: ${formatNumber(item.score)}</span>
          <span>收益: ${formatPct(item.summary.avg_total_return_pct)}</span>
          <span>拿住: ${formatPct(item.summary.avg_hold_return_pct)}</span>
          <span>超额: ${formatPct(item.summary.avg_excess_return_pct)}</span>
          <span>持仓回撤: ${formatPct(item.summary.avg_max_dd_pct)}</span>
          <span>全程回撤: ${formatPct(item.summary.avg_full_max_dd_pct)}</span>
          <span>交易数: ${item.summary.total_trades}</span>
          ${item.summary.open_trades ? `<span>未平仓: ${item.summary.open_trades}</span>` : ""}
          ${renderWinRate(item)}
        </div>
      </section>
      <section class="pill-row">
        ${(item.parameter_observations || []).map((obs) => `<span class="pill ${pillClass(obs.status)}">${escapeHtml(shortName(obs.parameter))}: ${escapeHtml(statusLabel(obs.status))}</span>`).join("")}
      </section>
      <section>
        <div class="tabs">
          ${tabButton("parameter_observability", "参数观察")}
          ${tabButton("trade_details", "交易明细")}
          ${tabButton("audit_context", "审计上下文")}
        </div>
        <div class="detail-body">${renderActiveTab(item)}</div>
      </section>
    `;

    detailView.querySelectorAll(".tab").forEach((node) => {
      node.addEventListener("click", () => {
        state.activeTab = node.dataset.tab;
        renderDetail();
      });
    });

    detailView.querySelectorAll(".sample-button").forEach((node) => {
      node.addEventListener("click", () => {
        state.activeSampleId = node.dataset.sampleId;
        renderDetail();
      });
    });
  }

  function renderActiveTab(item) {
    if (state.activeTab === "trade_details") {
      return renderTradeDetails(item);
    }
    if (state.activeTab === "audit_context") {
      return renderAuditContext(item);
    }
    return renderObservations(item);
  }

  function renderObservations(item) {
    return `
      <section class="observation-list">
        ${(item.parameter_observations || []).map((obs) => `
          <article class="observation">
            <div class="observation-head">
              <div class="observation-name">${escapeHtml(shortName(obs.parameter))} = ${escapeHtml(String(obs.value))}</div>
              <span class="pill ${pillClass(obs.status)}">${escapeHtml(statusLabel(obs.status))}</span>
            </div>
            <div class="observation-evidence">
              ${(obs.evidence || []).map((line) => `<span>${escapeHtml(line)}</span>`).join("")}
            </div>
          </article>
        `).join("")}
      </section>
    `;
  }

  function formatStopRange(trade) {
    const initialStop = trade.framework_initial_stop_price;
    const finalStop = trade.framework_final_stop_price;
    if (initialStop == null && finalStop == null) {
      return "SL: -";
    }
    if (initialStop == null) {
      return `SL: ${escapeHtml(String(finalStop))}`;
    }
    if (finalStop == null) {
      return `SL: ${escapeHtml(String(initialStop))}`;
    }

    const initialNumber = Number(initialStop);
    const finalNumber = Number(finalStop);
    const sameStop = Number.isFinite(initialNumber) && Number.isFinite(finalNumber)
      ? Math.abs(initialNumber - finalNumber) < 1e-9
      : String(initialStop) === String(finalStop);
    if (sameStop) {
      return `SL: ${escapeHtml(String(initialStop))}`;
    }
    return `SL: ${escapeHtml(String(initialStop))} → ${escapeHtml(String(finalStop))}`;
  }

  function renderTradeDetails(item) {
    const samples = item.samples || [];
    const activeSampleId = state.activeSampleId || (samples[0] || {}).sample_id;
    const selectedSample = samples.find((sample) => sample.sample_id === activeSampleId) || samples[0];
    const trades = (item.trades || []).filter((trade) => !selectedSample || trade.report_path === selectedSample.report_path);
    return `
      ${(samples.length > 1) ? `
        <div class="sample-switcher">
          ${samples.map((sample) => `<button class="sample-button ${sample.sample_id === activeSampleId ? "active" : ""}" data-sample-id="${escapeAttr(sample.sample_id)}">${escapeHtml(sample.label || sample.sample_id)}</button>`).join("")}
        </div>
      ` : ""}
      <div class="trade-table-wrap">
        <table class="trade-table">
          <colgroup>
            <col class="dir">
            <col class="time">
            <col class="price">
            <col class="risk">
            <col class="exit">
          </colgroup>
          <thead>
            <tr>
              <th>方向</th>
              <th>时间</th>
              <th>价格</th>
              <th>风控</th>
              <th>退场</th>
            </tr>
          </thead>
          <tbody>
            ${trades.map((trade) => {
              const isOpen = trade.status === "open";
              const exitValue = isOpen ? `当前: ${trade.current_px ?? "-"}` : `出: ${trade.exit || "-"}`;
              const pnlValue = isOpen ? `未实现PnL: ${trade.unrealized_pnl_pct ?? "-"}%` : `PnL: ${trade.pnl_pct ?? "-"}%`;
              return `
              <tr>
                <td><div class="stack"><span class="primary">${escapeHtml(String(trade.dir || ""))}</span><span class="secondary">#${escapeHtml(String(trade.id || ""))}</span></div></td>
                <td><div class="stack"><span class="primary">进: ${escapeHtml(String(trade.entry || "-"))}</span><span class="secondary">信号: ${escapeHtml(String(trade.entry_signal_time || "-"))}</span><span class="primary">${escapeHtml(String(exitValue))}</span><span class="secondary">信号: ${escapeHtml(String(trade.exit_signal_time || "-"))}</span></div></td>
                <td><div class="stack"><span class="primary">${escapeHtml(String(trade.entry_px || "-"))} → ${escapeHtml(String(isOpen ? trade.current_px ?? "-" : trade.exit_px || "-"))}</span><span class="secondary">数量: ${escapeHtml(String(trade.qty ?? "-"))}</span><span class="secondary">${escapeHtml(String(pnlValue))}</span></div></td>
                <td><div class="stack"><span class="primary">${formatStopRange(trade)}</span><span class="secondary">TP: ${escapeHtml(String(trade.framework_tp_price ?? "-"))}</span></div></td>
                <td><div class="stack"><span class="primary">${escapeHtml(String(trade.exit_reason_label || trade.exit_reason_code || "-"))}</span><span class="secondary">${escapeHtml(String(trade.exit_reason_detail || ""))}</span></div></td>
              </tr>
            `;}).join("")}
          </tbody>
        </table>
      </div>
    `;
  }

  function renderAuditContext(item) {
    return `
      <section class="audit-grid">
        <article class="observation">
          <div class="observation-name">原始报告</div>
          <div class="link-list">
            ${(item.links.report_paths || []).map((path) => `<a href="${escapeAttr(resolveReportHref(path))}" target="_blank" rel="noopener noreferrer">${escapeHtml(path)}</a>`).join("")}
          </div>
        </article>
        <article class="observation">
          <div class="observation-name">审计摘要</div>
          <div class="observation-evidence">
            <span>cluster_type: ${escapeHtml(String(item.audit.cluster_type || "-"))}</span>
            <span>cluster_member_count: ${escapeHtml(String(item.audit.cluster_member_count || "-"))}</span>
            <span>local_best_status: ${escapeHtml(String(item.audit.local_best_status || "-"))}</span>
            <span>local_best_winner: ${escapeHtml(String(item.audit.local_best_winner_param_id || "-"))}</span>
          </div>
        </article>
      </section>
    `;
  }

  function getSelectedItem() {
    return state.filteredItems.find((item) => item.rank === state.selectedRank) || null;
  }

  function tabButton(name, label) {
    return `<button class="tab ${state.activeTab === name ? "active" : ""}" data-tab="${escapeAttr(name)}">${escapeHtml(label)}</button>`;
  }

  function summarizeObservations(observations) {
    const counts = observations.reduce((acc, obs) => {
      acc[obs.status] = (acc[obs.status] || 0) + 1;
      return acc;
    }, {});
    return `有痕迹 ${counts.has_evidence || 0} / 未启用 ${counts.disabled || 0} / 未触发 ${counts.not_triggered || 0} / 可疑 ${counts.suspicious || 0}`;
  }

  function shortName(parameter) {
    return parameter.replace(/^chainer_/, "");
  }

  function statusLabel(status) {
    return {
      has_evidence: "有痕迹",
      disabled: "未启用",
      not_triggered: "本样本未触发",
      no_evidence: "无痕迹",
      suspicious: "可疑",
    }[status] || status;
  }

  function pillClass(status) {
    if (status === "suspicious" || status === "no_evidence") return "bad";
    if (status === "not_triggered" || status === "disabled") return "warn";
    return "";
  }

  function formatPct(value) {
    return `${formatNumber(value)}%`;
  }

  function renderWinRate(item) {
    const value = ((item || {}).summary || {}).avg_win_rate_pct;
    if (value === null || value === undefined) return "";
    return `<span>胜率: ${formatPct(value)}</span>`;
  }

  function resolveReportHref(path) {
    const text = String(path || "");
    if (!text) return "#";
    if (/^(https?:|file:)/.test(text)) return text;
    if (text.startsWith("/")) {
      if (location.protocol === "file:") {
        return `file://${text}`;
      }
      const marker = "/reports/";
      const idx = text.indexOf(marker);
      return idx >= 0 ? text.slice(idx) : `file://${text}`;
    }
    if (text.startsWith("reports/")) {
      return location.protocol === "file:" ? `../${text}` : `/${text}`;
    }
    return text;
  }

  function formatNumber(value) {
    if (value === null || value === undefined || value === "") return "-";
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(2).replace(/\.00$/, "") : "-";
  }

  function sortItems(items, mode) {
    const copy = [...(items || [])];
    const key = String(mode || "score_desc");
    const dir = key.endsWith("_asc") ? 1 : -1;

    function numeric(v, fallback = null) {
      const n = Number(v);
      return Number.isFinite(n) ? n : fallback;
    }

    function valueFor(item) {
      const summary = item.summary || {};
      if (key.startsWith("return_")) return numeric(summary.avg_total_return_pct, 0);
      if (key.startsWith("dd_")) return numeric(summary.avg_max_dd_pct, 0);
      if (key.startsWith("trades_")) return numeric(summary.total_trades, 0);
      if (key.startsWith("winrate_")) return numeric(summary.avg_win_rate_pct, -1);
      return numeric(item.score, 0);
    }

    copy.sort((a, b) => {
      const av = valueFor(a);
      const bv = valueFor(b);
      if (av !== bv) return (av - bv) * dir;
      return (Number(a.rank || 0) - Number(b.rank || 0));
    });
    return copy;
  }

  function escapeHtml(text) {
    return String(text)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function escapeAttr(text) {
    return escapeHtml(text).replace(/`/g, "&#96;");
  }
})();
