from __future__ import annotations

from collections import Counter
import shutil
from pathlib import Path
from typing import Any

from trader.task.optimization_audit import group_id


OBSERVABLE_PARAMETERS = [
    "chainer_need_confirm",
    "chainer_stoploss_atr_mult",
    "chainer_trailing_stop_ratio",
    "chainer_risk_reward_ratio",
    "chainer_enable_breakeven",
    "chainer_min_equity_percent",
    "chainer_mode",
    "macd_stop_enabled",
]


def build_workbench_payload(
    optimization_run_id: str,
    manifest: dict,
    ranking_items: list[dict],
    audit: dict,
    clusters: dict,
    local_best: dict,
    shortlist: dict,
) -> dict:
    items = []
    cluster_by_member = {}
    for cluster in clusters.get("items", []):
        for member in cluster.get("members", []):
            cluster_by_member[member] = cluster

    local_best_by_group = {
        item["group_id"]: item
        for item in local_best.get("items", [])
    }

    for index, row in enumerate(ranking_items, start=1):
        sample_summaries = [
            sample.get("summary", {})
            for sample in row.get("sample_details", [])
            if isinstance(sample, dict)
        ]
        win_rate_values = [
            float(summary.get("win_rate_pct"))
            for summary in sample_summaries
            if summary is not None and summary.get("win_rate_pct") is not None
        ]
        avg_win_rate_pct = (sum(win_rate_values) / len(win_rate_values)) if win_rate_values else None
        open_trade_count = sum(
            len(sample.get("open_trades", []))
            for sample in row.get("sample_details", [])
            if isinstance(sample, dict)
        )

        current_group_id = group_id(row)
        item_audit = audit.get("by_group", {}).get(current_group_id, {}).get("parameters", {})
        cluster = cluster_by_member.get(row["param_id"])
        local_group = local_best_by_group.get(current_group_id, {})
        items.append(
            {
                "rank": int(row.get("rank", index)),
                "param_id": row["param_id"],
                "strategy": row["strategy"],
                "symbol": row["symbol"],
                "interval": row["interval"],
                "group_id": current_group_id,
                "score": float(row.get("score", 0.0)),
                "summary": {
                    "avg_total_return_pct": float(row.get("avg_total_return_pct", 0.0)),
                    "avg_hold_return_pct": float(row.get("avg_hold_return_pct", 0.0)),
                    "avg_excess_return_pct": float(row.get("avg_excess_return_pct", 0.0)),
                    "avg_max_dd_pct": float(row.get("avg_max_dd_pct", 0.0)),
                    "avg_active_max_dd_pct": float(row.get("avg_active_max_dd_pct", row.get("avg_max_dd_pct", 0.0))),
                    "avg_full_max_dd_pct": float(row.get("avg_full_max_dd_pct", row.get("avg_max_dd_pct", 0.0))),
                    "total_trades": int(row.get("total_trades", 0)),
                    "open_trades": int(open_trade_count),
                    "avg_win_rate_pct": avg_win_rate_pct,
                },
                "params": dict(row.get("params", {})),
                "parameter_observations": build_parameter_observations(row, item_audit),
                "trades": _build_trade_rows(row),
                "samples": _build_samples(row),
                "links": _build_links(row),
                "audit": {
                    "run_health": audit.get("run_health"),
                    "cluster_type": cluster.get("cluster_type") if cluster else None,
                    "cluster_member_count": cluster.get("member_count") if cluster else 1,
                    "local_best_status": local_group.get("status"),
                    "local_best_winner_param_id": (local_group.get("winner") or {}).get("param_id"),
                },
                "views": ["parameter_observability", "trade_details", "audit_context"],
            }
        )

    return {
        "run": {
            "run_id": optimization_run_id,
            "status": audit.get("run_health", "unknown"),
            "blockers": _derive_blockers(audit, clusters),
            "generated_at": manifest.get("generated_at"),
        },
        "summary": {
            "completed_samples": manifest.get("completed_samples", 0),
            "failed_samples": manifest.get("failed_samples", 0),
            "timed_out_samples": manifest.get("timed_out_samples", 0),
            "skipped_samples": manifest.get("skipped_samples", 0),
            "unclassified_exit_rate": audit.get("unclassified_exit_rate", 0.0),
            "cluster_count": len(clusters.get("items", [])),
            "shortlist_count": len(shortlist.get("items", [])),
        },
        "items": items,
    }


def build_parameter_observations(item: dict, item_audit: dict[str, dict]) -> list[dict]:
    trades = _flatten_trades(item)
    signals = _flatten_signals(item)
    observations = []
    for parameter in OBSERVABLE_PARAMETERS:
        if parameter not in item.get("params", {}):
            continue
        machine_status = (item_audit.get(parameter) or {}).get("status")
        observations.append(_build_parameter_observation(parameter, item["params"][parameter], trades, signals, machine_status))
    return observations


def _build_parameter_observation(parameter: str, value: Any, trades: list[dict], signals: list[dict], machine_status: str | None) -> dict:
    if _is_disabled(parameter, value):
        return _observation(parameter, value, "disabled", ["当前候选未启用该参数"], {})

    if parameter == "chainer_need_confirm":
        signal_time_present_count = sum(1 for trade in trades if trade.get("entry_signal_time") or trade.get("exit_signal_time"))
        delayed_entry_count = sum(
            1
            for trade in trades
            if trade.get("entry_signal_time") and trade.get("entry") and trade.get("entry_signal_time") != trade.get("entry")
        )
        delayed_exit_count = sum(
            1
            for trade in trades
            if trade.get("exit_signal_time") and trade.get("exit") and trade.get("exit_signal_time") != trade.get("exit")
        )
        if delayed_entry_count or delayed_exit_count:
            status = "has_evidence"
        elif trades and signal_time_present_count == 0:
            status = "suspicious"
        else:
            status = _status_from_machine(machine_status, has_signal=bool(trades))
        evidence = []
        if delayed_entry_count:
            evidence.append(f"{delayed_entry_count} 笔交易的进场信号与成交时间分离")
        if delayed_exit_count:
            evidence.append(f"{delayed_exit_count} 笔交易的出场信号与执行时间分离")
        if not evidence:
            evidence.append("未观察到时间分离证据")
        return _observation(parameter, value, status, evidence, {
            "signal_time_present_count": signal_time_present_count,
            "delayed_entry_count": delayed_entry_count,
            "delayed_exit_count": delayed_exit_count,
        })

    if parameter == "chainer_stoploss_atr_mult":
        stop_count = sum(1 for trade in trades if trade.get("framework_initial_stop_price") is not None)
        framework_stop_hits = sum(1 for trade in trades if trade.get("exit_reason_code") == "framework_stop")
        if machine_status == "effective":
            status = "effective"
        else:
            status = "has_evidence" if stop_count > 0 else _status_from_machine(machine_status, has_signal=bool(trades))
        return _observation(parameter, value, status, [
            f"{stop_count} 笔交易记录了初始止损价",
            f"{framework_stop_hits} 笔交易由框架止损退出",
        ], {
            "stop_context_count": stop_count,
            "framework_stop_hit_count": framework_stop_hits,
        })

    if parameter == "chainer_trailing_stop_ratio":
        trailing_update_trade_count = sum(
            1
            for trade in trades
            if int(trade.get("framework_trailing_update_count") or 0) > 0
        )
        trailing_update_count = sum(int(trade.get("framework_trailing_update_count") or 0) for trade in trades)
        status = "effective" if machine_status == "effective" else (
            "has_evidence" if trailing_update_count > 0 else _status_from_machine(machine_status, has_signal=bool(trades))
        )
        return _observation(parameter, value, status, [
            f"{trailing_update_trade_count} 笔交易更新过移动止损",
        ], {
            "trailing_update_trade_count": trailing_update_trade_count,
            "trailing_update_count": trailing_update_count,
        })

    if parameter == "chainer_risk_reward_ratio":
        tp_count = sum(1 for trade in trades if trade.get("framework_tp_price") is not None)
        tp_hits = sum(1 for trade in trades if trade.get("exit_reason_code") == "risk_reward_take_profit")
        status = "has_evidence" if tp_count > 0 or tp_hits > 0 else _status_from_machine(machine_status, has_signal=bool(trades))
        return _observation(parameter, value, status, [
            f"{tp_count} 笔交易记录了止盈目标价",
            f"{tp_hits} 笔交易达到预设风险收益比退出",
        ], {
            "tp_context_count": tp_count,
            "tp_hit_count": tp_hits,
        })

    if parameter == "chainer_enable_breakeven":
        moved_stop_count = sum(
            1
            for trade in trades
            if trade.get("framework_initial_stop_price") is not None
            and trade.get("framework_final_stop_price") is not None
            and float(trade["framework_initial_stop_price"]) != float(trade["framework_final_stop_price"])
        )
        status = "has_evidence" if moved_stop_count > 0 else _status_from_machine(machine_status, has_signal=bool(trades))
        return _observation(parameter, value, status, [
            f"{moved_stop_count} 笔交易出现止损位移动",
        ], {
            "moved_stop_count": moved_stop_count,
        })

    if parameter == "chainer_min_equity_percent":
        blocked_equity_count = sum(1 for signal in signals if _signal_status(signal) == "blocked_equity")
        qty_values = sorted({float(trade.get("qty", 0.0)) for trade in trades if trade.get("qty") is not None})
        status = "has_evidence" if blocked_equity_count > 0 or len(qty_values) > 1 else _status_from_machine(machine_status, has_signal=bool(signals))
        evidence = [f"{blocked_equity_count} 个信号被余额保护拦截"]
        if qty_values:
            evidence.append(f"观察到 {len(qty_values)} 个不同的仓位数量")
        return _observation(parameter, value, status, evidence, {
            "blocked_equity_count": blocked_equity_count,
            "distinct_qty_count": len(qty_values),
        })

    if parameter == "chainer_mode":
        side_counts = Counter(trade.get("dir") for trade in trades)
        status = "has_evidence" if trades else _status_from_machine(machine_status, has_signal=bool(signals))
        return _observation(parameter, value, status, [
            f"L={side_counts.get('L', 0)} / S={side_counts.get('S', 0)}",
        ], {
            "long_trade_count": side_counts.get("L", 0),
            "short_trade_count": side_counts.get("S", 0),
        })

    if parameter == "macd_stop_enabled":
        strategy_stop_count = sum(1 for trade in trades if trade.get("exit_reason_code") == "strategy_stop")
        status = "has_evidence" if strategy_stop_count > 0 else _status_from_machine(machine_status, has_signal=bool(trades))
        return _observation(parameter, value, status, [
            f"{strategy_stop_count} 笔交易由策略止损逻辑退出",
        ], {
            "strategy_stop_count": strategy_stop_count,
        })

    return _observation(parameter, value, _status_from_machine(machine_status, has_signal=bool(trades) or bool(signals)), [], {})


def write_workbench_html(path: Path, workbench_payload: dict, app_js_path: Path, style_css_path: Path) -> None:
    workbench_dir = path.parent
    app_target = workbench_dir / app_js_path.name
    style_target = workbench_dir / style_css_path.name
    if app_js_path.resolve() != app_target.resolve():
        shutil.copy2(app_js_path, app_target)
    if style_css_path.resolve() != style_target.resolve():
        shutil.copy2(style_css_path, style_target)
    html = f"""<!DOCTYPE html>
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

  <script>window.__WORKBENCH_DATA__ = {__import__("json").dumps(workbench_payload, ensure_ascii=False)};</script>
  <script src="./{app_js_path.name}"></script>
</body>
</html>
"""
    path.write_text(html, encoding="utf-8")


def _status_from_machine(machine_status: str | None, *, has_signal: bool) -> str:
    if machine_status in {"shadowed_or_overridden", "suspicious"}:
        return "suspicious"
    if machine_status == "effective":
        return "has_evidence"
    if machine_status == "no_opportunity":
        return "not_triggered"
    if machine_status == "inactive":
        return "no_evidence" if has_signal else "not_triggered"
    return "no_evidence" if has_signal else "not_triggered"


def _is_disabled(parameter: str, value: Any) -> bool:
    if parameter == "chainer_mode":
        return False
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return float(value) == 0.0
    return value in (None, "", "0", "0.0", "false", "False")


def _observation(parameter: str, value: Any, status: str, evidence: list[str], stats: dict[str, Any]) -> dict:
    return {
        "parameter": parameter,
        "value": value,
        "status": status,
        "evidence": evidence,
        "stats": stats,
    }


def _build_trade_rows(item: dict) -> list[dict]:
    rows = []
    for sample in item.get("sample_details", []):
        report_path = sample.get("report_path")
        for trade in sample.get("trades", []):
            row = dict(trade)
            row["report_path"] = report_path
            rows.append(row)
        for trade in sample.get("open_trades", []):
            row = dict(trade)
            row["report_path"] = report_path
            rows.append(row)
    return rows


def _build_samples(item: dict) -> list[dict]:
    samples = []
    for index, sample in enumerate(item.get("sample_details", []), start=1):
        signals = sample.get("signals", [])
        samples.append(
            {
                "sample_id": f"sample-{index}",
                "label": sample.get("dataset_ref") or f"样本 {index}",
                "dataset_ref": sample.get("dataset_ref"),
                "report_path": sample.get("report_path"),
                "summary": sample.get("summary", {}),
                "signal_outcomes": dict(Counter(_signal_status(signal) for signal in signals)),
            }
        )
    return samples


def _build_links(item: dict) -> dict:
    report_paths = [sample.get("report_path") for sample in item.get("sample_details", []) if sample.get("report_path")]
    return {
        "primary_report_path": report_paths[0] if report_paths else None,
        "report_paths": report_paths,
    }


def _derive_blockers(audit: dict, clusters: dict) -> list[str]:
    blockers = []
    if float(audit.get("unclassified_exit_rate", 0.0)) > 0.0:
        blockers.append("unclassified_exit_rate")
    if any(item.get("status") in {"shadowed_or_overridden", "suspicious"} for item in audit.get("parameter_effectiveness", [])):
        blockers.append("parameter_effectiveness")
    if any(item.get("cluster_type") == "suspicious_same_behavior" for item in clusters.get("items", [])):
        blockers.append("suspicious_duplicate_cluster")
    return blockers


def _flatten_trades(item: dict) -> list[dict]:
    trades = []
    for sample in item.get("sample_details", []):
        trades.extend(sample.get("trades", []))
        trades.extend(sample.get("open_trades", []))
    return trades


def _flatten_signals(item: dict) -> list[dict]:
    signals = []
    for sample in item.get("sample_details", []):
        signals.extend(sample.get("signals", []))
    return signals


def _signal_status(signal: dict) -> str:
    outcome = signal.get("trade_outcome", {})
    return str(outcome.get("status") or "unknown")
