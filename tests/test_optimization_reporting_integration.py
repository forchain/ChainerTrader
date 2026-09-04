from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from trader.common.config import Config
from trader.strategy.trader_result import TraderResult
from trader.task.backtrader_task import process_backtrader
from trader.task.task_config import TaskConfig
from trader.task.task_manager import TaskManager
from trader.task.task_type import TaskType
from trader.utils.symbol_interval import Interval, SymbolInterval


class DummyLog:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass

    def error(self, *args, **kwargs):
        pass

    def debug(self, *args, **kwargs):
        pass

    def add_log_buffer(self, *args, **kwargs):
        pass


def _make_trader_result() -> TraderResult:
    return TraderResult(
        total_return_rate=10.0,
        max_drawdown=5.0,
        max_drawdown_duration=timedelta(days=2),
        volatility=1.0,
        win_rate=50.0,
        plr=1.2,
        avg_profit=5.0,
        avg_loss=-4.0,
        buys=2,
        sells=2,
        opts=[],
        hold_rate=3.0,
        data_len=100,
    )


def test_process_backtrader_emits_sample_report_metadata_for_optimization_runs(monkeypatch):
    captured_nodes = []

    class FakeNode:
        def __init__(self, *args, **kwargs):
            captured_nodes.append(kwargs)
            self.backtest_report = {
                "optimization_run_id": "run-1",
                "param_id": "param-a",
                "params": {"fast_period": 5},
                "dataset_ref": "dataset-a",
            }
            self.backtest_report_path = "reports/optimizations/run-1/runs/sample.json"

        def start(self):
            return _make_trader_result()

    monkeypatch.setattr("trader.task.backtrader_task.Node", FakeNode)

    tcfg = TaskConfig(
        id=1,
        ttype=TaskType.BACK_TRADER,
        symbol_interval=SymbolInterval("BTC-USDT", Interval.INTERVAL_1h),
        strategies=["macd_triple_divergence"],
        strategy_params={"fast_period": 5},
        param_id="param-a",
        optimization_run_id="run-1",
        dataset_ref=SimpleNamespace(dataset_key="dataset-a"),
    )
    ts = SimpleNamespace(id=1, tret=None)
    result = []

    process_backtrader([Config(), object(), ["strategy"], tcfg, ts], result)

    assert captured_nodes[0]["strategy_params"] == {"fast_period": 5}
    assert result[0][2]["report"]["param_id"] == "param-a"
    assert result[0][2]["report_path"] == "reports/optimizations/run-1/runs/sample.json"


def test_task_manager_finalize_optimization_runs_writes_run_directory(monkeypatch, tmp_path: Path):
    cfg = Config()
    task_manager = TaskManager(cfg, DummyLog(), db_manager=None, exchange=None)
    tasks = [
        TaskConfig(
            id=1,
            ttype=TaskType.BACK_TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval.INTERVAL_1h),
            strategies=["macd_triple_divergence"],
            optimization_run_id="run-1",
            param_id="param-a",
            strategy_params={"fast_period": 5},
        )
    ]
    sample_records = [
        {
            "task_id": 1,
            "report": {
                "strategy": "macd_triple_divergence",
                "optimization_run_id": "run-1",
                "report_version": "2.0",
                "param_id": "param-a",
                "params": {"fast_period": 5},
                "dataset_ref": "dataset-a",
                "summary": {
                    "total_return_pct": 10.0,
                    "hold_return_pct": 3.0,
                    "sharpe": 1.2,
                    "profit_factor": 1.4,
                    "max_dd_pct": 8.0,
                    "total_trades": 2,
                },
            },
            "report_path": "reports/optimizations/run-1/runs/sample.json",
        }
    ]
    failures = [
        {
            "task_id": 2,
            "dataset_key": "dataset-b",
            "reason": "download_failed",
            "message": "failed to download missing range",
        }
    ]

    monkeypatch.chdir(tmp_path)
    task_manager._finalize_optimization_runs(tasks, sample_records, failures)

    assert (tmp_path / "reports" / "optimizations" / "run-1" / "manifest.json").exists()
