import json
import os
from pathlib import Path
from types import SimpleNamespace

import backtrader as bt

from trader.analyzers.backtest_report import BacktestReportAnalyzer
from trader.exchange.binance.csvdata import BinanceCSVData
from trader.strategy.macd_triple_divergence import MacdTripleDivergenceStrategy
from trader.task.optimization_report import build_optimization_artifacts, write_optimization_artifacts


class _SilentReportStrategy(MacdTripleDivergenceStrategy):
    def log_info(self, msg):
        pass

    def log_debug(self, msg):
        pass


def _run_parameterized_report_probe(workdir: Path, report_context: dict):
    csv_path = Path(__file__).resolve().parents[1] / "data" / "BTCUSDT-1d-20170101-20251231.csv"
    previous_cwd = Path.cwd()
    os.chdir(workdir)
    try:
        cerebro = bt.Cerebro(stdstats=False)
        cerebro.addstrategy(_SilentReportStrategy)
        cerebro.adddata(BinanceCSVData(dataname=str(csv_path)))
        cerebro.addanalyzer(
            BacktestReportAnalyzer,
            _name="backtest_report",
            strategy_name="macd_triple_divergence",
            symbol="BTCUSDT",
            interval="1d",
            report_context=report_context,
        )
        cerebro.broker.setcash(100000.0)
        cerebro.broker.setcommission(commission=0.001)
        strategies = cerebro.run()
        analyzer = strategies[0].analyzers.backtest_report
        return analyzer.report, Path(analyzer.report_path)
    finally:
        os.chdir(previous_cwd)


def test_parameterized_sample_report_includes_optimization_context(tmp_path: Path):
    run_id = "run-20260411"
    report, report_path = _run_parameterized_report_probe(
        tmp_path,
        {
            "optimization_run_id": run_id,
            "param_id": "param-a",
            "params": {"fast_period": 5, "slow_period": 20},
            "dataset_ref": "BTCUSDT-1d|1700000000|1700086400",
        },
    )

    assert report["optimization_run_id"] == run_id
    assert report["report_version"] == "2.0"
    assert report["param_id"] == "param-a"
    assert report["params"] == {"fast_period": 5, "slow_period": 20}
    assert report["dataset_ref"] == "BTCUSDT-1d|1700000000|1700086400"
    assert report_path == tmp_path / "reports" / "optimizations" / run_id / "runs" / report_path.name
    written = json.loads(report_path.read_text(encoding="utf-8"))
    assert written["optimization_run_id"] == run_id


def test_optimization_artifacts_aggregate_samples_and_write_rankings(tmp_path: Path):
    sample_reports = [
        {
            "strategy": "macd_triple_divergence",
            "symbol": "BTCUSDT",
            "interval": "1d",
            "optimization_run_id": "run-1",
            "report_version": "2.0",
            "param_id": "param-a",
            "params": {"fast_period": 5, "slow_period": 20},
            "dataset_ref": "dataset-a",
            "summary": {
                "total_return_pct": 12.0,
                "hold_return_pct": 5.0,
                "sharpe": 1.6,
                "profit_factor": 1.8,
                "max_dd_pct": 10.0,
                "total_trades": 4,
            },
            "report_path": "reports/optimizations/run-1/runs/a.json",
            "trades": [
                {
                    "id": 1,
                    "dir": "L",
                    "entry_signal_time": "2025-12-31T00:00:00",
                    "entry": "2026-01-01T00:00:00",
                    "entry_px": 100.0,
                    "exit_signal_time": "2026-01-02T00:00:00",
                    "exit": "2026-01-03T00:00:00",
                    "exit_px": 90.0,
                    "pnl_pct": -10.0,
                    "pnl": -10.0,
                    "bars_held": 2,
                    "exit_reason_code": "framework_stop",
                    "exit_reason_label": "框架止损退出",
                }
            ],
        },
        {
            "strategy": "macd_triple_divergence",
            "symbol": "BTCUSDT",
            "interval": "1d",
            "optimization_run_id": "run-1",
            "report_version": "2.0",
            "param_id": "param-a",
            "params": {"fast_period": 5, "slow_period": 20},
            "dataset_ref": "dataset-b",
            "summary": {
                "total_return_pct": 9.0,
                "hold_return_pct": 4.0,
                "sharpe": 1.1,
                "profit_factor": 1.4,
                "max_dd_pct": 12.0,
                "total_trades": 3,
            },
            "report_path": "reports/optimizations/run-1/runs/b.json",
        },
        {
            "strategy": "macd_triple_divergence",
            "symbol": "ETHUSDT",
            "interval": "4h",
            "optimization_run_id": "run-1",
            "report_version": "2.0",
            "param_id": "param-b",
            "params": {"fast_period": 8, "slow_period": 30},
            "dataset_ref": "dataset-a",
            "summary": {
                "total_return_pct": 6.0,
                "hold_return_pct": 8.0,
                "sharpe": 0.2,
                "profit_factor": 0.9,
                "max_dd_pct": 18.0,
                "total_trades": 0,
            },
            "report_path": "reports/optimizations/run-1/runs/c.json",
        },
    ]
    failures = [
        {
            "task_id": 99,
            "dataset_key": "BTCUSDT-1d|1700000000|1700086400",
            "reason": "download_failed",
            "message": "failed to download missing range",
        }
    ]

    artifacts = build_optimization_artifacts("run-1", sample_reports, failures)
    aggregate_items = {(item["symbol"], item["interval"], item["param_id"]): item for item in artifacts["aggregate"]["items"]}

    assert aggregate_items[("BTCUSDT", "1d", "param-a")]["samples"] == 2
    assert aggregate_items[("BTCUSDT", "1d", "param-a")]["avg_excess_return_pct"] == 6.0
    assert aggregate_items[("BTCUSDT", "1d", "param-a")]["median_excess_return_pct"] == 6.0
    assert aggregate_items[("BTCUSDT", "1d", "param-a")]["beat_hold_ratio"] == 1.0
    assert aggregate_items[("BTCUSDT", "1d", "param-a")]["no_trade_ratio"] == 0.0
    assert aggregate_items[("ETHUSDT", "4h", "param-b")]["no_trade_ratio"] == 1.0
    assert artifacts["rankings"]["by_score"][0]["symbol"] == "BTCUSDT"
    assert artifacts["rankings"]["by_score"][0]["interval"] == "1d"
    assert artifacts["rankings"]["by_score"][0]["param_id"] == "param-a"
    assert artifacts["rankings"]["by_excess_return"][0]["symbol"] == "BTCUSDT"
    assert artifacts["rankings"]["by_excess_return"][0]["interval"] == "1d"
    assert artifacts["rankings"]["by_excess_return"][0]["param_id"] == "param-a"
    assert artifacts["manifest"]["failed_samples"] == 0
    assert artifacts["manifest"]["skipped_samples"] == 1
    assert artifacts["manifest"]["failure_records"] == 1
    assert artifacts["manifest"]["datasets"] == ["dataset-a", "dataset-b"]
    assert len(aggregate_items[("BTCUSDT", "1d", "param-a")]["sample_details"]) == 2
    assert aggregate_items[("BTCUSDT", "1d", "param-a")]["sample_details"][0]["trades"][0]["exit_reason_label"] == "框架止损退出"

    run_dir = write_optimization_artifacts(tmp_path, "run-1", sample_reports, failures)

    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "aggregate.json").exists()
    assert (run_dir / "rankings" / "by_score.json").exists()
    assert (run_dir / "rankings" / "index.html").exists()
    by_score = json.loads((run_dir / "rankings" / "by_score.json").read_text(encoding="utf-8"))
    assert by_score[0]["symbol"] == "BTCUSDT"
    assert by_score[0]["interval"] == "1d"
    assert by_score[0]["param_id"] == "param-a"
    html = (run_dir / "rankings" / "index.html").read_text(encoding="utf-8")
    assert "<table" in html
    assert "<colgroup" in html
    assert "data-sort-table" in html
    assert "币种" in html
    assert "周期" in html
    assert "参数ID" in html
    assert "fast_period" in html
    assert "slow_period" in html
    assert "交易列表" in html
    assert "renderDetails(row)" in html
    assert "applyColumnWidths()" in html
    assert "computeColumnWidth(spec)" in html
    assert 'class="drawer-row"' in html
    assert 'id="prev-page"' in html
    assert 'id="next-page"' in html
    assert "第 ${currentPage} / ${totalPages} 页" in html
    assert "持仓K线数" in html
    assert "退场原因" in html
    assert "进场信号" in html
    assert "出场信号" in html
    assert "框架止损退出" in html
    assert "renderReportPath(sample.report_path)" in html
    assert "renderTimeCell(trade.entry_signal_time, trade.entry)" in html
    assert "renderTimeCell(trade.exit_signal_time, trade.exit)" in html
    assert "sample-table compact-table" in html
    assert 'class="sample-columns"' in html
    assert "columnWidths = [56, 52, 172, 84, 172, 84, 84, 84, 78, 148]" in html
    assert "样例 #" not in html
    assert "dataset_ref:" not in html
    assert "BTCUSDT" in html
    assert "1d" in html
    assert "param-a" in html


def test_optimization_artifacts_merge_legacy_confirm_flags_for_display():
    sample_reports = [
        {
            "strategy": "macd_triple_divergence",
            "symbol": "BTCUSDT",
            "interval": "1d",
            "optimization_run_id": "run-legacy-confirm",
            "report_version": "2.0",
            "param_id": "param-confirm",
            "params": {
                "chainer_enter_need_confirm": False,
                "chainer_exit_need_confirm": False,
                "chainer_mode": "LONG_ONLY",
            },
            "dataset_ref": "dataset-a",
            "summary": {
                "total_return_pct": 5.0,
                "hold_return_pct": 1.0,
                "sharpe": 1.0,
                "profit_factor": 1.2,
                "max_dd_pct": 3.0,
                "total_trades": 1,
            },
        }
    ]

    artifacts = build_optimization_artifacts("run-legacy-confirm", sample_reports, [])

    assert artifacts["aggregate"]["items"][0]["params"] == {
        "chainer_mode": "LONG_ONLY",
        "chainer_need_confirm": False,
    }


def test_optimization_artifacts_preserve_structured_mixed_result_reasons():
    sample_reports = [
        {
            "strategy": "macd_triple_divergence",
            "symbol": "BTCUSDT",
            "interval": "1d",
            "optimization_run_id": "run-mixed",
            "report_version": "2.0",
            "param_id": "param-a",
            "params": {"fast_period": 5},
            "dataset_ref": "dataset-a",
            "summary": {
                "total_return_pct": 9.0,
                "hold_return_pct": 3.0,
                "sharpe": 1.1,
                "profit_factor": 1.3,
                "max_dd_pct": 8.0,
                "total_trades": 2,
            },
        }
    ]
    failures = [
        {"task_id": 2, "dataset_key": "dataset-b", "reason": "execution_failed", "message": "worker crashed"},
        {"task_id": 3, "dataset_key": "dataset-c", "reason": "sample_timeout", "message": "too slow"},
        {"task_id": 4, "dataset_key": "dataset-d", "reason": "dataset_timeout", "message": "dataset too slow"},
        {"task_id": None, "dataset_key": None, "reason": "run_aborted", "message": "high_failure_rate"},
    ]

    artifacts = build_optimization_artifacts("run-mixed", sample_reports, failures)

    assert artifacts["aggregate"]["items"]
    assert artifacts["manifest"]["completed_samples"] == 1
    assert artifacts["manifest"]["failed_samples"] == 1
    assert artifacts["manifest"]["timed_out_samples"] == 1
    assert artifacts["manifest"]["skipped_samples"] == 1
    assert artifacts["manifest"]["aborted"] is True
    assert artifacts["failures"] == failures


def test_backtest_report_enrichment_uses_tradeid_mapping_when_broker_ref_differs():
    analyzer = BacktestReportAnalyzer.__new__(BacktestReportAnalyzer)
    analyzer._trades = [
        {
            "id": 7,
            "broker_ref": 58,
            "entry_signal_time": None,
            "exit_signal_time": None,
            "exit_reason_code": None,
            "exit_reason_label": None,
            "exit_reason_detail": None,
            "stop_multiple_r": None,
            "risk_reward_ratio": None,
            "framework_initial_stop_price": None,
            "framework_final_stop_price": None,
            "framework_tp_price": None,
            "strategy_suggested_stop_price": None,
        }
    ]
    analyzer.strategy = SimpleNamespace(
        _trades_by_id={
            7: SimpleNamespace(
                exit_reason_code="framework_stop",
                exit_reason_label="框架止损退出",
                exit_reason_detail="触发框架止损，止损位达到 -1.00R",
                stop_multiple_r=-1.0,
                exit_risk_reward_ratio=None,
                initial_stop_price=98.0,
                stop_price=99.5,
                tp_price=112.0,
                signal_metadata={"signal_time": "2025-01-01T00:00:00", "suggested_stop_price": 90.0},
                exit_key_kline_ref=SimpleNamespace(dt=SimpleNamespace(isoformat=lambda: "2025-01-03T00:00:00")),
            )
        }
    )

    analyzer._enrich_trade_records_from_contexts()

    assert analyzer._trades[0]["entry_signal_time"] == "2025-01-01T00:00:00"
    assert analyzer._trades[0]["exit_signal_time"] == "2025-01-03T00:00:00"
    assert analyzer._trades[0]["exit_reason_code"] == "framework_stop"
    assert analyzer._trades[0]["exit_reason_label"] == "框架止损退出"
    assert analyzer._trades[0]["stop_multiple_r"] == -1.0
    assert analyzer._trades[0]["framework_initial_stop_price"] == 98.0
    assert analyzer._trades[0]["framework_final_stop_price"] == 99.5
    assert analyzer._trades[0]["framework_tp_price"] == 112.0
    assert analyzer._trades[0]["strategy_suggested_stop_price"] == 90.0
