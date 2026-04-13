from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path
from statistics import median


REPORT_VERSION = "2.0"
SCORE_VERSION = "score_v1"


def build_optimization_artifacts(optimization_run_id: str, sample_reports: list[dict], failures: list[dict]) -> dict:
    grouped = {}
    for sample in sample_reports:
        key = (sample["strategy"], sample["symbol"], sample["interval"], sample["param_id"])
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

    return {
        "manifest": {
            "optimization_run_id": optimization_run_id,
            "report_version": REPORT_VERSION,
            "score_version": SCORE_VERSION,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "completed_samples": len(sample_reports),
            "failed_samples": len(failures),
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
        "failures": failures,
    }


def write_optimization_artifacts(base_dir: str | Path, optimization_run_id: str, sample_reports: list[dict], failures: list[dict]) -> Path:
    artifacts = build_optimization_artifacts(optimization_run_id, sample_reports, failures)
    run_dir = Path(base_dir) / "reports" / "optimizations" / optimization_run_id
    rankings_dir = run_dir / "rankings"
    rankings_dir.mkdir(parents=True, exist_ok=True)

    _write_json(run_dir / "manifest.json", artifacts["manifest"])
    _write_json(run_dir / "aggregate.json", artifacts["aggregate"])
    _write_json(run_dir / "failures.json", artifacts["failures"])
    _write_json(rankings_dir / "by_score.json", artifacts["rankings"]["by_score"])
    _write_json(rankings_dir / "by_excess_return.json", artifacts["rankings"]["by_excess_return"])
    _write_html(rankings_dir / "index.html", _build_rankings_html(optimization_run_id, artifacts["rankings"]["by_score"]))
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
    rows = []
    for index, item in enumerate(ranking_items, start=1):
        rows.append(
            {
                "rank": index,
                "symbol": item["symbol"],
                "interval": item["interval"],
                "score": item["score"],
                "avg_total_return_pct": item["avg_total_return_pct"],
                "avg_excess_return_pct": item["avg_excess_return_pct"],
                "avg_max_dd_pct": item["avg_max_dd_pct"],
                "total_trades": item["total_trades"],
                "param_id": item["param_id"],
                "params": json.dumps(item["params"], ensure_ascii=False, sort_keys=True),
            }
        )

    rows_json = json.dumps(rows, ensure_ascii=False)
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
    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 1320px;
    }}
    thead th {{
      position: sticky;
      top: 0;
      background: var(--header);
      z-index: 1;
    }}
    th, td {{
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
      font-size: 14px;
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
  </style>
</head>
<body>
  <div class="wrap">
    <h1>组合排名报告</h1>
    <p class="sub">run_id: <span class="pill">{run_id}</span>。点击表头可排序。</p>
    <div class="panel">
      <div class="table-wrap">
        <table data-sort-table>
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
              <th>参数</th>
            </tr>
          </thead>
          <tbody id="rows"></tbody>
        </table>
      </div>
    </div>
  </div>
  <script>
    const rows = {rows_json};
    const tbody = document.getElementById("rows");
    let currentSort = {{ key: "score", direction: "desc", type: "number" }};

    function formatCell(key, value) {{
      if (value === null || value === undefined) return "";
      if (key === "params") return `<span class="mono">${{escapeHtml(String(value))}}</span>`;
      if (key === "param_id") return `<span class="mono">${{escapeHtml(String(value))}}</span>`;
      if (["score", "avg_total_return_pct", "avg_excess_return_pct", "avg_max_dd_pct"].includes(key)) {{
        return Number(value).toFixed(4).replace(/\\.0+$/, "").replace(/(\\.\\d*?)0+$/, "$1");
      }}
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
      tbody.innerHTML = sorted.map((row) => `
        <tr>
          <td>${{formatCell("rank", row.rank)}}</td>
          <td>${{formatCell("symbol", row.symbol)}}</td>
          <td>${{formatCell("interval", row.interval)}}</td>
          <td>${{formatCell("score", row.score)}}</td>
          <td>${{formatCell("avg_total_return_pct", row.avg_total_return_pct)}}</td>
          <td>${{formatCell("avg_excess_return_pct", row.avg_excess_return_pct)}}</td>
          <td>${{formatCell("avg_max_dd_pct", row.avg_max_dd_pct)}}</td>
          <td>${{formatCell("total_trades", row.total_trades)}}</td>
          <td>${{formatCell("param_id", row.param_id)}}</td>
          <td>${{formatCell("params", row.params)}}</td>
        </tr>
      `).join("");
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
        render();
      }});
    }});

    render();
  </script>
</body>
</html>
"""
