import json
from pathlib import Path

from trader.task.optimization_report import build_optimization_artifacts, write_optimization_artifacts


def _signal(signal_time: str, status: str, side: str = "LONG") -> dict:
    return {
        "signal_id": 1,
        "signal_time": signal_time,
        "signal_type": "bottom_divergence" if side == "LONG" else "top_divergence",
        "trade_outcome": {"status": status},
    }


def _trade(
    *,
    trade_id: int,
    entry_signal_time: str,
    entry_time: str,
    exit_signal_time: str | None,
    exit_time: str,
    qty: float,
    exit_reason_code: str,
    exit_reason_label: str,
    initial_stop: float,
    final_stop: float,
    tp_price: float | None,
) -> dict:
    return {
        "id": trade_id,
        "dir": "L",
        "entry_signal_time": entry_signal_time,
        "entry": entry_time,
        "entry_px": 100.0,
        "exit_signal_time": exit_signal_time,
        "exit": exit_time,
        "exit_px": 110.0 if exit_reason_code != "framework_stop" else 95.0,
        "qty": qty,
        "pnl_pct": 10.0 if exit_reason_code != "framework_stop" else -5.0,
        "pnl": 10.0 if exit_reason_code != "framework_stop" else -5.0,
        "bars_held": 2,
        "exit_reason_code": exit_reason_code,
        "exit_reason_label": exit_reason_label,
        "framework_initial_stop_price": initial_stop,
        "framework_final_stop_price": final_stop,
        "framework_tp_price": tp_price,
    }


def test_workbench_artifacts_include_parameter_observability_and_dynamic_entry(tmp_path: Path):
    sample_reports = [
        {
            "strategy": "macd_triple_divergence",
            "symbol": "BTCUSDT",
            "interval": "1d",
            "optimization_run_id": "run-workbench",
            "report_version": "2.0",
            "param_id": "param-a",
            "params": {
                "chainer_need_confirm": True,
                "chainer_stoploss_atr_mult": 1.0,
                "chainer_risk_reward_ratio": 1.5,
                "chainer_enable_breakeven": True,
                "chainer_min_equity_percent": 0.5,
            },
            "dataset_ref": "dataset-a",
            "summary": {
                "total_return_pct": 12.0,
                "hold_return_pct": 5.0,
                "sharpe": 1.6,
                "profit_factor": 1.8,
                "max_dd_pct": 10.0,
                "active_max_dd_pct": 4.0,
                "total_trades": 2,
            },
            "report_path": "reports/optimizations/run-workbench/runs/a.json",
            "signals": [
                _signal("2026-01-01T00:00:00", "entered"),
                _signal("2026-01-05T00:00:00", "blocked_equity"),
            ],
            "trades": [
                _trade(
                    trade_id=1,
                    entry_signal_time="2026-01-01T00:00:00",
                    entry_time="2026-01-02T00:00:00",
                    exit_signal_time="2026-01-03T00:00:00",
                    exit_time="2026-01-04T00:00:00",
                    qty=12.5,
                    exit_reason_code="risk_reward_take_profit",
                    exit_reason_label="达到预设风险收益比退出",
                    initial_stop=95.0,
                    final_stop=101.0,
                    tp_price=110.0,
                ),
                _trade(
                    trade_id=2,
                    entry_signal_time="2026-01-06T00:00:00",
                    entry_time="2026-01-07T00:00:00",
                    exit_signal_time=None,
                    exit_time="2026-01-08T00:00:00",
                    qty=8.0,
                    exit_reason_code="framework_stop",
                    exit_reason_label="框架止损退出",
                    initial_stop=96.0,
                    final_stop=96.0,
                    tp_price=112.0,
                ),
            ],
            "open_trades": [
                {
                    "id": 3,
                    "dir": "S",
                    "status": "open",
                    "entry_signal_time": "2026-01-09T00:00:00",
                    "entry": "2026-01-10T00:00:00",
                    "entry_px": 120.0,
                    "current_px": 90.0,
                    "qty": 4.0,
                    "unrealized_pnl_pct": 25.0,
                    "exit_reason_code": "open_position",
                    "exit_reason_label": "未平仓",
                    "framework_initial_stop_price": 130.0,
                    "framework_final_stop_price": 110.0,
                    "framework_tp_price": None,
                }
            ],
        }
    ]

    artifacts = build_optimization_artifacts("run-workbench", sample_reports, [])

    assert "workbench" in artifacts
    item = artifacts["workbench"]["items"][0]
    assert item["rank"] == 1
    assert item["links"]["primary_report_path"] == "reports/optimizations/run-workbench/runs/a.json"
    assert item["trades"][0]["qty"] == 12.5
    assert item["trades"][-1]["status"] == "open"
    assert item["trades"][-1]["current_px"] == 90.0
    assert item["summary"]["avg_hold_return_pct"] == 5.0
    assert item["summary"]["avg_excess_return_pct"] == 7.0
    assert item["summary"]["avg_max_dd_pct"] == 4.0
    assert item["summary"]["avg_full_max_dd_pct"] == 10.0
    assert item["summary"]["open_trades"] == 1
    assert item["views"] == ["parameter_observability", "trade_details", "audit_context"]

    observations = {obs["parameter"]: obs for obs in item["parameter_observations"]}
    assert observations["chainer_need_confirm"]["status"] == "has_evidence"
    assert observations["chainer_need_confirm"]["stats"]["delayed_entry_count"] == 3
    assert observations["chainer_risk_reward_ratio"]["status"] == "has_evidence"
    assert observations["chainer_enable_breakeven"]["status"] == "has_evidence"
    assert observations["chainer_min_equity_percent"]["status"] == "has_evidence"
    assert observations["chainer_min_equity_percent"]["stats"]["blocked_equity_count"] == 1

    run_dir = write_optimization_artifacts(tmp_path, "run-workbench", sample_reports, [])
    workbench = json.loads((run_dir / "workbench.json").read_text(encoding="utf-8"))
    assert workbench["run"]["run_id"] == "run-workbench"
    assert workbench["items"][0]["trades"][0]["qty"] == 12.5
    assert workbench["items"][0]["trades"][-1]["status"] == "open"
    static_html = (run_dir / "workbench" / "index.html").read_text(encoding="utf-8")
    assert "window.__WORKBENCH_DATA__" in static_html
    assert "Optimization Validation Workbench" in static_html


def test_disabled_parameter_observation_is_not_reported_as_has_evidence():
    sample_reports = [
        {
            "strategy": "macd_triple_divergence",
            "symbol": "BTCUSDT",
            "interval": "1d",
            "optimization_run_id": "run-disabled",
            "report_version": "2.0",
            "param_id": "param-disabled",
            "params": {
                "chainer_need_confirm": False,
                "chainer_stoploss_atr_mult": 0.0,
                "chainer_risk_reward_ratio": 0.0,
                "chainer_enable_breakeven": False,
                "chainer_min_equity_percent": 0.0,
            },
            "dataset_ref": "dataset-a",
            "summary": {
                "total_return_pct": 1.0,
                "hold_return_pct": 0.5,
                "sharpe": 0.5,
                "profit_factor": 1.1,
                "max_dd_pct": 2.0,
                "total_trades": 1,
            },
            "report_path": "reports/optimizations/run-disabled/runs/a.json",
            "signals": [_signal("2026-01-01T00:00:00", "entered")],
            "trades": [
                _trade(
                    trade_id=1,
                    entry_signal_time="2026-01-01T00:00:00",
                    entry_time="2026-01-01T00:00:00",
                    exit_signal_time=None,
                    exit_time="2026-01-02T00:00:00",
                    qty=10.0,
                    exit_reason_code="signal_exit",
                    exit_reason_label="信号出场",
                    initial_stop=95.0,
                    final_stop=95.0,
                    tp_price=None,
                ),
            ],
        }
    ]

    artifacts = build_optimization_artifacts("run-disabled", sample_reports, [])
    observations = {obs["parameter"]: obs for obs in artifacts["workbench"]["items"][0]["parameter_observations"]}

    assert observations["chainer_need_confirm"]["status"] == "disabled"
    assert observations["chainer_stoploss_atr_mult"]["status"] == "disabled"
    assert observations["chainer_risk_reward_ratio"]["status"] == "disabled"
    assert observations["chainer_enable_breakeven"]["status"] == "disabled"
    assert observations["chainer_min_equity_percent"]["status"] == "disabled"


def test_need_confirm_without_signal_time_evidence_is_suspicious():
    sample_reports = [
        {
            "strategy": "macd_triple_divergence",
            "symbol": "BTCUSDT",
            "interval": "1d",
            "optimization_run_id": "run-confirm-gap",
            "report_version": "2.0",
            "param_id": "param-gap",
            "params": {"chainer_need_confirm": True},
            "dataset_ref": "dataset-a",
            "summary": {
                "total_return_pct": 1.0,
                "hold_return_pct": 0.5,
                "sharpe": 0.5,
                "profit_factor": 1.1,
                "max_dd_pct": 2.0,
                "total_trades": 1,
            },
            "report_path": "reports/optimizations/run-confirm-gap/runs/a.json",
            "signals": [_signal("2026-01-01T00:00:00", "entered")],
            "trades": [
                _trade(
                    trade_id=1,
                    entry_signal_time=None,
                    entry_time="2026-01-02T00:00:00",
                    exit_signal_time=None,
                    exit_time="2026-01-03T00:00:00",
                    qty=10.0,
                    exit_reason_code="signal_exit",
                    exit_reason_label="信号出场",
                    initial_stop=95.0,
                    final_stop=95.0,
                    tp_price=None,
                ),
            ],
        }
    ]

    artifacts = build_optimization_artifacts("run-confirm-gap", sample_reports, [])
    observations = {obs["parameter"]: obs for obs in artifacts["workbench"]["items"][0]["parameter_observations"]}

    assert observations["chainer_need_confirm"]["status"] == "suspicious"
    assert "未观察到时间分离证据" in observations["chainer_need_confirm"]["evidence"][0]
