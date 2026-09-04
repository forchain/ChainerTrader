from __future__ import annotations

import json
from pathlib import Path

from trader.task.optimization_audit_workflow import run_optimization_audit


def _write_run_report(run_dir: Path, name: str, payload: dict) -> None:
    runs_dir = run_dir / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"{name}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _sample_report(
    *,
    param_id: str,
    symbol: str = "BTCUSDT",
    interval: str = "1d",
    params: dict,
    total_return_pct: float,
    hold_return_pct: float,
    max_dd_pct: float,
    trades: list[dict],
) -> dict:
    return {
        "strategy": "macd_triple_divergence",
        "symbol": symbol,
        "interval": interval,
        "optimization_run_id": "run-script",
        "report_version": "2.0",
        "param_id": param_id,
        "params": params,
        "dataset_ref": f"{symbol}-{interval}-baseline",
        "summary": {
            "total_return_pct": total_return_pct,
            "hold_return_pct": hold_return_pct,
            "sharpe": 1.0,
            "profit_factor": 1.3,
            "max_dd_pct": max_dd_pct,
            "total_trades": len(trades),
            "total_signals": max(1, len(trades)),
        },
        "trades": trades,
        "signals": [{"bar_index": 1}],
    }


def _trade(exit_reason_code: str, framework_initial_stop_price: float, *, tp_price: float | None = None, suggested_stop: float | None = None) -> dict:
    return {
        "id": 1,
        "dir": "L",
        "entry": "2026-03-01T00:00:00",
        "entry_px": 100.0,
        "exit": "2026-03-01T04:00:00",
        "exit_px": 95.0 if exit_reason_code == "framework_stop" else 110.0,
        "pnl_pct": -5.0 if exit_reason_code == "framework_stop" else 10.0,
        "pnl": -5.0 if exit_reason_code == "framework_stop" else 10.0,
        "bars_held": 1,
        "exit_reason_code": exit_reason_code,
        "exit_reason_label": {
            "framework_stop": "框架止损退出",
            "risk_reward_take_profit": "达到预设风险收益比退出",
            "unclassified_exit": "未分类退出",
        }[exit_reason_code],
        "framework_initial_stop_price": framework_initial_stop_price,
        "framework_final_stop_price": framework_initial_stop_price,
        "framework_tp_price": tp_price,
        "strategy_suggested_stop_price": suggested_stop,
    }


def test_run_optimization_audit_blocks_on_shadowed_or_unclassified_results(tmp_path: Path):
    run_dir = tmp_path / "reports" / "optimizations" / "run-script"
    _write_run_report(
        run_dir,
        "a",
        _sample_report(
            param_id="shadow-0",
            params={"chainer_stoploss_atr_mult": 0},
            total_return_pct=10.0,
            hold_return_pct=2.0,
            max_dd_pct=10.0,
            trades=[_trade("framework_stop", 98.0, suggested_stop=90.0)],
        ),
    )
    _write_run_report(
        run_dir,
        "b",
        _sample_report(
            param_id="shadow-1",
            params={"chainer_stoploss_atr_mult": 1},
            total_return_pct=10.0,
            hold_return_pct=2.0,
            max_dd_pct=10.0,
            trades=[_trade("framework_stop", 98.0, suggested_stop=90.0)],
        ),
    )
    (run_dir / "failures.json").write_text("[]", encoding="utf-8")

    result = run_optimization_audit(tmp_path, "run-script", block_on_failure=False)

    assert result["status"] == "blocked"
    assert "shadowed_parameter" in result["blocker_codes"]
    summary = json.loads((run_dir / "agent_review_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "blocked"
    assert summary["run_health"] == "blocked"


def test_run_optimization_audit_passes_and_writes_agent_summary_for_healthy_run(tmp_path: Path):
    run_dir = tmp_path / "reports" / "optimizations" / "run-script"
    _write_run_report(
        run_dir,
        "a",
        _sample_report(
            param_id="rr-1",
            symbol="SOLUSDT",
            interval="1h",
            params={"chainer_risk_reward_ratio": 1.0},
            total_return_pct=18.0,
            hold_return_pct=4.0,
            max_dd_pct=8.0,
            trades=[_trade("risk_reward_take_profit", 95.0, tp_price=110.0)],
        ),
    )
    _write_run_report(
        run_dir,
        "b",
        _sample_report(
            param_id="rr-2",
            symbol="SOLUSDT",
            interval="1h",
            params={"chainer_risk_reward_ratio": 2.0},
            total_return_pct=22.0,
            hold_return_pct=4.0,
            max_dd_pct=9.0,
            trades=[_trade("risk_reward_take_profit", 95.0, tp_price=120.0)],
        ),
    )
    (run_dir / "failures.json").write_text("[]", encoding="utf-8")

    result = run_optimization_audit(tmp_path, "run-script", block_on_failure=False)

    assert result["status"] == "passed"
    assert result["blocker_codes"] == []
    summary = json.loads((run_dir / "agent_review_summary.json").read_text(encoding="utf-8"))
    assert summary["status"] == "passed"
    assert summary["shortlist_count"] == 1


def test_run_optimization_audit_blocks_on_suspicious_duplicate_clusters(tmp_path: Path):
    run_dir = tmp_path / "reports" / "optimizations" / "run-script"
    _write_run_report(
        run_dir,
        "a",
        _sample_report(
            param_id="rr-1a",
            symbol="SOLUSDT",
            interval="1h",
            params={"chainer_risk_reward_ratio": 1.0},
            total_return_pct=18.0,
            hold_return_pct=4.0,
            max_dd_pct=8.0,
            trades=[_trade("risk_reward_take_profit", 95.0, tp_price=110.0)],
        ),
    )
    _write_run_report(
        run_dir,
        "b",
        _sample_report(
            param_id="rr-2a",
            symbol="SOLUSDT",
            interval="1h",
            params={"chainer_risk_reward_ratio": 2.0},
            total_return_pct=18.0,
            hold_return_pct=4.0,
            max_dd_pct=8.0,
            trades=[_trade("risk_reward_take_profit", 95.0, tp_price=110.0)],
        ),
    )
    _write_run_report(
        run_dir,
        "c",
        _sample_report(
            param_id="rr-2b",
            symbol="SOLUSDT",
            interval="1h",
            params={"chainer_risk_reward_ratio": 2.0},
            total_return_pct=22.0,
            hold_return_pct=4.0,
            max_dd_pct=9.0,
            trades=[_trade("risk_reward_take_profit", 95.0, tp_price=120.0)],
        ),
    )
    (run_dir / "failures.json").write_text("[]", encoding="utf-8")

    result = run_optimization_audit(tmp_path, "run-script", block_on_failure=False)

    assert result["status"] == "blocked"
    assert "suspicious_duplicate_cluster" in result["blocker_codes"]


def test_run_optimization_audit_restores_report_paths_from_runs_directory(tmp_path: Path):
    run_dir = tmp_path / "reports" / "optimizations" / "run-script"
    runs_dir = run_dir / "runs"
    runs_dir.mkdir(parents=True)

    sample = {
        "strategy": "macd_triple_divergence",
        "symbol": "BTCUSDT",
        "interval": "1d",
        "optimization_run_id": "run-script",
        "report_version": "2.0",
        "param_id": "param-a",
        "params": {"chainer_need_confirm": True},
        "summary": {
            "total_return_pct": 1.0,
            "hold_return_pct": 0.0,
            "sharpe": 1.0,
            "profit_factor": 1.1,
            "max_dd_pct": 2.0,
            "total_trades": 1,
            "total_signals": 1,
        },
        "signals": [],
        "trades": [
            {
                "id": 1,
                "dir": "L",
                "entry": "2026-01-01T00:00:00",
                "entry_px": 100.0,
                "exit": "2026-01-02T00:00:00",
                "exit_px": 101.0,
                "pnl_pct": 1.0,
                "pnl": 1.0,
                "bars_held": 1,
                "exit_reason_code": "signal_exit",
                "framework_initial_stop_price": 95.0,
            }
        ],
    }
    report_path = runs_dir / "sample.json"
    report_path.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
    (run_dir / "failures.json").write_text("[]", encoding="utf-8")

    run_optimization_audit(tmp_path, "run-script", block_on_failure=False)

    workbench = json.loads((run_dir / "workbench.json").read_text(encoding="utf-8"))
    assert workbench["items"][0]["links"]["primary_report_path"] == str(report_path)
