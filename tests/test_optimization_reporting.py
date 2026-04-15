import json
import os
from pathlib import Path

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
    assert "data-sort-table" in html
    assert "币种" in html
    assert "周期" in html
    assert "参数ID" in html
    assert "BTCUSDT" in html
    assert "1d" in html
    assert "param-a" in html


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
