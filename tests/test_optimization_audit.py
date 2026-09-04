from __future__ import annotations

import json
from pathlib import Path

from trader.task.optimization_report import build_optimization_artifacts, write_optimization_artifacts


def _sample_report(
    *,
    strategy: str,
    symbol: str,
    interval: str,
    param_id: str,
    params: dict,
    total_return_pct: float,
    hold_return_pct: float,
    max_dd_pct: float,
    total_trades: int,
    total_signals: int,
    trades: list[dict],
    dataset_ref: str | None = None,
) -> dict:
    return {
        "strategy": strategy,
        "symbol": symbol,
        "interval": interval,
        "optimization_run_id": "run-audit",
        "report_version": "2.0",
        "param_id": param_id,
        "params": params,
        "dataset_ref": dataset_ref or f"{symbol}-{interval}-{param_id}",
        "report_path": f"reports/optimizations/run-audit/runs/{param_id}.json",
        "summary": {
            "total_return_pct": total_return_pct,
            "hold_return_pct": hold_return_pct,
            "sharpe": 1.2,
            "profit_factor": 1.4,
            "max_dd_pct": max_dd_pct,
            "total_trades": total_trades,
            "total_signals": total_signals,
        },
        "trades": trades,
        "signals": [{"bar_index": idx} for idx in range(total_signals)],
    }


def _trade(
    *,
    trade_id: int,
    entry: str,
    exit: str,
    entry_px: float,
    exit_px: float,
    exit_reason_code: str,
    exit_reason_label: str,
    bars_held: int = 1,
    framework_initial_stop_price: float | None = None,
    framework_final_stop_price: float | None = None,
    framework_tp_price: float | None = None,
    strategy_suggested_stop_price: float | None = None,
) -> dict:
    pnl_pct = round((exit_px - entry_px) / entry_px * 100, 4)
    return {
        "id": trade_id,
        "dir": "L",
        "entry": entry,
        "entry_px": entry_px,
        "exit": exit,
        "exit_px": exit_px,
        "pnl_pct": pnl_pct,
        "pnl": round(exit_px - entry_px, 4),
        "bars_held": bars_held,
        "exit_reason_code": exit_reason_code,
        "exit_reason_label": exit_reason_label,
        "exit_reason_detail": exit_reason_label,
        "stop_multiple_r": -1.0 if exit_reason_code == "framework_stop" else None,
        "risk_reward_ratio": 1.0 if exit_reason_code == "risk_reward_take_profit" else None,
        "framework_initial_stop_price": framework_initial_stop_price,
        "framework_final_stop_price": framework_final_stop_price,
        "framework_tp_price": framework_tp_price,
        "strategy_suggested_stop_price": strategy_suggested_stop_price,
    }


def test_optimization_audit_and_shortlist_artifacts_are_generated(tmp_path: Path):
    sample_reports = [
        _sample_report(
            strategy="macd_triple_divergence",
            symbol="BTCUSDT",
            interval="1d",
            param_id="btc-shadow-0",
            params={"chainer_stoploss_atr_mult": 0, "chainer_need_confirm": True},
            total_return_pct=20.0,
            hold_return_pct=5.0,
            max_dd_pct=15.0,
            total_trades=1,
            total_signals=1,
            dataset_ref="BTCUSDT-1d-baseline",
            trades=[
                _trade(
                    trade_id=1,
                    entry="2026-01-01T00:00:00",
                    exit="2026-01-02T00:00:00",
                    entry_px=105.0,
                    exit_px=98.0,
                    exit_reason_code="framework_stop",
                    exit_reason_label="框架止损退出",
                    framework_initial_stop_price=98.0,
                    framework_final_stop_price=98.0,
                    strategy_suggested_stop_price=90.0,
                )
            ],
        ),
        _sample_report(
            strategy="macd_triple_divergence",
            symbol="BTCUSDT",
            interval="1d",
            param_id="btc-shadow-1",
            params={"chainer_stoploss_atr_mult": 1, "chainer_need_confirm": True},
            total_return_pct=20.0,
            hold_return_pct=5.0,
            max_dd_pct=15.0,
            total_trades=1,
            total_signals=1,
            dataset_ref="BTCUSDT-1d-baseline",
            trades=[
                _trade(
                    trade_id=1,
                    entry="2026-01-01T00:00:00",
                    exit="2026-01-02T00:00:00",
                    entry_px=105.0,
                    exit_px=98.0,
                    exit_reason_code="framework_stop",
                    exit_reason_label="框架止损退出",
                    framework_initial_stop_price=98.0,
                    framework_final_stop_price=98.0,
                    strategy_suggested_stop_price=90.0,
                )
            ],
        ),
        _sample_report(
            strategy="macd_triple_divergence",
            symbol="ETHUSDT",
            interval="4h",
            param_id="eth-equity-01",
            params={"chainer_min_equity_percent": 0.1, "chainer_need_confirm": False},
            total_return_pct=12.0,
            hold_return_pct=4.0,
            max_dd_pct=20.0,
            total_trades=0,
            total_signals=2,
            dataset_ref="ETHUSDT-4h-baseline",
            trades=[],
        ),
        _sample_report(
            strategy="macd_triple_divergence",
            symbol="ETHUSDT",
            interval="4h",
            param_id="eth-equity-05",
            params={"chainer_min_equity_percent": 0.5, "chainer_need_confirm": False},
            total_return_pct=12.0,
            hold_return_pct=4.0,
            max_dd_pct=20.0,
            total_trades=0,
            total_signals=2,
            dataset_ref="ETHUSDT-4h-baseline",
            trades=[],
        ),
        _sample_report(
            strategy="macd_triple_divergence",
            symbol="SOLUSDT",
            interval="1h",
            param_id="sol-rr-1",
            params={"chainer_risk_reward_ratio": 1.0, "chainer_need_confirm": False},
            total_return_pct=30.0,
            hold_return_pct=10.0,
            max_dd_pct=8.0,
            total_trades=1,
            total_signals=1,
            dataset_ref="SOLUSDT-1h-baseline",
            trades=[
                _trade(
                    trade_id=1,
                    entry="2026-02-01T00:00:00",
                    exit="2026-02-01T04:00:00",
                    entry_px=100.0,
                    exit_px=110.0,
                    exit_reason_code="risk_reward_take_profit",
                    exit_reason_label="达到预设风险收益比退出",
                    framework_initial_stop_price=95.0,
                    framework_final_stop_price=95.0,
                    framework_tp_price=110.0,
                )
            ],
        ),
        _sample_report(
            strategy="macd_triple_divergence",
            symbol="SOLUSDT",
            interval="1h",
            param_id="sol-rr-2",
            params={"chainer_risk_reward_ratio": 2.0, "chainer_need_confirm": False},
            total_return_pct=24.0,
            hold_return_pct=10.0,
            max_dd_pct=9.0,
            total_trades=1,
            total_signals=1,
            dataset_ref="SOLUSDT-1h-baseline",
            trades=[
                _trade(
                    trade_id=1,
                    entry="2026-02-01T00:00:00",
                    exit="2026-02-01T08:00:00",
                    entry_px=100.0,
                    exit_px=120.0,
                    exit_reason_code="risk_reward_take_profit",
                    exit_reason_label="达到预设风险收益比退出",
                    framework_initial_stop_price=95.0,
                    framework_final_stop_price=95.0,
                    framework_tp_price=120.0,
                )
            ],
        ),
    ]

    artifacts = build_optimization_artifacts("run-audit", sample_reports, [])

    assert "audit" in artifacts
    assert "fingerprints" in artifacts
    assert "clusters" in artifacts
    assert "local_best" in artifacts
    assert "shortlist" in artifacts

    parameter_status = {item["parameter"]: item["status"] for item in artifacts["audit"]["parameter_effectiveness"]}
    assert parameter_status["chainer_stoploss_atr_mult"] == "shadowed_or_overridden"
    assert parameter_status["chainer_min_equity_percent"] == "no_opportunity"
    assert parameter_status["chainer_risk_reward_ratio"] == "effective"

    fingerprint_items = {item["param_id"]: item for item in artifacts["fingerprints"]["items"]}
    assert fingerprint_items["btc-shadow-0"]["exact_hash"] == fingerprint_items["btc-shadow-1"]["exact_hash"]
    assert fingerprint_items["sol-rr-1"]["exact_hash"] != fingerprint_items["sol-rr-2"]["exact_hash"]

    clusters = artifacts["clusters"]["items"]
    btc_cluster = next(cluster for cluster in clusters if set(cluster["members"]) == {"btc-shadow-0", "btc-shadow-1"})
    assert btc_cluster["cluster_type"] == "shadowed_behavior_cluster"
    assert btc_cluster["representative_param_id"] in {"btc-shadow-0", "btc-shadow-1"}

    eth_cluster = next(cluster for cluster in clusters if set(cluster["members"]) == {"eth-equity-01", "eth-equity-05"})
    assert eth_cluster["cluster_type"] == "expected_same_behavior"

    local_best = {item["group_id"]: item for item in artifacts["local_best"]["items"]}
    assert local_best["macd_triple_divergence|BTCUSDT|1d"]["status"] == "no_valid_winner"
    assert local_best["macd_triple_divergence|SOLUSDT|1h"]["winner"]["param_id"] == "sol-rr-1"

    shortlist_items = {item["group_id"]: item for item in artifacts["shortlist"]["items"]}
    assert "macd_triple_divergence|BTCUSDT|1d" not in shortlist_items
    assert shortlist_items["macd_triple_divergence|SOLUSDT|1h"]["status"] == "promote"
    assert shortlist_items["macd_triple_divergence|ETHUSDT|4h"]["status"] == "watch"

    run_dir = write_optimization_artifacts(tmp_path, "run-audit", sample_reports, [])
    assert (run_dir / "audit.json").exists()
    assert (run_dir / "fingerprints.json").exists()
    assert (run_dir / "clusters.json").exists()
    assert (run_dir / "local_best.json").exists()
    assert (run_dir / "shortlist.json").exists()
    assert (run_dir / "shortlist" / "index.html").exists()

    shortlist_json = json.loads((run_dir / "shortlist.json").read_text(encoding="utf-8"))
    assert shortlist_json["items"]
    shortlist_html = (run_dir / "shortlist" / "index.html").read_text(encoding="utf-8")
    assert "Shortlist" in shortlist_html
    assert "SOLUSDT" in shortlist_html
    assert "promote" in shortlist_html
