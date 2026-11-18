from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests.persistence_harness import InMemoryTaskRepository
from trader.core.shared.domain import Interval, Kline, SymbolInterval, add_time_duration
from trader.core.task import TaskConfig, TaskRunner, TaskStateType, TaskType
from trader.core.task.use_cases import (
    CheckKlinesNumTaskRunner,
    CheckKlinesTaskRunner,
    ImportCsvTaskRunner,
    UpdateKlinesTaskRunner,
)


@pytest.fixture
def anyio_backend():
    return "asyncio"


class _DummyLog:
    def __init__(self):
        self.messages: list[str] = []

    def info(self, msg, *_args, **_kwargs):
        self.messages.append(str(msg))

    def warning(self, msg, *_args, **_kwargs):
        self.messages.append(str(msg))

    def error(self, msg, *_args, **_kwargs):
        self.messages.append(str(msg))

    def debug(self, msg, *_args, **_kwargs):
        pass


class _FakeKlineRepo:
    def __init__(self, initial: list[Kline] | None = None):
        self.klines: dict[int, Kline] = {k.open_time: k for k in (initial or [])}
        self.deleted_ranges: list[tuple[str, int, int]] = []

    async def get_latest_kline(self, _name: str) -> Kline | None:
        if not self.klines:
            return None
        return self.klines[max(self.klines)]

    async def get_first_kline(self, _name: str) -> Kline | None:
        if not self.klines:
            return None
        return self.klines[min(self.klines)]

    async def get_kline(self, _name: str, open_time: int) -> Kline | None:
        return self.klines.get(open_time)

    async def get_klines(self, _name: str, start_time: int = 0, end_time: int = 0) -> list[Kline]:
        return [self.klines[t] for t in sorted(self.klines) if (not start_time or t >= start_time) and (not end_time or t <= end_time)]

    async def add_klines(self, _name: str, klines: list[Kline], **_kwargs) -> int:
        for k in klines:
            self.klines[k.open_time] = k
        return len(klines)

    async def delete_klines_in_range(self, name: str, start_time: int, end_time: int) -> int:
        self.deleted_ranges.append((name, start_time, end_time))
        removed = [t for t in self.klines if start_time <= t <= end_time]
        for t in removed:
            del self.klines[t]
        return len(removed)


class _FakeMarketDataClient:
    def __init__(self, klines_by_range: list[Kline]):
        self.klines_by_range = list(klines_by_range)
        self.calls: list[tuple[str, int | None, int | None, int]] = []

    def name(self) -> str:
        return "BINANCE"

    def get_klines(self, symbol_interval: SymbolInterval, start_time=None, end_time=None, limit: int = 500):
        self.calls.append((symbol_interval.name(), start_time, end_time, limit))
        return [
            k
            for k in self.klines_by_range
            if (start_time is None or k.open_time >= start_time) and (end_time is None or k.open_time <= end_time)
        ]


class _FakeFileStore:
    def __init__(self, rows: list[list[str]]):
        self.rows = rows
        self.read_paths: list[Path] = []

    def write_klines(self, path: Path, klines: list[Kline]) -> None:
        raise NotImplementedError

    def count_klines(self, path: Path) -> int:
        return len(self.rows)

    def read_rows(self, path: Path) -> list[list[str]]:
        self.read_paths.append(path)
        return self.rows


def _kline(open_time: int) -> Kline:
    return Kline(open_time, 100.0, 101.0, 99.0, 100.5, open_time + 3599, 10.0, 1000.0, 5, 5.0, 500.0, 0.0)


@pytest.mark.anyio
async def test_update_klines_runner_preserves_relative_limit_and_force_update():
    si = SymbolInterval("BTC-USDT", Interval.INTERVAL_1h)
    end_time = 1_700_007_200
    t0 = add_time_duration(end_time, si.interval, -2)
    t1 = add_time_duration(end_time, si.interval, -1)
    klines = [_kline(t0), _kline(t1), _kline(end_time)]

    task_repo = InMemoryTaskRepository()
    kline_repo = _FakeKlineRepo([_kline(t0)])
    client = _FakeMarketDataClient(klines)

    runner = UpdateKlinesTaskRunner(
        kline_repository=kline_repo,
        market_data_client=client,
        task_repository=task_repo,
        log=_DummyLog(),
    )
    assert isinstance(runner, TaskRunner)

    tcfg = TaskConfig(
        101,
        TaskType.UPDATE_KLINES,
        si,
        end_time=end_time,
        limit=2,
        force_update=True,
    )
    ts = await runner.run(tcfg, quit_event=asyncio.Event())

    assert kline_repo.deleted_ranges == [("BTCUSDT-1h", t0, end_time)]
    assert client.calls == [("BTCUSDT-1h", t0, end_time, 3)]
    assert sorted(kline_repo.klines) == [t0, t1, end_time]
    assert ts.state == TaskStateType.DONE
    assert (await task_repo.get_task(101)).state == TaskStateType.DONE


@pytest.mark.anyio
async def test_check_klines_and_check_num_runners_execute_through_ports():
    si = SymbolInterval("BTC-USDT", Interval.INTERVAL_1h)
    base = 1_700_000_000
    klines = [_kline(base), _kline(base + 3600), _kline(base + 7200), _kline(base + 10800)]
    kline_repo = _FakeKlineRepo(klines)
    task_repo = InMemoryTaskRepository()
    log = _DummyLog()

    check_runner = CheckKlinesTaskRunner(kline_repository=kline_repo, task_repository=task_repo, log=log)
    num_runner = CheckKlinesNumTaskRunner(kline_repository=kline_repo, task_repository=task_repo, log=log)
    assert isinstance(check_runner, TaskRunner)
    assert isinstance(num_runner, TaskRunner)

    ts1 = await check_runner.run(TaskConfig(102, TaskType.CHECK_KLINES, si), quit_event=asyncio.Event())
    ts2 = await num_runner.run(TaskConfig(103, TaskType.CHECK_KLINES_NUM, si, limit=2), quit_event=asyncio.Event())

    assert ts1.state == TaskStateType.DONE
    assert ts2.state == TaskStateType.DONE
    assert any("process result:0/3" in msg for msg in log.messages)
    assert any("is completed. Process:2/2" in msg for msg in log.messages)


@pytest.mark.anyio
async def test_import_csv_runner_resolves_relative_csv_path_and_imports_klines(tmp_path: Path):
    si = SymbolInterval("BTC-USDT", Interval.INTERVAL_1h)
    rows = [
        ["open_time", "open", "high", "low", "close", "volume", "close_time", "quote_vol", "count", "tb_vol", "tb_qvol", "ignore"],
        ["1700000000000", "100", "101", "99", "100.5", "10", "1700003599000", "1000", "5", "5", "500", "0"],
        ["1700003600000", "100.5", "102", "100", "101.5", "12", "1700007199000", "1200", "6", "6", "600", "0"],
    ]
    file_store = _FakeFileStore(rows)
    kline_repo = _FakeKlineRepo()
    task_repo = InMemoryTaskRepository()

    runner = ImportCsvTaskRunner(
        kline_repository=kline_repo,
        file_store=file_store,
        task_repository=task_repo,
        data_dir=tmp_path,
        log=_DummyLog(),
    )
    assert isinstance(runner, TaskRunner)

    ts = await runner.run(TaskConfig(104, TaskType.IMPORT_CSV, si, csv="nested/sample.csv"))

    assert file_store.read_paths == [tmp_path / "nested/sample.csv"]
    assert sorted(kline_repo.klines) == [1_700_000_000, 1_700_003_600]
    assert ts.state == TaskStateType.DONE
    assert (await task_repo.get_task(104)).state == TaskStateType.DONE


def test_data_task_runners_have_no_direct_db_or_exchange_imports():
    path = Path(__file__).resolve().parents[1] / "src" / "trader" / "core" / "task" / "use_cases" / "data_tasks.py"
    source = path.read_text(encoding="utf-8")
    assert "DatabaseManager" not in source
    assert "BinanceExchange" not in source
