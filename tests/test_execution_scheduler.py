import asyncio
from concurrent.futures import TimeoutError as FutureTimeoutError
import json
import threading
import time
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

from trader.common.config import Config
from trader.strategy.trader_result import TraderResult
from trader.task.backtrader_task import BacktestSampleSpec, run_backtest_sample
from trader.task.optimization_runtime import OptimizationRuntimeStatus
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


def _write_dataset_csv(csv_path: Path):
    csv_path.write_text(
        "1700000000000,100,101,99,100.5,10,1700003599000,20,3,4,5,0\n",
        encoding="utf-8",
    )


def _make_backtest_task(task_id: int, symbol: str, interval: Interval, start_time: int, end_time: int):
    return TaskConfig(
        id=task_id,
        ttype=TaskType.BACK_TRADER,
        symbol_interval=SymbolInterval(symbol, interval),
        start_time=start_time,
        end_time=end_time,
        strategies=["macd_triple_divergence"],
        optimization_run_id="run-1",
        param_id=f"param-{task_id}",
        strategy_params={"fast_period": task_id},
        auto_download=True,
    )


def _make_sample_spec(dataset_path: Path) -> BacktestSampleSpec:
    return BacktestSampleSpec(
        task_id=1,
        strategy_name="macd_triple_divergence",
        strategy_names=["macd_triple_divergence"],
        symbol="BTC-USDT",
        interval="1h",
        start_time=1_700_000_000,
        end_time=1_700_000_000 + 3600,
        data_path=str(dataset_path),
        use_data_range=False,
        free_cash=100000.0,
        cfg=Config().to_dict(),
        strategy_params={"fast_period": 5},
        optimization_run_id="run-1",
        param_id="param-a",
        dataset_key="dataset-a",
    )


def test_prepare_backtest_datasets_runs_unique_jobs_with_bounded_parallelism(monkeypatch):
    async def _test():
        cfg = Config()
        task_manager = TaskManager(cfg, DummyLog(), db_manager=SimpleNamespace(kline=SimpleNamespace()), exchange=SimpleNamespace())
        tasks = [
            _make_backtest_task(1, "BTC-USDT", Interval.INTERVAL_1h, 1_700_000_000, 1_700_000_000 + 3600),
            _make_backtest_task(2, "BTC-USDT", Interval.INTERVAL_1h, 1_700_000_000, 1_700_000_000 + 3600),
            _make_backtest_task(3, "ETH-USDT", Interval.INTERVAL_1h, 1_700_000_000, 1_700_000_000 + 3600),
            _make_backtest_task(4, "SOL-USDT", Interval.INTERVAL_4h, 1_700_000_000, 1_700_000_000 + 4 * 3600),
        ]

        active = 0
        max_active = 0
        call_keys = []
        lock = threading.Lock()

        monkeypatch.setattr(TaskManager, "_dataset_prepare_max_workers", lambda self: 2)

        def fake_prepare_sync(self, resolver, symbol_interval, start_time, end_time, allow_download, max_download_ranges=None):
            nonlocal active, max_active
            dataset_key = (symbol_interval.name(), start_time, end_time)
            with lock:
                active += 1
                max_active = max(max_active, active)
                call_keys.append(dataset_key)
            time.sleep(0.05)
            with lock:
                active -= 1
            return SimpleNamespace(
                ok=True,
                dataset_ref=SimpleNamespace(
                    path=f"/tmp/{symbol_interval.name()}-{start_time}-{end_time}.csv",
                    dataset_key=f"{symbol_interval.name()}|{start_time}|{end_time}",
                ),
            )

        monkeypatch.setattr(TaskManager, "_prepare_dataset_job_sync", fake_prepare_sync)

        failures = await task_manager._prepare_backtest_datasets(tasks)

        assert failures == []
        assert len(call_keys) == 3
        assert max_active > 1
        assert max_active <= 2
        assert tasks[0].dataset_ref.path == tasks[1].dataset_ref.path

    asyncio.run(_test())


def test_prepare_backtest_datasets_times_out_one_dataset_and_continues(monkeypatch, tmp_path: Path):
    async def _test():
        cfg = Config()
        task_manager = TaskManager(cfg, DummyLog(), db_manager=SimpleNamespace(kline=SimpleNamespace()), exchange=SimpleNamespace())
        slow_task = _make_backtest_task(1, "BTC-USDT", Interval.INTERVAL_1h, 1_700_000_000, 1_700_000_000 + 3600)
        fast_task = _make_backtest_task(2, "ETH-USDT", Interval.INTERVAL_1h, 1_700_000_000, 1_700_000_000 + 3600)

        monkeypatch.setattr(TaskManager, "_optimization_dataset_prepare_timeout_seconds", lambda self: 0.01, raising=False)

        async def fake_prepare_job(self, resolver, symbol_interval, start_time, end_time, allow_download, max_download_ranges=None):
            if symbol_interval.symbol() == "BTCUSDT":
                await asyncio.sleep(0.05)
            return SimpleNamespace(
                ok=True,
                dataset_ref=SimpleNamespace(
                    path=str(tmp_path / f"{symbol_interval.symbol()}.csv"),
                    dataset_key=f"{symbol_interval.name()}|{start_time}|{end_time}",
                ),
            )

        monkeypatch.setattr(TaskManager, "_prepare_dataset_job", fake_prepare_job)

        failures = await task_manager._prepare_backtest_datasets([slow_task, fast_task])

        assert len(failures) == 1
        assert failures[0]["task_id"] == slow_task.id
        assert failures[0]["reason"] == "dataset_timeout"
        assert slow_task.dataset_ref is None
        assert fast_task.dataset_ref.dataset_key.startswith("ETHUSDT-1h")

    asyncio.run(_test())


def test_prepare_backtest_datasets_emits_runtime_dataset_events(monkeypatch, tmp_path: Path):
    async def _test():
        cfg = Config()
        task_manager = TaskManager(cfg, DummyLog(), db_manager=SimpleNamespace(kline=SimpleNamespace()), exchange=SimpleNamespace())
        task = _make_backtest_task(1, "BTC-USDT", Interval.INTERVAL_1h, 1_700_000_000, 1_700_000_000 + 3600)
        runtime = OptimizationRuntimeStatus(tmp_path / "run", "run-1", total_samples=1, total_datasets=1, configured_workers=1)
        runtime.start()

        async def fake_prepare_job(self, resolver, symbol_interval, start_time, end_time, allow_download, max_download_ranges=None):
            return SimpleNamespace(
                ok=True,
                dataset_ref=SimpleNamespace(
                    path=str(tmp_path / "BTCUSDT.csv"),
                    dataset_key=f"{symbol_interval.name()}|{start_time}|{end_time}",
                ),
            )

        monkeypatch.setattr(TaskManager, "_prepare_dataset_job", fake_prepare_job)

        failures = await task_manager._prepare_backtest_datasets([task], {"run-1": runtime})

        events = [
            json.loads(line)
            for line in (tmp_path / "run" / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ]

        assert failures == []
        assert [event["event"] for event in events] == [
            "run_started",
            "dataset_job_started",
            "dataset_job_succeeded",
        ]

    asyncio.run(_test())


def test_execute_sample_specs_uses_process_pool_with_cpu_bound_limit(monkeypatch, tmp_path: Path):
    async def _test():
        cfg = Config()
        task_manager = TaskManager(cfg, DummyLog(), db_manager=None, exchange=None)
        sample_specs = [
            _make_sample_spec(tmp_path / "a.csv"),
            BacktestSampleSpec(**{**_make_sample_spec(tmp_path / "b.csv").__dict__, "task_id": 2, "param_id": "param-b"}),
            BacktestSampleSpec(**{**_make_sample_spec(tmp_path / "c.csv").__dict__, "task_id": 3, "param_id": "param-c"}),
        ]

        captured = {"max_workers": None, "submitted": []}

        class FakeFuture:
            def __init__(self, value):
                self._value = value

            def result(self, timeout=None):
                return self._value

        class FakeExecutor:
            def __init__(self, max_workers):
                captured["max_workers"] = max_workers

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def submit(self, func, spec):
                captured["submitted"].append(spec.task_id)
                return FakeFuture(
                    SimpleNamespace(
                        ok=True,
                        task_id=spec.task_id,
                        trader_result={"total_return_rate": 1.0},
                        logs=[],
                        report={"optimization_run_id": spec.optimization_run_id},
                        report_path=f"reports/optimizations/{spec.optimization_run_id}/runs/{spec.task_id}.json",
                        error=None,
                    )
                )

        monkeypatch.setattr(TaskManager, "_sample_max_workers", lambda self: 2)
        monkeypatch.setattr("trader.task.task_manager.ProcessPoolExecutor", FakeExecutor)

        results = await task_manager._execute_sample_specs(sample_specs)

        assert captured["max_workers"] == 2
        assert captured["submitted"] == [1, 2, 3]
        assert [result.task_id for result in results] == [1, 2, 3]

    asyncio.run(_test())


def test_execute_sample_specs_records_timeout_and_continues(monkeypatch, tmp_path: Path):
    cfg = Config(optimization_sample_timeout_seconds=0.01)
    task_manager = TaskManager(cfg, DummyLog(), db_manager=None, exchange=None)
    first = _make_sample_spec(tmp_path / "timeout.csv")
    second = BacktestSampleSpec(**{**_make_sample_spec(tmp_path / "ok.csv").__dict__, "task_id": 2, "param_id": "param-b"})

    class TimeoutFuture:
        def result(self, timeout=None):
            raise FutureTimeoutError()

        def cancel(self):
            return True

    class SuccessFuture:
        def __init__(self, spec):
            self.spec = spec

        def result(self, timeout=None):
            return SimpleNamespace(
                ok=True,
                task_id=self.spec.task_id,
                trader_result={"total_return_rate": 1.0},
                logs=[],
                report={"optimization_run_id": self.spec.optimization_run_id},
                report_path=f"reports/optimizations/{self.spec.optimization_run_id}/runs/{self.spec.task_id}.json",
                error=None,
                timed_out=False,
            )

        def cancel(self):
            return False

    class FakeExecutor:
        def __init__(self, max_workers):
            self.submitted = []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def submit(self, func, spec):
            self.submitted.append(spec)
            return TimeoutFuture() if spec.task_id == first.task_id else SuccessFuture(spec)

    monkeypatch.setattr("trader.task.task_manager.ProcessPoolExecutor", FakeExecutor)

    results = task_manager._execute_sample_specs_sync([first, second])

    assert len(results) == 2
    assert results[0].ok is False
    assert results[0].task_id == first.task_id
    assert results[0].timed_out is True
    assert results[0].error == "sample execution exceeded timeout budget"
    assert results[1].ok is True
    assert results[1].task_id == second.task_id


def test_run_backtest_sample_builds_runtime_objects_from_sample_spec(monkeypatch, tmp_path: Path):
    dataset_path = tmp_path / "prepared.csv"
    _write_dataset_csv(dataset_path)

    csv_calls = []
    strategy_calls = []
    node_calls = []

    class FakeCSVData:
        def __init__(self, **kwargs):
            csv_calls.append(kwargs)

    class FakeNode:
        def __init__(self, *args, **kwargs):
            node_calls.append(kwargs)
            self.backtest_report = {
                "optimization_run_id": kwargs["report_context"]["optimization_run_id"],
                "param_id": kwargs["report_context"]["param_id"],
                "params": kwargs["report_context"]["params"],
                "dataset_ref": kwargs["report_context"]["dataset_ref"],
            }
            self.backtest_report_path = "reports/optimizations/run-1/runs/1.json"

        def start(self):
            return TraderResult(
                total_return_rate=10.0,
                max_drawdown=5.0,
                max_drawdown_duration=timedelta(hours=1),
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

    monkeypatch.setattr("trader.task.backtrader_task.BinanceCSVData", FakeCSVData)
    monkeypatch.setattr(
        "trader.task.backtrader_task.parse_strategies",
        lambda strategies: strategy_calls.append(list(strategies)) or ["fake-strategy"],
    )
    monkeypatch.setattr("trader.task.backtrader_task.Node", FakeNode)

    result = run_backtest_sample(_make_sample_spec(dataset_path))

    assert strategy_calls == [["macd_triple_divergence"]]
    assert csv_calls == [{"dataname": str(dataset_path)}]
    assert node_calls[0]["strategy_params"] == {"fast_period": 5}
    assert result.ok is True
    assert result.report["param_id"] == "param-a"


def test_add_backtrader_task_builds_sample_specs_from_shared_dataset_refs(monkeypatch, tmp_path: Path):
    async def _test():
        cfg = Config()
        task_manager = TaskManager(cfg, DummyLog(), db_manager=None, exchange=None)
        queue = asyncio.Queue()
        shared_ref = SimpleNamespace(path=str(tmp_path / "shared.csv"), dataset_key="dataset-a")
        tasks = [
            _make_backtest_task(1, "BTC-USDT", Interval.INTERVAL_1h, 1_700_000_000, 1_700_000_000 + 3600),
            _make_backtest_task(2, "BTC-USDT", Interval.INTERVAL_1h, 1_700_000_000, 1_700_000_000 + 3600),
        ]

        async def fake_prepare(self, cfgs, runtimes=None):
            for cfg in cfgs:
                cfg.dataset_ref = shared_ref
            return []

        captured_specs = []

        async def fake_execute(self, sample_specs):
            captured_specs.extend(sample_specs)
            trader_result = TraderResult(
                total_return_rate=10.0,
                max_drawdown=5.0,
                max_drawdown_duration=timedelta(hours=1),
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
            ).to_dict()
            return [
                SimpleNamespace(
                    ok=True,
                    task_id=spec.task_id,
                    trader_result=trader_result,
                    logs=[],
                    report={
                        "strategy": spec.strategy_name,
                        "symbol": spec.symbol,
                        "interval": spec.interval,
                        "optimization_run_id": spec.optimization_run_id,
                        "param_id": spec.param_id,
                        "params": spec.strategy_params,
                        "dataset_ref": spec.dataset_key,
                        "summary": {
                            "total_return_pct": 10.0,
                            "hold_return_pct": 3.0,
                            "sharpe": 1.1,
                            "profit_factor": 1.3,
                            "max_dd_pct": 8.0,
                            "total_trades": 2,
                        },
                    },
                    report_path=f"reports/optimizations/run-1/runs/{spec.task_id}.json",
                    error=None,
                )
                for spec in sample_specs
            ]

        monkeypatch.setattr(TaskManager, "_prepare_backtest_datasets", fake_prepare)
        monkeypatch.setattr(TaskManager, "_execute_sample_specs", fake_execute)

        await task_manager.add_backtrader_task(tasks, queue)

        assert len(captured_specs) == 2
        assert captured_specs[0].data_path == captured_specs[1].data_path
        assert captured_specs[0].dataset_key == captured_specs[1].dataset_key == "dataset-a"
        assert queue.qsize() == 2

    asyncio.run(_test())


def test_add_backtrader_task_propagates_execution_failures_to_optimization_artifacts(monkeypatch, tmp_path: Path):
    async def _test():
        cfg = Config()
        task_manager = TaskManager(cfg, DummyLog(), db_manager=None, exchange=None)
        queue = asyncio.Queue()
        tasks = [
            _make_backtest_task(1, "BTC-USDT", Interval.INTERVAL_1h, 1_700_000_000, 1_700_000_000 + 3600),
            _make_backtest_task(2, "ETH-USDT", Interval.INTERVAL_1h, 1_700_000_000, 1_700_000_000 + 3600),
        ]

        async def fake_prepare(self, cfgs, runtimes=None):
            for index, cfg in enumerate(cfgs, start=1):
                cfg.dataset_ref = SimpleNamespace(path=str(tmp_path / f"{index}.csv"), dataset_key=f"dataset-{index}")
            return []

        trader_result = TraderResult(
            total_return_rate=10.0,
            max_drawdown=5.0,
            max_drawdown_duration=timedelta(hours=1),
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
        ).to_dict()

        async def fake_execute(self, sample_specs):
            return [
                SimpleNamespace(
                    ok=True,
                    task_id=sample_specs[0].task_id,
                    trader_result=trader_result,
                    logs=[],
                    report={
                        "strategy": sample_specs[0].strategy_name,
                        "symbol": sample_specs[0].symbol,
                        "interval": sample_specs[0].interval,
                        "optimization_run_id": sample_specs[0].optimization_run_id,
                        "param_id": sample_specs[0].param_id,
                        "params": sample_specs[0].strategy_params,
                        "dataset_ref": sample_specs[0].dataset_key,
                        "summary": {
                            "total_return_pct": 10.0,
                            "hold_return_pct": 3.0,
                            "sharpe": 1.1,
                            "profit_factor": 1.3,
                            "max_dd_pct": 8.0,
                            "total_trades": 2,
                        },
                    },
                    report_path="reports/optimizations/run-1/runs/1.json",
                    error=None,
                ),
                SimpleNamespace(
                    ok=False,
                    task_id=sample_specs[1].task_id,
                    trader_result=None,
                    logs=[],
                    report=None,
                    report_path=None,
                    error="worker crashed",
                ),
            ]

        finalized = {}

        def fake_finalize(self, cfgs, sample_records, failures):
            finalized["sample_records"] = list(sample_records)
            finalized["failures"] = list(failures)

        monkeypatch.setattr(TaskManager, "_prepare_backtest_datasets", fake_prepare)
        monkeypatch.setattr(TaskManager, "_execute_sample_specs", fake_execute)
        monkeypatch.setattr(TaskManager, "_finalize_optimization_runs", fake_finalize)

        await task_manager.add_backtrader_task(tasks, queue)

        assert len(finalized["sample_records"]) == 1
        assert len(finalized["failures"]) == 1
        assert finalized["failures"][0]["task_id"] == 2
        assert finalized["failures"][0]["reason"] == "execution_failed"
        assert finalized["failures"][0]["message"] == "worker crashed"
        assert queue.qsize() == 1

    asyncio.run(_test())


def test_add_backtrader_task_writes_runtime_status_with_final_report_run_id(monkeypatch, tmp_path: Path):
    async def _test():
        cfg = Config()
        task_manager = TaskManager(cfg, DummyLog(), db_manager=None, exchange=None)
        queue = asyncio.Queue()
        tasks = [_make_backtest_task(1, "BTC-USDT", Interval.INTERVAL_1h, 1_700_000_000, 1_700_000_000 + 3600)]
        tasks[0].optimization_run_id = "run-status-1"

        async def fake_prepare(self, cfgs, runtimes=None):
            for cfg in cfgs:
                cfg.dataset_ref = SimpleNamespace(path=str(tmp_path / "1.csv"), dataset_key="dataset-1")
            return []

        trader_result = TraderResult(
            total_return_rate=10.0,
            max_drawdown=5.0,
            max_drawdown_duration=timedelta(hours=1),
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
        ).to_dict()

        async def fake_execute(self, sample_specs):
            return [
                SimpleNamespace(
                    ok=True,
                    task_id=sample_specs[0].task_id,
                    trader_result=trader_result,
                    logs=[],
                    report={
                        "strategy": sample_specs[0].strategy_name,
                        "symbol": sample_specs[0].symbol,
                        "interval": sample_specs[0].interval,
                        "optimization_run_id": sample_specs[0].optimization_run_id,
                        "param_id": sample_specs[0].param_id,
                        "params": sample_specs[0].strategy_params,
                        "dataset_ref": sample_specs[0].dataset_key,
                        "summary": {
                            "total_return_pct": 10.0,
                            "hold_return_pct": 3.0,
                            "sharpe": 1.1,
                            "profit_factor": 1.3,
                            "max_dd_pct": 8.0,
                            "total_trades": 2,
                        },
                    },
                    report_path="reports/optimizations/run-status-1/runs/1.json",
                    error=None,
                )
            ]

        monkeypatch.setattr(TaskManager, "_prepare_backtest_datasets", fake_prepare)
        monkeypatch.setattr(TaskManager, "_execute_sample_specs", fake_execute)

        await task_manager.add_backtrader_task(tasks, queue)

        status = json.loads(Path("tmp/optimization_runs/run-status-1/status.json").read_text(encoding="utf-8"))
        manifest = json.loads(Path("reports/optimizations/run-status-1/manifest.json").read_text(encoding="utf-8"))
        events = [
            json.loads(line)
            for line in Path("tmp/optimization_runs/run-status-1/events.jsonl").read_text(encoding="utf-8").splitlines()
        ]

        assert status["run_id"] == manifest["optimization_run_id"] == "run-status-1"
        assert status["stage"] == "finished"
        assert status["samples_succeeded"] == 1
        assert events[0]["event"] == "run_started"
        assert events[-1]["event"] == "run_finished"

    asyncio.run(_test())


def test_add_backtrader_task_records_dataset_failures_as_skipped_samples(monkeypatch, tmp_path: Path):
    async def _test():
        cfg = Config()
        task_manager = TaskManager(cfg, DummyLog(), db_manager=None, exchange=None)
        queue = asyncio.Queue()
        failed = _make_backtest_task(1, "BTC-USDT", Interval.INTERVAL_1h, 1_700_000_000, 1_700_000_000 + 3600)
        runnable = _make_backtest_task(2, "ETH-USDT", Interval.INTERVAL_1h, 1_700_000_000, 1_700_000_000 + 3600)
        for task in (failed, runnable):
            task.optimization_run_id = "run-skip-1"

        async def fake_prepare(self, cfgs, runtimes=None):
            runnable.dataset_ref = SimpleNamespace(path=str(tmp_path / "runnable.csv"), dataset_key="dataset-ok")
            return [
                {
                    "task_id": failed.id,
                    "dataset_key": "dataset-bad",
                    "reason": "dataset_timeout",
                    "message": "too slow",
                }
            ]

        captured_specs = []

        async def fake_execute(self, sample_specs):
            captured_specs.extend(sample_specs)
            return []

        monkeypatch.setattr(TaskManager, "_prepare_backtest_datasets", fake_prepare)
        monkeypatch.setattr(TaskManager, "_execute_sample_specs", fake_execute)

        await task_manager.add_backtrader_task([failed, runnable], queue)

        status = json.loads(Path("tmp/optimization_runs/run-skip-1/status.json").read_text(encoding="utf-8"))
        failures = json.loads(Path("reports/optimizations/run-skip-1/failures.json").read_text(encoding="utf-8"))
        events = [
            json.loads(line)
            for line in Path("tmp/optimization_runs/run-skip-1/events.jsonl").read_text(encoding="utf-8").splitlines()
        ]

        assert [spec.task_id for spec in captured_specs] == [runnable.id]
        assert status["samples_skipped"] == 1
        assert status["samples_failed"] == 0
        assert status["samples_completed"] == 1
        assert failures[0]["reason"] == "dataset_timeout"
        assert any(event["event"] == "sample_skipped" and event["task_id"] == failed.id for event in events)

    asyncio.run(_test())


def test_add_backtrader_task_records_sample_timeouts_distinctly(monkeypatch, tmp_path: Path):
    async def _test():
        cfg = Config()
        task_manager = TaskManager(cfg, DummyLog(), db_manager=None, exchange=None)
        queue = asyncio.Queue()
        task = _make_backtest_task(1, "BTC-USDT", Interval.INTERVAL_1h, 1_700_000_000, 1_700_000_000 + 3600)
        task.optimization_run_id = "run-timeout-1"

        async def fake_prepare(self, cfgs, runtimes=None):
            task.dataset_ref = SimpleNamespace(path=str(tmp_path / "timeout.csv"), dataset_key="dataset-timeout")
            return []

        async def fake_execute(self, sample_specs):
            return [
                SimpleNamespace(
                    ok=False,
                    task_id=task.id,
                    trader_result=None,
                    logs=[],
                    report=None,
                    report_path=None,
                    error="sample execution exceeded timeout budget",
                    timed_out=True,
                )
            ]

        monkeypatch.setattr(TaskManager, "_prepare_backtest_datasets", fake_prepare)
        monkeypatch.setattr(TaskManager, "_execute_sample_specs", fake_execute)

        await task_manager.add_backtrader_task([task], queue)

        status = json.loads(Path("tmp/optimization_runs/run-timeout-1/status.json").read_text(encoding="utf-8"))
        failures = json.loads(Path("reports/optimizations/run-timeout-1/failures.json").read_text(encoding="utf-8"))
        events = [
            json.loads(line)
            for line in Path("tmp/optimization_runs/run-timeout-1/events.jsonl").read_text(encoding="utf-8").splitlines()
        ]

        assert status["samples_timed_out"] == 1
        assert status["samples_failed"] == 0
        assert failures[0]["reason"] == "sample_timeout"
        assert any(event["event"] == "sample_timed_out" and event["task_id"] == task.id for event in events)

    asyncio.run(_test())


def test_add_backtrader_task_aborts_when_runnable_ratio_too_low(monkeypatch, tmp_path: Path):
    async def _test():
        cfg = Config(optimization_min_runnable_ratio=0.5)
        task_manager = TaskManager(cfg, DummyLog(), db_manager=None, exchange=None)
        queue = asyncio.Queue()
        tasks = [
            _make_backtest_task(index, f"BTC{index}-USDT", Interval.INTERVAL_1h, 1_700_000_000, 1_700_000_000 + 3600)
            for index in range(1, 11)
        ]
        for task in tasks:
            task.optimization_run_id = "run-abort-low-runnable"

        async def fake_prepare(self, cfgs, runtimes=None):
            cfgs[-1].dataset_ref = SimpleNamespace(path=str(tmp_path / "ok.csv"), dataset_key="dataset-ok")
            return [
                {
                    "task_id": task.id,
                    "dataset_key": f"dataset-{task.id}",
                    "reason": "dataset_timeout",
                    "message": "too slow",
                }
                for task in cfgs[:-1]
            ]

        async def fake_execute(self, sample_specs):
            raise AssertionError("sample execution should not start after low-runnable abort")

        monkeypatch.setattr(TaskManager, "_prepare_backtest_datasets", fake_prepare)
        monkeypatch.setattr(TaskManager, "_execute_sample_specs", fake_execute)

        await task_manager.add_backtrader_task(tasks, queue)

        status = json.loads(Path("tmp/optimization_runs/run-abort-low-runnable/status.json").read_text(encoding="utf-8"))
        summary = json.loads(Path("tmp/optimization_runs/run-abort-low-runnable/abort_summary.json").read_text(encoding="utf-8"))
        manifest = json.loads(Path("reports/optimizations/run-abort-low-runnable/manifest.json").read_text(encoding="utf-8"))
        failures = json.loads(Path("reports/optimizations/run-abort-low-runnable/failures.json").read_text(encoding="utf-8"))

        assert status["stage"] == "aborted"
        assert status["abort_reason"] == "insufficient_runnable_samples"
        assert status["samples_skipped"] == 9
        assert summary["reason"] == "insufficient_runnable_samples"
        assert manifest["aborted"] is True
        assert failures[-1]["reason"] == "run_aborted"
        assert failures[-1]["message"] == "insufficient_runnable_samples"

    asyncio.run(_test())
