from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

from trader.core.optimization.domain import display_param_name


def write_shortlist_html(path: Path, shortlist: dict) -> None:
    cards = []
    for item in shortlist.get("items", []):
        winner = item["winner"]
        summary = winner["summary"]
        cards.append(
            f"""
            <article class="card">
              <div class="badge badge-{item['status']}">{item['status']}</div>
              <h2>{winner['strategy']} / {winner['symbol']} / {winner['interval']}</h2>
              <p class="param">param_id: <span>{winner['param_id']}</span></p>
              <p>收益: {summary['avg_total_return_pct']:.2f}% | 持仓回撤: {summary['avg_max_dd_pct']:.2f}% | 交易数: {summary['total_trades']}</p>
              <p>入选原因: {", ".join(item['selection_reasons']) or "n/a"}</p>
              <p>风险提示: {", ".join(item['risks']) or "无"}</p>
            </article>
            """
        )

    rendered = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Shortlist</title>
  <style>
    body {{ margin: 0; padding: 32px; font-family: "Avenir Next", "PingFang SC", sans-serif; background: #f4efe4; color: #201c17; }}
    h1 {{ margin: 0 0 18px; font-size: 30px; }}
    .grid {{ display: grid; gap: 16px; }}
    .card {{
      background: #fffaf0; border: 1px solid #d9ccb7; border-radius: 16px;
      padding: 18px 20px; box-shadow: 0 16px 40px rgba(54, 41, 21, 0.08);
    }}
    .badge {{
      display: inline-block; padding: 4px 10px; border-radius: 999px;
      font-size: 12px; font-weight: 700; margin-bottom: 10px; text-transform: uppercase;
    }}
    .badge-promote {{ background: #dfeee6; color: #245946; }}
    .badge-watch {{ background: #efe6cf; color: #76551b; }}
    .badge-reject {{ background: #f4dddb; color: #8a3b34; }}
    .param span {{ font-family: ui-monospace, "SFMono-Regular", Menlo, monospace; }}
  </style>
</head>
<body>
  <h1>Shortlist</h1>
  <div class="grid">{''.join(cards)}</div>
</body>
</html>"""
    path.write_text(rendered, encoding="utf-8")


def write_workbench_html(path: Path, workbench_payload: dict, app_js_path: Path, style_css_path: Path) -> None:
    workbench_dir = path.parent
    app_target = workbench_dir / app_js_path.name
    style_target = workbench_dir / style_css_path.name
    if app_js_path.resolve() != app_target.resolve():
        shutil.copy2(app_js_path, app_target)
    if style_css_path.resolve() != style_target.resolve():
        shutil.copy2(style_css_path, style_target)
    rendered = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Optimization Validation Workbench</title>
  <link rel="stylesheet" href="./{style_css_path.name}">
</head>
<body>
  <main class="shell">
    <header class="hero">
      <div>
        <h1>Optimization Validation Workbench</h1>
        <p id="run-meta" class="muted"></p>
      </div>
      <div class="hero-actions">
        <input id="filter-input" type="search" placeholder="筛选 symbol / interval / param_id">
      </div>
    </header>

    <section id="summary-grid" class="summary-grid"></section>

    <section class="layout">
      <aside class="candidate-pane">
        <div class="pane-head">
          <h2>候选列表</h2>
          <p id="candidate-count" class="muted"></p>
          <div class="param-filters">
            <label>
              <select id="sort-select">
                <option value="score_desc">排序: 评分（高→低）</option>
                <option value="return_desc">收益（高→低）</option>
                <option value="dd_asc">持仓回撤（低→高）</option>
                <option value="trades_desc">交易数（多→少）</option>
                <option value="winrate_desc">胜率（高→低）</option>
              </select>
            </label>
          </div>
          <div id="param-filters" class="param-filters"></div>
          <div class="pager">
            <button id="prev-page" type="button">上一页</button>
            <span id="page-indicator" class="muted"></span>
            <button id="next-page" type="button">下一页</button>
          </div>
        </div>
        <div id="candidate-list" class="candidate-list"></div>
      </aside>

      <section class="detail-pane">
        <div id="detail-empty" class="empty-state">
          选择左侧候选，查看参数观察、交易明细和原始报告入口。
        </div>
        <div id="detail-view" class="detail-view hidden"></div>
      </section>
    </section>
  </main>

  <script>window.__WORKBENCH_DATA__ = {json.dumps(workbench_payload, ensure_ascii=False)};</script>
  <script src="./{app_js_path.name}"></script>
</body>
</html>
"""
    path.write_text(rendered, encoding="utf-8")


def build_rankings_html(optimization_run_id: str, ranking_items: list[dict]) -> str:
    param_keys = sorted({key for item in ranking_items for key in item["params"].keys()})
    param_columns = [{"key": key, "label": display_param_name(key)} for key in param_keys]
    rows = []
    for index, item in enumerate(ranking_items, start=1):
        row = {
            "rank": index,
            "symbol": item["symbol"],
            "interval": item["interval"],
            "score": item["score"],
            "avg_total_return_pct": item["avg_total_return_pct"],
            "avg_hold_return_pct": item["avg_hold_return_pct"],
            "avg_excess_return_pct": item["avg_excess_return_pct"],
            "avg_max_dd_pct": item["avg_max_dd_pct"],
            "avg_full_max_dd_pct": item.get("avg_full_max_dd_pct", item["avg_max_dd_pct"]),
            "total_trades": item["total_trades"],
            "param_id": item["param_id"],
            "sample_details": item["sample_details"],
        }
        for key in param_keys:
            row[key] = item["params"].get(key)
        rows.append(row)

    rows_json = json.dumps(rows, ensure_ascii=False)
    param_columns_json = json.dumps(param_columns, ensure_ascii=False)
    title = html.escape(f"Optimization Rankings - {optimization_run_id}")
    run_id = html.escape(optimization_run_id)
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f3efe6;
      --panel: #fffdf8;
      --line: #d7cdbd;
      --text: #1e1b16;
      --muted: #6f6659;
      --accent: #2f6b5f;
      --accent-soft: #dcebe7;
      --header: #f0e5d1;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "PingFang SC", "Hiragino Sans GB", sans-serif;
      background: linear-gradient(180deg, #ede6d8 0%, var(--bg) 100%);
      color: var(--text);
    }}
    .wrap {{
      max-width: 1600px;
      margin: 0 auto;
      padding: 32px 24px 48px;
    }}
    h1 {{
      margin: 0 0 8px;
      font-size: 34px;
      letter-spacing: 0.02em;
    }}
    .sub {{
      margin: 0 0 24px;
      color: var(--muted);
      font-size: 15px;
    }}
    .panel {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 18px;
      overflow: hidden;
      box-shadow: 0 18px 50px rgba(67, 55, 38, 0.08);
    }}
    .table-wrap {{
      overflow: auto;
    }}
    .toolbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 12px;
      padding: 14px 18px;
      border-top: 1px solid var(--line);
      background: #f8f2e6;
      color: var(--muted);
      font-size: 13px;
    }}
    .pager {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }}
    .pager button {{
      all: unset;
      cursor: pointer;
      padding: 6px 10px;
      border: 1px solid var(--line);
      border-radius: 10px;
      background: var(--panel);
      color: var(--text);
      font-weight: 600;
    }}
    .pager button[disabled] {{
      cursor: default;
      opacity: 0.45;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 1160px;
      table-layout: fixed;
    }}
    col {{
      width: auto;
    }}
    thead th {{
      position: sticky;
      top: 0;
      background: var(--header);
      z-index: 1;
    }}
    th, td {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 13px;
      overflow-wrap: anywhere;
    }}
    tbody tr:nth-child(even) {{
      background: #fcf9f1;
    }}
    th button {{
      all: unset;
      cursor: pointer;
      display: inline-flex;
      gap: 6px;
      align-items: center;
      color: inherit;
      font-weight: 700;
    }}
    th button:hover {{
      color: var(--accent);
    }}
    .pill {{
      display: inline-block;
      padding: 4px 8px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font-weight: 600;
      font-size: 12px;
    }}
    .mono {{
      font-family: ui-monospace, "SFMono-Regular", Menlo, monospace;
      font-size: 12px;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    tbody tr {{
      cursor: pointer;
    }}
    tbody tr:hover {{
      background: #f4ecdc;
    }}
    tbody tr.is-selected {{
      background: #efe2c5;
    }}
    .drawer-row td {{
      padding: 0;
      background: #f7efdf;
      border-bottom: 1px solid var(--line);
    }}
    .drawer {{
      padding: 18px;
      display: grid;
      gap: 18px;
    }}
    .drawer-title {{
      margin: 0;
      font-size: 18px;
    }}
    .drawer-sub {{
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .sample-card {{
      border: 1px solid var(--line);
      border-radius: 14px;
      background: #fcf9f1;
      overflow: hidden;
    }}
    .sample-meta {{
      padding: 10px 12px;
      border-bottom: 1px solid var(--line);
      background: #f7efdf;
      display: flex;
      justify-content: flex-start;
      align-items: center;
      min-height: 42px;
      font-size: 12px;
      color: var(--muted);
    }}
    .sample-table-wrap {{
      overflow: auto;
    }}
    .sample-table {{
      width: auto;
      min-width: 0;
      table-layout: fixed;
    }}
    .sample-columns col {{
      width: auto;
    }}
    .compact-table th, .compact-table td {{
      padding: 7px 8px;
      font-size: 12px;
    }}
    .path-line {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
      align-items: center;
      min-width: 0;
    }}
    .path-label {{
      color: var(--muted);
      font-weight: 600;
    }}
    .report-link {{
      color: var(--accent);
      text-decoration: none;
      border-bottom: 1px dashed rgba(47, 107, 95, 0.45);
      max-width: 100%;
      overflow-wrap: anywhere;
    }}
    .report-link:hover {{
      color: #20483f;
      border-bottom-color: currentColor;
    }}
    .time-cell {{
      display: grid;
      gap: 1px;
      min-width: 0;
    }}
    .time-line {{
      display: block;
      min-width: 0;
      line-height: 1.35;
      word-break: break-word;
    }}
    .time-line.signal {{
      color: var(--muted);
      font-size: 10px;
    }}
    .time-line.exec {{
      color: var(--text);
      font-weight: 600;
      font-size: 11px;
    }}
    .empty-note {{
      padding: 16px;
      color: var(--muted);
      font-size: 14px;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>组合排名报告</h1>
    <p class="sub">run_id: <span class="pill">{run_id}</span>。点击表头可排序。</p>
    <div class="panel">
      <div class="table-wrap">
        <table data-sort-table>
          <colgroup id="table-columns"></colgroup>
          <thead>
            <tr>
              <th><button data-key="rank" data-type="number">排名</button></th>
              <th><button data-key="symbol" data-type="string">币种</button></th>
              <th><button data-key="interval" data-type="string">周期</button></th>
              <th><button data-key="score" data-type="number">评分</button></th>
              <th><button data-key="avg_total_return_pct" data-type="number">总收益率%</button></th>
              <th><button data-key="avg_hold_return_pct" data-type="number">拿住收益%</button></th>
              <th><button data-key="avg_excess_return_pct" data-type="number">超额收益%</button></th>
              <th><button data-key="avg_max_dd_pct" data-type="number">持仓回撤%</button></th>
              <th><button data-key="avg_full_max_dd_pct" data-type="number">全程回撤%</button></th>
              <th><button data-key="total_trades" data-type="number">交易数</button></th>
              <th><button data-key="param_id" data-type="string">参数ID</button></th>
              <th id="param-columns-anchor"></th>
            </tr>
          </thead>
          <tbody id="rows"></tbody>
        </table>
      </div>
      <div class="toolbar">
        <div id="table-summary"></div>
        <div class="pager">
          <button id="prev-page" type="button">上一页</button>
          <span id="page-indicator"></span>
          <button id="next-page" type="button">下一页</button>
        </div>
      </div>
    </div>
  </div>
  <script>
    const rows = {rows_json};
    const paramColumns = {param_columns_json};
    const tbody = document.getElementById("rows");
    const tableColumns = document.getElementById("table-columns");
    const paramColumnsAnchor = document.getElementById("param-columns-anchor");
    const tableSummary = document.getElementById("table-summary");
    const pageIndicator = document.getElementById("page-indicator");
    const prevPageButton = document.getElementById("prev-page");
    const nextPageButton = document.getElementById("next-page");
    let currentSort = {{ key: "score", direction: "desc", type: "number" }};
    let currentPage = 1;
    let expandedRank = null;
    const pageSize = 25;

    paramColumnsAnchor.outerHTML = paramColumns.map((column) => `
      <th><button data-key="${{column.key}}" data-type="string">${{escapeHtml(column.label)}}</button></th>
    `).join("");

    function formatCell(key, value) {{
      if (value === null || value === undefined) return "";
      if (key === "param_id") return `<span class="mono">${{escapeHtml(String(value))}}</span>`;
      if (["score", "avg_total_return_pct", "avg_hold_return_pct", "avg_excess_return_pct", "avg_max_dd_pct", "avg_full_max_dd_pct"].includes(key)) {{
        return Number(value).toFixed(4).replace(/\\.0+$/, "").replace(/(\\.\\d*?)0+$/, "$1");
      }}
      if (typeof value === "boolean") return value ? "true" : "false";
      return escapeHtml(String(value));
    }}

    function escapeHtml(text) {{
      return text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }}

    function measureTextWidth(text, isMono = false) {{
      const probe = document.createElement("span");
      probe.textContent = text;
      probe.style.position = "absolute";
      probe.style.visibility = "hidden";
      probe.style.whiteSpace = "nowrap";
      probe.style.fontSize = isMono ? "12px" : "14px";
      probe.style.fontFamily = isMono
        ? 'ui-monospace, "SFMono-Regular", Menlo, monospace'
        : '"Avenir Next", "PingFang SC", "Hiragino Sans GB", sans-serif';
      document.body.appendChild(probe);
      const width = probe.getBoundingClientRect().width;
      probe.remove();
      return width;
    }}

    function buildColumnSpecs() {{
      const fixedSpecs = [
        {{ key: "rank", label: "排名", mono: false }},
        {{ key: "symbol", label: "币种", mono: false }},
        {{ key: "interval", label: "周期", mono: false }},
        {{ key: "score", label: "评分", mono: false }},
        {{ key: "avg_total_return_pct", label: "总收益率%", mono: false }},
        {{ key: "avg_hold_return_pct", label: "拿住收益%", mono: false }},
        {{ key: "avg_excess_return_pct", label: "超额收益%", mono: false }},
        {{ key: "avg_max_dd_pct", label: "持仓回撤%", mono: false }},
        {{ key: "avg_full_max_dd_pct", label: "全程回撤%", mono: false }},
        {{ key: "total_trades", label: "交易数", mono: false }},
        {{ key: "param_id", label: "参数ID", mono: true }},
      ];
      return fixedSpecs.concat(paramColumns.map((column) => ({{
        key: column.key,
        label: column.label,
        mono: false,
      }})));
    }}

    function computeColumnWidth(spec) {{
      const values = rows.map((row) => {{
        const value = row[spec.key];
        if (value === null || value === undefined) return "";
        if (typeof value === "boolean") return value ? "true" : "false";
        const numCols = ["score", "avg_total_return_pct", "avg_hold_return_pct",
          "avg_excess_return_pct", "avg_max_dd_pct", "avg_full_max_dd_pct"];
        if (numCols.includes(spec.key)) {{
          return Number(value).toFixed(4).replace(/\\.0+$/, "").replace(/(\\.\\d*?)0+$/, "$1");
        }}
        return String(value);
      }});
      const contentText = values.reduce((longest, current) => current.length > longest.length ? current : longest, "");
      const contentWidth = measureTextWidth(contentText, spec.mono);
      const headerWidth = measureTextWidth(spec.label, false);
      const preferred = Math.max(contentWidth, headerWidth * 0.7);
      const extraPadding = spec.key === "param_id" ? 26 : 24;
      return Math.max(56, Math.min(220, Math.ceil(preferred + extraPadding)));
    }}

    function applyColumnWidths() {{
      const specs = buildColumnSpecs();
      tableColumns.innerHTML = specs.map((spec) => `<col style="width:${{computeColumnWidth(spec)}}px">`).join("");
    }}

    function renderReportPath(reportPath) {{
      const text = String(reportPath || "").trim();
      if (!text) return "";
      const href = escapeAttribute(resolveReportHref(text));
      return `<div class="path-line"><span class="path-label">报告</span>`
        + `<a class="report-link mono" href="${{href}}" target="_blank" rel="noopener noreferrer">${{escapeHtml(text)}}</a></div>`;
    }}

    function resolveReportHref(reportPath) {{
      if (/^(https?:|file:)/.test(reportPath)) return reportPath;
      if (reportPath.startsWith("/")) return `file://${{reportPath}}`;
      const marker = "reports/optimizations/";
      const idx = reportPath.indexOf(marker);
      if (idx >= 0) {{
        return `../${{reportPath.slice(idx + marker.length)}}`;
      }}
      return reportPath;
    }}

    function escapeAttribute(text) {{
      return escapeHtml(text).replace(/`/g, "&#96;");
    }}

    function renderTimeCell(signalTime, executionTime) {{
      const signal = signalTime ? escapeHtml(String(signalTime)) : "无信号时间";
      const execution = executionTime ? escapeHtml(String(executionTime)) : "-";
      return `
        <div class="time-cell">
          <span class="time-line signal">${{signal}}</span>
          <span class="time-line exec">${{execution}}</span>
        </div>
      `;
    }}

    function render() {{
      const sorted = [...rows].sort((a, b) => {{
        const av = a[currentSort.key];
        const bv = b[currentSort.key];
        if (currentSort.type === "number") {{
          const diff = Number(av) - Number(bv);
          return currentSort.direction === "asc" ? diff : -diff;
        }}
        const cmp = String(av).localeCompare(String(bv), "zh-Hans-CN");
        return currentSort.direction === "asc" ? cmp : -cmp;
      }});
      const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
      currentPage = Math.min(currentPage, totalPages);
      const start = (currentPage - 1) * pageSize;
      const visibleRows = sorted.slice(start, start + pageSize);
      tableSummary.textContent = `共 ${{sorted.length}} 条，当前显示第 ${{start + 1}}-${{Math.min(start + visibleRows.length, sorted.length)}} 条`;
      pageIndicator.textContent = `第 ${{currentPage}} / ${{totalPages}} 页`;
      prevPageButton.disabled = currentPage <= 1;
      nextPageButton.disabled = currentPage >= totalPages;

      tbody.innerHTML = visibleRows.map((row) => {{
        const baseRow = `
        <tr data-row-rank="${{row.rank}}" class="${{row.rank === expandedRank ? "is-selected" : ""}}">
          <td>${{formatCell("rank", row.rank)}}</td>
          <td>${{formatCell("symbol", row.symbol)}}</td>
          <td>${{formatCell("interval", row.interval)}}</td>
          <td>${{formatCell("score", row.score)}}</td>
          <td>${{formatCell("avg_total_return_pct", row.avg_total_return_pct)}}</td>
          <td>${{formatCell("avg_hold_return_pct", row.avg_hold_return_pct)}}</td>
          <td>${{formatCell("avg_excess_return_pct", row.avg_excess_return_pct)}}</td>
          <td>${{formatCell("avg_max_dd_pct", row.avg_max_dd_pct)}}</td>
          <td>${{formatCell("avg_full_max_dd_pct", row.avg_full_max_dd_pct)}}</td>
          <td>${{formatCell("total_trades", row.total_trades)}}</td>
          <td>${{formatCell("param_id", row.param_id)}}</td>
          ${{paramColumns.map((column) => `<td>${{formatCell(column.key, row[column.key])}}</td>`).join("")}}
        </tr>
        `;
        if (row.rank !== expandedRank) return baseRow;
        return baseRow + `
        <tr class="drawer-row">
          <td colspan="${{11 + paramColumns.length}}">
            ${{renderDetails(row)}}
          </td>
        </tr>
        `;
      }}).join("");

      tbody.querySelectorAll("tr").forEach((tr) => {{
        if (tr.classList.contains("drawer-row")) return;
        tr.addEventListener("click", () => {{
          const rank = Number(tr.dataset.rowRank);
          expandedRank = expandedRank === rank ? null : rank;
          render();
        }});
      }});
    }}

    function renderDetails(row) {{
      const sampleDetails = row.sample_details || [];
      const columnWidths = [56, 52, 172, 84, 172, 84, 84, 84, 78, 148];
      const detailBody = sampleDetails.map((sample, index) => {{
        const trades = (sample.trades || []).concat(sample.open_trades || []);
        const tradeRows = trades.length ? trades.map((trade) => {{
          const isOpen = trade.status === "open";
          const exitTime = isOpen ? `当前: ${{trade.current_px ?? "-"}}` : trade.exit;
          const exitPrice = isOpen ? trade.current_px : trade.exit_px;
          const pnlPct = isOpen ? trade.unrealized_pnl_pct : trade.pnl_pct;
          const pnl = isOpen ? "" : trade.pnl;
          return `
          <tr>
            <td>${{formatCell("id", trade.id)}}</td>
            <td>${{formatCell("dir", trade.dir)}}</td>
            <td>${{renderTimeCell(trade.entry_signal_time, trade.entry)}}</td>
            <td>${{formatCell("entry_px", trade.entry_px)}}</td>
            <td>${{renderTimeCell(trade.exit_signal_time, exitTime)}}</td>
            <td>${{formatCell("exit_px", exitPrice)}}</td>
            <td>${{formatCell("pnl_pct", pnlPct)}}</td>
            <td>${{formatCell("pnl", pnl)}}</td>
            <td>${{formatCell("bars_held", trade.bars_held)}}</td>
            <td>${{formatCell("exit_reason_label", trade.exit_reason_label || trade.exit_reason_code || "")}}</td>
          </tr>
        `;}}).join("") : `<div class="empty-note">该样例没有成交记录。</div>`;

        return `
          <section class="sample-card">
            ${{
              sample.report_path
                ? `<div class="sample-meta">${{renderReportPath(sample.report_path)}}</div>`
                : ""
            }}
            <div class="sample-table-wrap">
              ${{
                trades.length
                  ? `<table class="sample-table compact-table">
                      <colgroup class="sample-columns">
                        ${{columnWidths.map((width) => `<col style="width:${{width}}px">`).join("")}}
                      </colgroup>
                      <thead>
                        <tr>
                          <th>ID</th>
                          <th>方向</th>
                          <th>进场时间<div class="time-line signal">进场信号</div></th>
                          <th>进场价</th>
                          <th>出场时间<div class="time-line signal">出场信号</div></th>
                          <th>出场价</th>
                          <th>收益%</th>
                          <th>收益</th>
                          <th>持仓K线数</th>
                          <th>退场原因</th>
                        </tr>
                      </thead>
                      <tbody>${{tradeRows}}</tbody>
                    </table>`
                  : tradeRows
              }}
            </div>
          </section>
        `;
      }}).join("");
      return `
        <div class="drawer">
          <div>
            <h2 class="drawer-title">交易列表</h2>
            <p class="drawer-sub">${{escapeHtml(`${{row.symbol}} / ${{row.interval}} / ${{row.param_id}}`)}}</p>
          </div>
          ${{detailBody}}
        </div>
      `;
    }}

    document.querySelectorAll("[data-sort-table] thead button").forEach((button) => {{
      button.addEventListener("click", () => {{
        const key = button.dataset.key;
        const type = button.dataset.type;
        const sameKey = currentSort.key === key;
        currentSort = {{
          key,
          type,
          direction: sameKey && currentSort.direction === "desc" ? "asc" : "desc",
        }};
        currentPage = 1;
        render();
      }});
    }});

    prevPageButton.addEventListener("click", () => {{
      if (currentPage <= 1) return;
      currentPage -= 1;
      render();
    }});

    nextPageButton.addEventListener("click", () => {{
      currentPage += 1;
      render();
    }});

    applyColumnWidths();
    render();
  </script>
</body>
</html>
"""
