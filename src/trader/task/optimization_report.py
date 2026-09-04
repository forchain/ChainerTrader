from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from statistics import median

from trader.task.optimization_audit import (
    build_behavior_clusters,
    build_local_best,
    build_parameter_coverage_audit,
    build_shortlist,
    build_trade_fingerprints,
    write_shortlist_html,
)
from trader.task.optimization_workbench import build_workbench_payload
from trader.task.optimization_workbench import write_workbench_html

REPORT_VERSION = "2.0"
SCORE_VERSION = "score_v1"


def normalize_report_params(params: dict) -> dict:
    normalized = dict(params or {})
    enter_key = "chainer_enter_need_confirm"
    exit_key = "chainer_exit_need_confirm"
    merged_key = "chainer_need_confirm"

    if enter_key in normalized or exit_key in normalized:
        enter_value = normalized.get(enter_key)
        exit_value = normalized.get(exit_key)
        if enter_value == exit_value:
            normalized[merged_key] = enter_value
            normalized.pop(enter_key, None)
            normalized.pop(exit_key, None)

    normalized.pop("chainer_auto_signal", None)
    normalized.pop("chainer_signal_interfaces", None)
    return normalized


def _display_param_name(name: str) -> str:
    if name.startswith("chainer_"):
        return name.removeprefix("chainer_")
    return name


def build_optimization_artifacts(optimization_run_id: str, sample_reports: list[dict], failures: list[dict]) -> dict:
    grouped = {}
    for sample in sample_reports:
        sample["params"] = normalize_report_params(sample.get("params", {}))
        key = (
            sample.get("strategy", "unknown"),
            sample.get("symbol", "unknown"),
            sample.get("interval", "unknown"),
            sample.get("param_id", "unknown"),
        )
        grouped.setdefault(key, []).append(sample)

    aggregate_items = []
    for (_, symbol, interval, param_id), items in grouped.items():
        first = items[0]
        total_returns = [item["summary"]["total_return_pct"] for item in items]
        hold_returns = [item["summary"]["hold_return_pct"] for item in items]
        excess_returns = [total - hold for total, hold in zip(total_returns, hold_returns)]
        sharpe_values = [item["summary"].get("sharpe") for item in items if item["summary"].get("sharpe") is not None]
        profit_factors = [item["summary"].get("profit_factor") for item in items if item["summary"].get("profit_factor") is not None]
        max_dd_values = [item["summary"].get("max_dd_pct", 0.0) for item in items]
        total_trades = sum(item["summary"].get("total_trades", 0) for item in items)
        no_trade_samples = sum(1 for item in items if item["summary"].get("total_trades", 0) == 0)
        samples = len(items)
        beat_hold_ratio = round(sum(1 for value in excess_returns if value > 0) / samples, 4)
        no_trade_ratio = round(no_trade_samples / samples, 4)

        aggregate_items.append(
            {
                "strategy": first["strategy"],
                "symbol": symbol,
                "interval": interval,
                "param_id": param_id,
                "params": first["params"],
                "sample_details": [
                    {
                        "dataset_ref": item.get("dataset_ref"),
                        "report_path": item.get("report_path"),
                        "summary": item.get("summary", {}),
                        "trades": item.get("trades", []),
                        "signals": item.get("signals", []),
                    }
                    for item in items
                ],
                "samples": samples,
                "total_trades": total_trades,
                "no_trade_samples": no_trade_samples,
                "no_trade_ratio": no_trade_ratio,
                "avg_total_return_pct": round(sum(total_returns) / samples, 4),
                "avg_hold_return_pct": round(sum(hold_returns) / samples, 4),
                "avg_excess_return_pct": round(sum(excess_returns) / samples, 4),
                "median_excess_return_pct": round(median(excess_returns), 4),
                "beat_hold_ratio": beat_hold_ratio,
                "avg_sharpe": round(sum(sharpe_values) / len(sharpe_values), 4) if sharpe_values else None,
                "avg_profit_factor": round(sum(profit_factors) / len(profit_factors), 4) if profit_factors else None,
                "avg_max_dd_pct": round(sum(max_dd_values) / samples, 4),
            }
        )

    for item in aggregate_items:
        item["score_version"] = SCORE_VERSION
        item["score"] = _score_item(item)

    by_score = sorted(aggregate_items, key=lambda item: (item["score"], item["avg_excess_return_pct"]), reverse=True)
    by_excess_return = sorted(aggregate_items, key=lambda item: (item["avg_excess_return_pct"], item["beat_hold_ratio"]), reverse=True)
    datasets = sorted({sample["dataset_ref"] for sample in sample_reports if sample.get("dataset_ref")})
    failure_counts = _classify_failure_counts(failures)
    fingerprints = build_trade_fingerprints(aggregate_items)
    audit = build_parameter_coverage_audit(optimization_run_id, aggregate_items, fingerprints)
    clusters = build_behavior_clusters(aggregate_items, fingerprints, audit)
    local_best = build_local_best(aggregate_items, audit, clusters)
    shortlist = build_shortlist(local_best, audit, clusters)
    workbench = build_workbench_payload(
        optimization_run_id,
        {
            "optimization_run_id": optimization_run_id,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "completed_samples": len(sample_reports),
            "failed_samples": failure_counts["failed_samples"],
            "timed_out_samples": failure_counts["timed_out_samples"],
            "skipped_samples": failure_counts["skipped_samples"],
        },
        by_score,
        audit,
        clusters,
        local_best,
        shortlist,
    )

    return {
        "manifest": {
            "optimization_run_id": optimization_run_id,
            "report_version": REPORT_VERSION,
            "score_version": SCORE_VERSION,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "completed_samples": len(sample_reports),
            "failed_samples": failure_counts["failed_samples"],
            "timed_out_samples": failure_counts["timed_out_samples"],
            "skipped_samples": failure_counts["skipped_samples"],
            "failure_records": len(failures),
            "aborted": failure_counts["aborted"],
            "datasets": datasets,
            "run_reports": [sample.get("report_path") for sample in sample_reports if sample.get("report_path")],
        },
        "aggregate": {
            "optimization_run_id": optimization_run_id,
            "report_version": REPORT_VERSION,
            "score_version": SCORE_VERSION,
            "items": aggregate_items,
        },
        "rankings": {
            "by_score": by_score,
            "by_excess_return": by_excess_return,
        },
        "fingerprints": fingerprints,
        "audit": audit,
        "clusters": clusters,
        "local_best": local_best,
        "shortlist": shortlist,
        "workbench": workbench,
        "failures": failures,
    }


def _classify_failure_counts(failures: list[dict]) -> dict:
    skipped_reasons = {
        "coverage_incomplete",
        "dataset_failed",
        "dataset_timeout",
        "db_unavailable",
        "download_budget_exceeded",
        "download_failed",
        "no_data",
    }
    counts = {
        "failed_samples": 0,
        "timed_out_samples": 0,
        "skipped_samples": 0,
        "aborted": False,
    }
    for failure in failures:
        reason = failure.get("reason")
        if reason == "run_aborted":
            counts["aborted"] = True
        elif reason == "sample_timeout":
            counts["timed_out_samples"] += 1
        elif reason in skipped_reasons:
            counts["skipped_samples"] += 1
        else:
            counts["failed_samples"] += 1
    return counts


def write_optimization_artifacts(base_dir: str | Path, optimization_run_id: str, sample_reports: list[dict], failures: list[dict]) -> Path:
    artifacts = build_optimization_artifacts(optimization_run_id, sample_reports, failures)
    run_dir = Path(base_dir) / "reports" / "optimizations" / optimization_run_id
    rankings_dir = run_dir / "rankings"
    shortlist_dir = run_dir / "shortlist"
    workbench_dir = run_dir / "workbench"
    rankings_dir.mkdir(parents=True, exist_ok=True)
    shortlist_dir.mkdir(parents=True, exist_ok=True)
    workbench_dir.mkdir(parents=True, exist_ok=True)

    _write_json(run_dir / "manifest.json", artifacts["manifest"])
    _write_json(run_dir / "aggregate.json", artifacts["aggregate"])
    _write_json(run_dir / "failures.json", artifacts["failures"])
    _write_json(run_dir / "fingerprints.json", artifacts["fingerprints"])
    _write_json(run_dir / "audit.json", artifacts["audit"])
    _write_json(run_dir / "clusters.json", artifacts["clusters"])
    _write_json(run_dir / "local_best.json", artifacts["local_best"])
    _write_json(run_dir / "shortlist.json", artifacts["shortlist"])
    _write_json(run_dir / "workbench.json", artifacts["workbench"])
    _write_json(rankings_dir / "by_score.json", artifacts["rankings"]["by_score"])
    _write_json(rankings_dir / "by_excess_return.json", artifacts["rankings"]["by_excess_return"])
    _write_html(rankings_dir / "index.html", _build_rankings_html(optimization_run_id, artifacts["rankings"]["by_score"]))
    write_shortlist_html(shortlist_dir / "index.html", artifacts["shortlist"])
    write_workbench_html(
        workbench_dir / "index.html",
        artifacts["workbench"],
        Path(base_dir) / "src" / "trader" / "rpc" / "static" / "optimization-workbench" / "app.js",
        Path(base_dir) / "src" / "trader" / "rpc" / "static" / "optimization-workbench" / "style.css",
    )
    return run_dir


def _score_item(item: dict) -> float:
    excess_component = _clamp(item["avg_excess_return_pct"] / 20.0, -1.0, 1.0) * 35.0
    beat_component = item["beat_hold_ratio"] * 25.0
    sharpe_component = _clamp((item["avg_sharpe"] or 0.0) / 2.0, 0.0, 1.0) * 10.0
    profit_component = _clamp(((item["avg_profit_factor"] or 0.0) - 1.0) / 1.5, 0.0, 1.0) * 10.0
    drawdown_penalty = _clamp(item["avg_max_dd_pct"] / 40.0, 0.0, 1.0) * 20.0
    no_trade_penalty = item["no_trade_ratio"] * 30.0
    return round(50.0 + excess_component + beat_component + sharpe_component + profit_component - drawdown_penalty - no_trade_penalty, 4)


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _write_json(path: Path, payload):
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_html(path: Path, content: str):
    path.write_text(content, encoding="utf-8")


def _build_rankings_html(optimization_run_id: str, ranking_items: list[dict]) -> str:
    param_keys = sorted({key for item in ranking_items for key in item["params"].keys()})
    param_columns = [{"key": key, "label": _display_param_name(key)} for key in param_keys]
    rows = []
    for index, item in enumerate(ranking_items, start=1):
        row = {
            "rank": index,
            "symbol": item["symbol"],
            "interval": item["interval"],
            "score": item["score"],
            "avg_total_return_pct": item["avg_total_return_pct"],
            "avg_excess_return_pct": item["avg_excess_return_pct"],
            "avg_max_dd_pct": item["avg_max_dd_pct"],
            "total_trades": item["total_trades"],
            "param_id": item["param_id"],
            "sample_details": item["sample_details"],
        }
        for key in param_keys:
            row[key] = item["params"].get(key)
        rows.append(
            row
        )

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
              <th><button data-key="avg_excess_return_pct" data-type="number">超额收益%</button></th>
              <th><button data-key="avg_max_dd_pct" data-type="number">最大回撤%</button></th>
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
      if (["score", "avg_total_return_pct", "avg_excess_return_pct", "avg_max_dd_pct"].includes(key)) {{
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
        {{ key: "avg_excess_return_pct", label: "超额收益%", mono: false }},
        {{ key: "avg_max_dd_pct", label: "最大回撤%", mono: false }},
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
        if (["score", "avg_total_return_pct", "avg_excess_return_pct", "avg_max_dd_pct"].includes(spec.key)) {{
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
      return `<div class="path-line"><span class="path-label">报告</span><a class="report-link mono" href="${{escapeAttribute(resolveReportHref(text))}}" target="_blank" rel="noopener noreferrer">${{escapeHtml(text)}}</a></div>`;
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
          <td>${{formatCell("avg_excess_return_pct", row.avg_excess_return_pct)}}</td>
          <td>${{formatCell("avg_max_dd_pct", row.avg_max_dd_pct)}}</td>
          <td>${{formatCell("total_trades", row.total_trades)}}</td>
          <td>${{formatCell("param_id", row.param_id)}}</td>
          ${{paramColumns.map((column) => `<td>${{formatCell(column.key, row[column.key])}}</td>`).join("")}}
        </tr>
        `;
        if (row.rank !== expandedRank) return baseRow;
        return baseRow + `
        <tr class="drawer-row">
          <td colspan="${{9 + paramColumns.length}}">
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
        const trades = sample.trades || [];
        const tradeRows = trades.length ? trades.map((trade) => `
          <tr>
            <td>${{formatCell("id", trade.id)}}</td>
            <td>${{formatCell("dir", trade.dir)}}</td>
            <td>${{renderTimeCell(trade.entry_signal_time, trade.entry)}}</td>
            <td>${{formatCell("entry_px", trade.entry_px)}}</td>
            <td>${{renderTimeCell(trade.exit_signal_time, trade.exit)}}</td>
            <td>${{formatCell("exit_px", trade.exit_px)}}</td>
            <td>${{formatCell("pnl_pct", trade.pnl_pct)}}</td>
            <td>${{formatCell("pnl", trade.pnl)}}</td>
            <td>${{formatCell("bars_held", trade.bars_held)}}</td>
            <td>${{formatCell("exit_reason_label", trade.exit_reason_label || trade.exit_reason_code || "")}}</td>
          </tr>
        `).join("") : `<div class="empty-note">该样例没有成交记录。</div>`;

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
