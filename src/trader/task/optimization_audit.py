from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


KEY_PARAMETERS = {
    "chainer_stoploss_atr_mult",
    "chainer_risk_reward_ratio",
    "chainer_need_confirm",
    "chainer_enable_breakeven",
    "chainer_min_equity_percent",
    "macd_stop_enabled",
}

STATUS_PRIORITY = {
    "shadowed_or_overridden": 4,
    "suspicious": 3,
    "effective": 2,
    "inactive": 1,
    "no_opportunity": 0,
}


def build_trade_fingerprints(aggregate_items: list[dict]) -> dict:
    items = []
    for item in aggregate_items:
        exact_payload = _exact_fingerprint_payload(item)
        exact_hash = _stable_hash(exact_payload)
        items.append(
            {
                "group_id": group_id(item),
                "strategy": item["strategy"],
                "symbol": item["symbol"],
                "interval": item["interval"],
                "param_id": item["param_id"],
                "params": item.get("params", {}),
                "exact_hash": exact_hash,
                "exact_payload": exact_payload,
            }
        )

    return {"items": items}


def build_parameter_coverage_audit(optimization_run_id: str, aggregate_items: list[dict], fingerprints: dict) -> dict:
    by_group: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    observations_by_param: dict[str, list[dict]] = defaultdict(list)

    items_by_group: dict[str, list[dict]] = defaultdict(list)
    for item in aggregate_items:
        items_by_group[group_id(item)].append(item)

    fingerprint_map = {item["param_id"]: item for item in fingerprints["items"]}

    for current_group_id, group_items in items_by_group.items():
        for parameter in _varying_parameters(group_items):
            observation = _evaluate_parameter_for_group(parameter, group_items, fingerprint_map)
            observations_by_param[parameter].append(observation)
            by_group[current_group_id][parameter] = observation

    parameter_effectiveness = []
    for parameter in sorted(observations_by_param):
        observations = observations_by_param[parameter]
        parameter_effectiveness.append(
            {
                "parameter": parameter,
                "tested_values": _sorted_jsonable({value for obs in observations for value in obs["tested_values"]}),
                "path_enter_count": sum(obs["path_enter_count"] for obs in observations),
                "opportunity_count": sum(obs["opportunity_count"] for obs in observations),
                "trigger_count": sum(obs["trigger_count"] for obs in observations),
                "effect_count": sum(obs["effect_count"] for obs in observations),
                "status": max(observations, key=lambda obs: STATUS_PRIORITY[obs["status"]])["status"],
                "changed_fields": sorted({field for obs in observations for field in obs["changed_fields"]}),
                "group_observations": observations,
            }
        )

    unclassified_trade_count = sum(
        1
        for item in aggregate_items
        for trade in _flatten_trades(item)
        if trade.get("exit_reason_code") == "unclassified_exit"
    )
    total_trade_count = sum(len(_flatten_trades(item)) for item in aggregate_items)
    unclassified_exit_rate = round(unclassified_trade_count / total_trade_count, 4) if total_trade_count else 0.0

    blocking_parameters = [
        item["parameter"]
        for item in parameter_effectiveness
        if item["status"] in {"shadowed_or_overridden", "suspicious"}
    ]
    run_health = "healthy"
    if unclassified_exit_rate > 0.0 or blocking_parameters:
        run_health = "blocked"
    elif any(item["status"] in {"inactive", "no_opportunity"} for item in parameter_effectiveness):
        run_health = "warning"

    return {
        "optimization_run_id": optimization_run_id,
        "run_health": run_health,
        "unclassified_exit_rate": unclassified_exit_rate,
        "unclassified_trade_count": unclassified_trade_count,
        "total_trade_count": total_trade_count,
        "parameter_effectiveness": parameter_effectiveness,
        "by_group": {
            group_key: {"parameters": observations}
            for group_key, observations in sorted(by_group.items())
        },
    }


def build_behavior_clusters(aggregate_items: list[dict], fingerprints: dict, audit: dict) -> dict:
    item_by_param = {item["param_id"]: item for item in aggregate_items}
    grouped_fingerprints: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for fingerprint in fingerprints["items"]:
        grouped_fingerprints[(fingerprint["group_id"], fingerprint["exact_hash"])].append(fingerprint)

    clusters = []
    for (current_group_id, exact_hash), members in sorted(grouped_fingerprints.items()):
        if len(members) < 2:
            continue
        param_ids = sorted(member["param_id"] for member in members)
        group_parameters = audit.get("by_group", {}).get(current_group_id, {}).get("parameters", {})
        varying = _varying_parameters([item_by_param[param_id] for param_id in param_ids])
        statuses = {parameter: group_parameters.get(parameter, {}).get("status") for parameter in varying}
        cluster_type = _cluster_type_from_statuses(statuses.values())
        representative_param_id = _choose_representative([item_by_param[param_id] for param_id in param_ids])["param_id"]
        clusters.append(
            {
                "group_id": current_group_id,
                "cluster_id": f"{current_group_id}|{exact_hash[:12]}",
                "strategy": members[0]["strategy"],
                "symbol": members[0]["symbol"],
                "interval": members[0]["interval"],
                "exact_hash": exact_hash,
                "cluster_type": cluster_type,
                "members": param_ids,
                "member_count": len(param_ids),
                "representative_param_id": representative_param_id,
                "varying_parameters": varying,
                "parameter_statuses": statuses,
            }
        )

    return {"items": clusters}


def build_local_best(aggregate_items: list[dict], audit: dict, clusters: dict) -> dict:
    item_by_param = {item["param_id"]: item for item in aggregate_items}
    cluster_by_member = {}
    for cluster in clusters["items"]:
        for member in cluster["members"]:
            cluster_by_member[member] = cluster

    grouped_items: dict[str, list[dict]] = defaultdict(list)
    for item in aggregate_items:
        grouped_items[group_id(item)].append(item)

    results = []
    for current_group_id, group_items in sorted(grouped_items.items()):
        eligible = []
        rejected = []
        group_parameter_statuses = audit.get("by_group", {}).get(current_group_id, {}).get("parameters", {})

        for item in group_items:
            reasons = []
            cluster = cluster_by_member.get(item["param_id"])
            if cluster is not None and cluster["representative_param_id"] != item["param_id"]:
                reasons.append("duplicate_cluster_non_representative")
            if cluster is not None and cluster["cluster_type"] == "shadowed_behavior_cluster":
                reasons.append("shadowed_behavior_cluster")
            if cluster is not None and cluster["cluster_type"] == "suspicious_same_behavior":
                reasons.append("suspicious_duplicate_cluster")
            if _item_unclassified_exit_rate(item) > 0.0:
                reasons.append("unclassified_exit_present")

            for parameter, observation in group_parameter_statuses.items():
                if parameter in item.get("params", {}) and observation["status"] in {"shadowed_or_overridden", "suspicious"}:
                    reasons.append(observation["status"])

            if reasons:
                rejected.append(
                    {
                        "param_id": item["param_id"],
                        "why_not_selected": sorted(set(reasons)),
                    }
                )
            else:
                eligible.append(item)

        if not eligible:
            results.append(
                {
                    "group_id": current_group_id,
                    "status": "no_valid_winner",
                    "winner": None,
                    "runner_up": [],
                    "rejected": rejected,
                }
            )
            continue

        ordered = sorted(eligible, key=lambda item: _local_best_sort_key(item, group_parameter_statuses))
        winner = ordered[0]
        results.append(
            {
                "group_id": current_group_id,
                "status": "selected",
                "winner": {
                    "param_id": winner["param_id"],
                    "strategy": winner["strategy"],
                    "symbol": winner["symbol"],
                    "interval": winner["interval"],
                    "params": winner.get("params", {}),
                    "selection_reasons": _selection_reasons(winner, group_parameter_statuses, cluster_by_member.get(winner["param_id"])),
                    "summary": _winner_summary(winner),
                },
                "runner_up": [
                    {
                        "param_id": item["param_id"],
                        "why_not_selected": ["lower_rank_than_winner"],
                    }
                    for item in ordered[1:]
                ],
                "rejected": rejected,
            }
        )

    return {"items": results}


def build_shortlist(local_best: dict, audit: dict, clusters: dict) -> dict:
    items = []
    for record in local_best["items"]:
        if record["status"] != "selected" or record["winner"] is None:
            continue
        winner = record["winner"]
        summary = winner["summary"]
        item_status = "promote"
        risks = []
        if summary["total_trades"] <= 0:
            item_status = "watch"
            risks.append("no_closed_trades")
        if "no_opportunity_parameter_present" in winner["selection_reasons"]:
            item_status = "watch"
            risks.append("parameter_coverage_no_opportunity")

        items.append(
            {
                "group_id": record["group_id"],
                "status": item_status,
                "winner": winner,
                "selection_reasons": winner["selection_reasons"],
                "risks": risks,
                "alternatives": record["runner_up"],
            }
        )

    return {
        "run_health": audit["run_health"],
        "items": items,
    }


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

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Shortlist</title>
  <style>
    body {{ margin: 0; padding: 32px; font-family: "Avenir Next", "PingFang SC", sans-serif; background: #f4efe4; color: #201c17; }}
    h1 {{ margin: 0 0 18px; font-size: 30px; }}
    .grid {{ display: grid; gap: 16px; }}
    .card {{ background: #fffaf0; border: 1px solid #d9ccb7; border-radius: 16px; padding: 18px 20px; box-shadow: 0 16px 40px rgba(54, 41, 21, 0.08); }}
    .badge {{ display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; margin-bottom: 10px; text-transform: uppercase; }}
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
    path.write_text(html, encoding="utf-8")


def group_id(item: dict) -> str:
    return f"{item['strategy']}|{item['symbol']}|{item['interval']}"


def _varying_parameters(items: list[dict]) -> list[str]:
    keys = sorted({key for item in items for key in item.get("params", {}) if key in KEY_PARAMETERS})
    varying = []
    for key in keys:
        values = {_json_key(item.get("params", {}).get(key)) for item in items if key in item.get("params", {})}
        if len(values) > 1:
            varying.append(key)
    return varying


def _evaluate_parameter_for_group(parameter: str, group_items: list[dict], fingerprint_map: dict[str, dict]) -> dict:
    values = _sorted_jsonable({
        item.get("params", {}).get(parameter)
        for item in group_items
        if parameter in item.get("params", {})
    })
    path_enter_count = len(group_items)
    opportunity_count = sum(1 for item in group_items if _parameter_has_opportunity(parameter, item))
    trigger_count = sum(1 for item in group_items if _parameter_triggered(parameter, item))
    changed_fields = set()
    effect_count = 0

    for left, right in _distinct_pairs(group_items):
        left_value = left.get("params", {}).get(parameter)
        right_value = right.get("params", {}).get(parameter)
        if left_value == right_value:
            continue
        diff_fields = _parameter_diff_fields(parameter, left, right, fingerprint_map)
        if diff_fields:
            effect_count += 1
            changed_fields.update(diff_fields)

    status = "inactive"
    if effect_count > 0:
        status = "effective"
    elif opportunity_count == 0:
        status = "no_opportunity"
    elif parameter == "chainer_stoploss_atr_mult" and _stoploss_shadowed(group_items):
        status = "shadowed_or_overridden"

    return {
        "group_id": group_id(group_items[0]),
        "tested_values": values,
        "path_enter_count": path_enter_count,
        "opportunity_count": opportunity_count,
        "trigger_count": trigger_count,
        "effect_count": effect_count,
        "status": status,
        "changed_fields": sorted(changed_fields),
    }


def _parameter_has_opportunity(parameter: str, item: dict) -> bool:
    trades = _flatten_trades(item)
    if parameter == "chainer_min_equity_percent":
        threshold = (1.0 - float(item.get("params", {}).get(parameter, 0.0))) * 100.0
        return float(item.get("avg_max_dd_pct", 0.0)) >= threshold
    if parameter == "chainer_need_confirm":
        return _total_signals(item) > 0
    if parameter in {"chainer_stoploss_atr_mult", "chainer_risk_reward_ratio", "chainer_enable_breakeven", "macd_stop_enabled"}:
        return any(trade.get("framework_initial_stop_price") is not None for trade in trades) or bool(trades)
    return bool(trades) or _total_signals(item) > 0


def _parameter_triggered(parameter: str, item: dict) -> bool:
    trades = _flatten_trades(item)
    if parameter == "chainer_stoploss_atr_mult":
        return any(trade.get("framework_initial_stop_price") is not None for trade in trades)
    if parameter == "chainer_risk_reward_ratio":
        return any(
            trade.get("framework_tp_price") is not None or trade.get("exit_reason_code") == "risk_reward_take_profit"
            for trade in trades
        )
    if parameter == "chainer_enable_breakeven":
        return any(
            trade.get("framework_initial_stop_price") is not None
            and trade.get("framework_final_stop_price") is not None
            and float(trade["framework_initial_stop_price"]) != float(trade["framework_final_stop_price"])
            for trade in trades
        )
    if parameter == "chainer_need_confirm":
        return _total_signals(item) > 0
    if parameter == "chainer_min_equity_percent":
        return _parameter_has_opportunity(parameter, item)
    if parameter == "macd_stop_enabled":
        return any(trade.get("exit_reason_code") == "strategy_stop" for trade in trades)
    return False


def _parameter_diff_fields(parameter: str, left: dict, right: dict, fingerprint_map: dict[str, dict]) -> set[str]:
    changed = set()
    left_trades = _flatten_trades(left)
    right_trades = _flatten_trades(right)
    if parameter == "chainer_stoploss_atr_mult":
        if _field_values(left_trades, "framework_initial_stop_price") != _field_values(right_trades, "framework_initial_stop_price"):
            changed.add("framework_initial_stop_price")
        if _field_values(left_trades, "framework_final_stop_price") != _field_values(right_trades, "framework_final_stop_price"):
            changed.add("framework_final_stop_price")
    elif parameter == "chainer_risk_reward_ratio":
        if _field_values(left_trades, "framework_tp_price") != _field_values(right_trades, "framework_tp_price"):
            changed.add("framework_tp_price")
        if _field_values(left_trades, "exit_reason_code") != _field_values(right_trades, "exit_reason_code"):
            changed.add("exit_reason_code")
    elif parameter == "chainer_need_confirm":
        if _field_values(left_trades, "entry") != _field_values(right_trades, "entry"):
            changed.add("entry")
        if left.get("total_trades") != right.get("total_trades"):
            changed.add("total_trades")
    elif parameter == "chainer_enable_breakeven":
        if _field_values(left_trades, "framework_final_stop_price") != _field_values(right_trades, "framework_final_stop_price"):
            changed.add("framework_final_stop_price")
    elif parameter == "chainer_min_equity_percent":
        if left.get("total_trades") != right.get("total_trades"):
            changed.add("total_trades")
    elif parameter == "macd_stop_enabled":
        if _field_values(left_trades, "exit_reason_code") != _field_values(right_trades, "exit_reason_code"):
            changed.add("exit_reason_code")

    left_hash = fingerprint_map[left["param_id"]]["exact_hash"]
    right_hash = fingerprint_map[right["param_id"]]["exact_hash"]
    if left_hash != right_hash:
        changed.add("exact_behavior")
    return changed


def _stoploss_shadowed(group_items: list[dict]) -> bool:
    trades = [trade for item in group_items for trade in _flatten_trades(item)]
    if not trades:
        return False
    initial_stops = {trade.get("framework_initial_stop_price") for trade in trades}
    suggested_stops = {trade.get("strategy_suggested_stop_price") for trade in trades if trade.get("strategy_suggested_stop_price") is not None}
    return len(initial_stops) == 1 and bool(suggested_stops)


def _field_values(trades: list[dict], key: str) -> list[Any]:
    return [trade.get(key) for trade in trades]


def _local_best_sort_key(item: dict, group_parameter_statuses: dict[str, dict]) -> tuple:
    statuses = [
        observation["status"]
        for parameter, observation in group_parameter_statuses.items()
        if parameter in item.get("params", {})
    ]
    health_rank = min((0 if status == "effective" else 1 if status == "no_opportunity" else 2 for status in statuses), default=1)
    return (
        health_rank,
        float(item.get("avg_max_dd_pct", 0.0)),
        -int(item.get("total_trades", 0)),
        -float(item.get("score", 0.0)),
        -float(item.get("avg_total_return_pct", 0.0)),
        item["param_id"],
    )


def _selection_reasons(item: dict, group_parameter_statuses: dict[str, dict], cluster: dict | None) -> list[str]:
    reasons = ["audit_passed"]
    if cluster is None or cluster.get("representative_param_id") == item["param_id"]:
        reasons.append("cluster_representative")
    statuses = [
        observation["status"]
        for parameter, observation in group_parameter_statuses.items()
        if parameter in item.get("params", {})
    ]
    if "no_opportunity" in statuses:
        reasons.append("no_opportunity_parameter_present")
    reasons.append("lowest_risk_then_best_return")
    return reasons


def _winner_summary(item: dict) -> dict:
    return {
        "avg_total_return_pct": float(item.get("avg_total_return_pct", 0.0)),
        "avg_max_dd_pct": float(item.get("avg_max_dd_pct", 0.0)),
        "total_trades": int(item.get("total_trades", 0)),
        "score": float(item.get("score", 0.0)),
    }


def _cluster_type_from_statuses(statuses) -> str:
    normalized = {status for status in statuses if status}
    if "shadowed_or_overridden" in normalized:
        return "shadowed_behavior_cluster"
    if normalized and normalized.issubset({"no_opportunity", "inactive"}):
        return "expected_same_behavior"
    return "suspicious_same_behavior"


def _choose_representative(items: list[dict]) -> dict:
    return sorted(
        items,
        key=lambda item: (
            -float(item.get("score", 0.0)),
            float(item.get("avg_max_dd_pct", 0.0)),
            -int(item.get("total_trades", 0)),
            item["param_id"],
        ),
    )[0]


def _exact_fingerprint_payload(item: dict) -> list[dict]:
    payload = []
    for sample in sorted(item.get("sample_details", []), key=lambda sample: (str(sample.get("dataset_ref") or ""), str(sample.get("report_path") or ""))):
        payload.append(
            {
                "dataset_ref": sample.get("dataset_ref"),
                "trades": [
                    {
                        "dir": trade.get("dir"),
                        "entry": trade.get("entry"),
                        "entry_px": trade.get("entry_px"),
                        "exit": trade.get("exit"),
                        "exit_px": trade.get("exit_px"),
                        "bars_held": trade.get("bars_held"),
                        "exit_reason_code": trade.get("exit_reason_code"),
                        "framework_initial_stop_price": trade.get("framework_initial_stop_price"),
                        "framework_final_stop_price": trade.get("framework_final_stop_price"),
                        "framework_tp_price": trade.get("framework_tp_price"),
                        "strategy_suggested_stop_price": trade.get("strategy_suggested_stop_price"),
                    }
                    for trade in sample.get("trades", [])
                ],
            }
        )
    return payload


def _stable_hash(payload: Any) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _flatten_trades(item: dict) -> list[dict]:
    trades = []
    for sample in item.get("sample_details", []):
        trades.extend(sample.get("trades", []))
    return trades


def _item_unclassified_exit_rate(item: dict) -> float:
    trades = _flatten_trades(item)
    if not trades:
        return 0.0
    unclassified = sum(1 for trade in trades if trade.get("exit_reason_code") == "unclassified_exit")
    return unclassified / len(trades)


def _total_signals(item: dict) -> int:
    total = 0
    for sample in item.get("sample_details", []):
        summary = sample.get("summary", {})
        total += int(summary.get("total_signals", 0) or 0)
    return total


def _sorted_jsonable(values: set[Any]) -> list[Any]:
    return sorted(values, key=lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False))


def _json_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _distinct_pairs(items: list[dict]):
    for index, left in enumerate(items):
        for right in items[index + 1 :]:
            yield left, right
