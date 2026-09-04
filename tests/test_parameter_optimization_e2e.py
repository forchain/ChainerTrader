import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from trader.common.config import Config
from trader.task.dataset_resolver import DatasetResolver
from trader.task.optimization_report import write_optimization_artifacts
from trader.task.task_config import parse_task_config
from trader.task.task_manager import TaskManager
from trader.utils.kline import Kline
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


def make_kline(open_time: int, price: float) -> Kline:
    return Kline(
        open_time=open_time,
        open=price,
        high=price + 1,
        low=price - 1,
        close=price + 0.5,
        close_time=open_time + 3599,
        volume=10,
        vol_quote=20,
        trades=3,
        vol_taker_base=4,
        vol_taker_quote=5,
        ignore=0,
    )


class MemoryKlineStore:
    def __init__(self, initial: dict[str, list[Kline]] | None = None):
        self.data = {name: list(items) for name, items in (initial or {}).items()}

    def get_klines(self, name: str, start_time: int = 0, end_time: int = 0):
        rows = list(self.data.get(name, []))
        return [row for row in rows if (start_time == 0 or row.open_time >= start_time) and (end_time == 0 or row.open_time <= end_time)]

    def add_klines(self, name: str, klines: list[Kline]):
        bucket = self.data.setdefault(name, [])
        existing = {item.open_time for item in bucket}
        added = 0
        for item in klines:
            if item.open_time in existing:
                continue
            bucket.append(item)
            existing.add(item.open_time)
            added += 1
        bucket.sort(key=lambda item: item.open_time)
        return added


def test_e2e_dataset_resolver_repairs_gap_writes_db_and_materializes_cache(tmp_path: Path):
    async def _test():
        start_time = 1_700_000_000
        mid_time = start_time + 3600
        end_time = start_time + 7200
        symbol_interval = SymbolInterval("BTC-USDT", Interval.INTERVAL_1h)
        store = MemoryKlineStore(
            {
                symbol_interval.name(): [
                    make_kline(start_time, 100.0),
                    make_kline(end_time, 102.0),
                ]
            }
        )
        db_manager = SimpleNamespace(kline=store)

        async def downloader(name, log, db_manager_arg, collection_name, exchange, symbol_interval_arg, range_start, range_end, quit_event):
            assert collection_name == symbol_interval.name()
            assert range_start == mid_time
            assert range_end == mid_time
            db_manager_arg.kline.add_klines(collection_name, [make_kline(mid_time, 101.0)])
            return True

        resolver = DatasetResolver(
            db_manager=db_manager,
            exchange=SimpleNamespace(),
            log=DummyLog(),
            cache_dir=tmp_path,
            range_downloader=downloader,
        )

        result = await resolver.prepare(symbol_interval, start_time, end_time)

        assert result.ok is True
        assert [item.open_time for item in store.get_klines(symbol_interval.name(), start_time, end_time)] == [start_time, mid_time, end_time]
        cache_path = Path(result.dataset_ref.path)
        assert cache_path.exists()
        assert cache_path.read_text(encoding="utf-8").count("\n") == 3

    asyncio.run(_test())


def test_e2e_multi_symbol_multi_interval_config_shares_run_id_and_supports_aggregation():
    config = json.dumps(
        [
            {
                "task_type": "BACK_TRADER",
                "symbols": "BTC-USDT,ETH-USDT",
                "interval": "1h",
                "strategy": "macd_triple_divergence",
                "param_grid": {
                    "fast_period": [5, 8],
                    "slow_period": [20],
                },
            },
            {
                "task_type": "BACK_TRADER",
                "symbol": "BTC-USDT",
                "interval": "4h",
                "strategy": "macd_triple_divergence",
                "param_grid": {
                    "fast_period": [5, 8],
                    "slow_period": [20],
                },
            },
        ]
    )

    tasks = parse_task_config(config)

    assert len(tasks) == 6
    assert len({task.optimization_run_id for task in tasks}) == 1
    assert len({task.param_id for task in tasks if task.strategy_params == {"fast_period": 5, "slow_period": 20}}) == 1
    assert len({task.param_id for task in tasks if task.strategy_params == {"fast_period": 8, "slow_period": 20}}) == 1


def test_e2e_artifact_directory_contains_runs_aggregate_failures_and_rankings(tmp_path: Path):
    run_dir = write_optimization_artifacts(
        tmp_path,
        "run-1",
            [
                {
                    "strategy": "macd_triple_divergence",
                    "symbol": "BTCUSDT",
                    "interval": "1d",
                    "optimization_run_id": "run-1",
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
                "report_path": "reports/optimizations/run-1/runs/sample-a.json",
            }
        ],
        [
            {
                "task_id": 2,
                "dataset_key": "dataset-b",
                "reason": "download_failed",
                "message": "failed to download missing range",
            }
        ],
    )

    assert run_dir == tmp_path / "reports" / "optimizations" / "run-1"
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "aggregate.json").exists()
    assert (run_dir / "failures.json").exists()
    assert (run_dir / "rankings" / "by_score.json").exists()
    assert (run_dir / "rankings" / "by_excess_return.json").exists()


def test_e2e_optimization_run_id_links_manifest_run_reports_and_aggregate(tmp_path: Path):
    cfg = Config()
    task_manager = TaskManager(cfg, DummyLog(), db_manager=None, exchange=None)
    tasks = parse_task_config(
        json.dumps(
            [
                {
                    "task_type": "BACK_TRADER",
                    "symbols": "BTC-USDT,ETH-USDT",
                    "interval": "1h",
                    "strategy": "macd_triple_divergence",
                    "param_grid": {"fast_period": [5], "slow_period": [20]},
                }
            ]
        )
    )
    run_id = tasks[0].optimization_run_id
    sample_records = [
        {
                "task_id": task.id,
                "report": {
                    "strategy": task.strategy_name(),
                    "symbol": task.symbol_interval.symbol(),
                    "interval": task.symbol_interval.interval.value,
                    "optimization_run_id": run_id,
                    "report_version": "2.0",
                    "param_id": task.param_id,
                "params": task.strategy_params,
                "dataset_ref": f"{task.symbol_interval.name()}|dataset",
                "summary": {
                    "total_return_pct": 10.0 if task.symbol_interval.symbol() == "BTCUSDT" else 8.0,
                    "hold_return_pct": 3.0,
                    "sharpe": 1.2,
                    "profit_factor": 1.4,
                    "max_dd_pct": 7.0,
                    "total_trades": 2,
                },
            },
            "report_path": f"reports/optimizations/{run_id}/runs/{task.id}.json",
        }
        for task in tasks
    ]

    failures = []
    current_cwd = Path.cwd()
    try:
        import os

        os.chdir(tmp_path)
        task_manager._finalize_optimization_runs(tasks, sample_records, failures)
    finally:
        os.chdir(current_cwd)

    run_dir = tmp_path / "reports" / "optimizations" / run_id
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    aggregate = json.loads((run_dir / "aggregate.json").read_text(encoding="utf-8"))
    ranking = json.loads((run_dir / "rankings" / "by_score.json").read_text(encoding="utf-8"))

    assert manifest["optimization_run_id"] == run_id
    assert aggregate["optimization_run_id"] == run_id
    assert all(path.startswith(f"reports/optimizations/{run_id}/runs/") for path in manifest["run_reports"])
    assert all(item["param_id"] == tasks[0].param_id for item in aggregate["items"])
    assert {item["symbol"] for item in aggregate["items"]} == {"BTCUSDT", "ETHUSDT"}
    assert all(item["interval"] == "1h" for item in aggregate["items"])
    assert ranking[0]["symbol"] == "BTCUSDT"
    assert ranking[0]["interval"] == "1h"
    assert ranking[0]["param_id"] == tasks[0].param_id
