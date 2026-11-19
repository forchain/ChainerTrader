from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.persistence_harness import InMemoryTaskRepository
from trader.adapters.outbound.backtrader.backtest_runner import BacktestTaskRunner
from trader.adapters.outbound.backtrader.data import BinanceData
from trader.adapters.outbound.files.dataset import CsvDatasetFileStore
from trader.core.marketdata.domain import DatasetPreparationResult, DatasetRef
from trader.core.shared.domain import Interval, Kline, SymbolInterval
from trader.core.task import TaskConfig, TaskRunner, TaskStateType, TaskType


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _DummyLog:
    def info(self, *_args, **_kwargs):
        pass

    def warning(self, *_args, **_kwargs):
        pass

    def error(self, *_args, **_kwargs):
        pass

    def debug(self, *_args, **_kwargs):
        pass

    def add_log_buffer(self, *_args, **_kwargs):
        pass


class _FakeKlineRepo:
    def __init__(self, klines: list[Kline]):
        self.klines = klines
        self.calls: list[tuple[str, int, int]] = []

    async def get_klines(self, name: str, start_time: int = 0, end_time: int = 0) -> list[Kline]:
        self.calls.append((name, start_time, end_time))
        return list(self.klines)


class _FakeDatasetResolver:
    def __init__(self, start_time: int, end_time: int):
        self.start_time = start_time
        self.end_time = end_time
        self.calls: list[tuple[str, int, int, bool]] = []

    async def prepare(self, symbol_interval: SymbolInterval, start_time: int, end_time: int, *, allow_download: bool = False):
        self.calls.append((symbol_interval.name(), start_time, end_time, allow_download))
        return DatasetPreparationResult(
            ok=True,
            dataset_ref=DatasetRef(
                dataset_key=f"{symbol_interval.name()}|{self.start_time}|{self.end_time}",
                source_type="db",
                symbol=symbol_interval.symbol(),
                interval=symbol_interval.interval.value,
                start_time=self.start_time,
                end_time=self.end_time,
            ),
        )


def _kline(open_time: int) -> Kline:
    return Kline(
        open_time=open_time,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        close_time=open_time + 3599,
        volume=10.0,
        vol_quote=20.0,
        trades=3,
        vol_taker_base=4.0,
        vol_taker_quote=5.0,
        ignore=0.0,
    )


@pytest.mark.anyio
async def test_backtest_task_runner_executes_db_backtest_and_persists_via_ports():
    task_repo = InMemoryTaskRepository()
    kline_repo = _FakeKlineRepo([_kline(1_700_000_000), _kline(1_700_003_600)])
    resolver = _FakeDatasetResolver(1_700_000_000, 1_700_003_600)
    node_calls = []

    class _FakeNode:
        def __init__(self, name, strategy, si, cfg, log, data, **_kwargs):
            node_calls.append((name, strategy, si.name(), type(data)))
            self.backtest_report = {"summary": {"total_return_rate": 12.5}}
            self.backtest_report_path = None

        def start(self):
            return SimpleNamespace(total_return_rate=12.5, to_dict=lambda: {"total_return_rate": 12.5})

    cfg = SimpleNamespace(cash=10000.0, commission=0.001, warmup_candles=5, db="sqlite://:memory:", plot=False)
    runner = BacktestTaskRunner(
        cfg=cfg,
        log=_DummyLog(),
        task_repository=task_repo,
        kline_repository=kline_repo,
        dataset_resolver=resolver,
        dataset_file_store=CsvDatasetFileStore(),
        strategy_parser=lambda names: [f"strat:{n}" for n in names],
        node_factory=_FakeNode,
    )
    assert isinstance(runner, TaskRunner)

    tcfg = TaskConfig(
        id=77,
        ttype=TaskType.BACK_TRADER,
        symbol_interval=SymbolInterval("BTC-USDT", Interval.INTERVAL_1h),
        start_time=1_700_000_000,
        end_time=1_700_003_600,
        strategies=["macd_triple_divergence"],
        auto_download=True,
        user_id=3,
    )

    outcome = await runner.run(tcfg)

    assert resolver.calls == [("BTCUSDT-1h", 1_700_000_000 - 5 * 3600, 1_700_003_600, True)]
    assert kline_repo.calls == [("BTCUSDT-1h", 1_700_000_000, 1_700_003_600)]
    assert node_calls == [("macd_triple_divergence", ["strat:macd_triple_divergence"], "BTCUSDT-1h", BinanceData)]
    persisted = await task_repo.get_task(77)
    assert persisted is not None
    assert persisted.state == TaskStateType.DONE
    assert persisted.user_id == 3
    assert outcome.trader_result.total_return_rate == 12.5


@pytest.mark.anyio
async def test_backtest_task_runner_executes_csv_backtest_through_ports(tmp_path: Path):
    csv_path = tmp_path / "BTCUSDT-1h.csv"
    csv_path.write_text(
        "\n".join(
            [
                "1700000000000,100,101,99,100.5,10,1700003599000,20,3,4,5,0",
                "1700003600000,100.5,102,100,101.5,12,1700007199000,25,4,5,6,0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    task_repo = InMemoryTaskRepository()
    node_calls = []

    class _FakeNode:
        def __init__(self, name, strategy, si, cfg, log, data, **_kwargs):
            node_calls.append((name, si.name(), data))
            self.backtest_report = {"summary": {"total_return_rate": 4.2}}
            self.backtest_report_path = None

        def start(self):
            return SimpleNamespace(total_return_rate=4.2, to_dict=lambda: {"total_return_rate": 4.2})

    cfg = SimpleNamespace(cash=5000.0, commission=0.001, warmup_candles=0, db=None, plot=False)
    runner = BacktestTaskRunner(
        cfg=cfg,
        log=_DummyLog(),
        task_repository=task_repo,
        dataset_file_store=CsvDatasetFileStore(),
        path_resolver=lambda p: str(p),
        strategy_parser=lambda names: list(names),
        node_factory=_FakeNode,
    )
    tcfg = TaskConfig(
        id=88,
        ttype=TaskType.BACK_TRADER,
        symbol_interval=SymbolInterval("BTC-USDT", Interval.INTERVAL_1h),
        csv=str(csv_path),
        strategies=["macd_triple_divergence"],
    )

    outcome = await runner.run(tcfg)

    assert len(node_calls) == 1
    assert outcome.trader_result.total_return_rate == 4.2
    assert (await task_repo.get_task(88)).state == TaskStateType.DONE


def test_backtest_runner_has_no_getattr_repository_probing_or_database_manager_import():
    path = Path(__file__).resolve().parents[1] / "src" / "trader" / "adapters" / "outbound" / "backtrader" / "backtest_runner.py"
    source = path.read_text(encoding="utf-8")
    assert "DatabaseManager" not in source
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "getattr":
            args_src = ast.unparse(node)
            assert "db_manager" not in args_src
            assert "repository" not in args_src.lower()
