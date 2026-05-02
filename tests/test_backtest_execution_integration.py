import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from trader.common.config import Config
from trader.exchange.binance.csvdata import BinanceCSVData
from trader.exchange.binance.data import BinanceData
from trader.strategy.node import build_strategy_kwargs
from trader.task.backtrader_task import BackTraderTask
from trader.task.task_config import TaskConfig
from trader.task.task_manager import TaskManager
from trader.task.task_type import TaskType
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


def _write_dataset_csv(csv_path: Path):
    csv_path.write_text(
        "1700000000000,100,101,99,100.5,10,1700003599000,20,3,4,5,0\n",
        encoding="utf-8",
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


def test_build_strategy_kwargs_allows_parameter_overrides():
    kwargs = build_strategy_kwargs(
        Config(period=14),
        DummyLog(),
        position=0,
        trader=False,
        strategy_params={"period": 55, "fast_period": 8},
    )

    assert kwargs["period"] == 55
    assert kwargs["fast_period"] == 8
    assert "atr" not in kwargs
    assert "stoploss" not in kwargs


def test_backtrader_task_start_uses_dataset_resolver_for_db_backtests(monkeypatch):
    async def _test():
        prepare_calls = []

        class FakeResolver:
            def __init__(self, *args, **kwargs):
                pass

            async def prepare(
                self,
                symbol_interval,
                start_time,
                end_time,
                allow_download=True,
                max_download_ranges=None,
                allow_incomplete_coverage=False,
            ):
                prepare_calls.append((symbol_interval.name(), start_time, end_time, allow_download))
                return SimpleNamespace(
                    ok=True,
                    dataset_ref=SimpleNamespace(
                        dataset_key="BTCUSDT-1h|1700000000|1700003600",
                        source_type="db",
                        symbol="BTCUSDT",
                        interval="1h",
                        start_time=1_700_000_000,
                        end_time=1_700_000_000 + 3600,
                        path=None,
                    ),
                )

        monkeypatch.setattr("trader.task.backtrader_task.DatasetResolver", FakeResolver)
        monkeypatch.setattr("trader.task.backtrader_task.parse_strategies", lambda strategies: ["fake-strategy"])

        tcfg = TaskConfig(
            id=1,
            ttype=TaskType.BACK_TRADER,
            symbol_interval=SymbolInterval("BTC-USDT", Interval.INTERVAL_1h),
            start_time=1_700_000_000,
            end_time=1_700_000_000 + 3600,
            strategies=["macd_triple_divergence"],
            auto_download=True,
        )
        get_klines = AsyncMock(return_value=[_kline(1_700_000_000), _kline(1_700_000_000 + 3600)])
        db_manager = SimpleNamespace(kline=SimpleNamespace(get_klines=get_klines))
        task = BackTraderTask(tcfg, Config(), DummyLog(), db_manager=db_manager, exchange=SimpleNamespace())

        result = await task.start(None)

        assert prepare_calls == [("BTCUSDT-1h", 1_700_000_000, 1_700_000_000 + 3600, True)]
        assert result[0] == ["fake-strategy"]
        assert isinstance(result[1], BinanceData)
        get_klines.assert_awaited_once_with("BTCUSDT-1h", 1_700_000_000, 1_700_000_000 + 3600)

    asyncio.run(_test())


def test_task_manager_prepares_shared_dataset_once_for_same_dataset_key(monkeypatch, tmp_path: Path):
    async def _test():
        dataset_path = tmp_path / "prepared.csv"
        _write_dataset_csv(dataset_path)
        prepare_calls = []

        class FakeResolver:
            def __init__(self, *args, **kwargs):
                pass

            async def prepare(
                self,
                symbol_interval,
                start_time,
                end_time,
                allow_download=True,
                max_download_ranges=None,
                allow_incomplete_coverage=False,
            ):
                prepare_calls.append((symbol_interval.name(), start_time, end_time, allow_download))
                return SimpleNamespace(
                    ok=True,
                    dataset_ref=SimpleNamespace(
                        dataset_key="BTCUSDT-1h|1700000000|1700003600",
                        source_type="db",
                        symbol="BTCUSDT",
                        interval="1h",
                        start_time=1_700_000_000,
                        end_time=1_700_000_000 + 3600,
                        path=None,
                    ),
                )

        monkeypatch.setattr("trader.task.task_manager.DatasetResolver", FakeResolver)

        cfg = Config()
        task_manager = TaskManager(cfg, DummyLog(), db_manager=SimpleNamespace(kline=SimpleNamespace()), exchange=SimpleNamespace())
        shared_si = SymbolInterval("BTC-USDT", Interval.INTERVAL_1h)
        tasks = [
            TaskConfig(
                id=1,
                ttype=TaskType.BACK_TRADER,
                symbol_interval=shared_si,
                start_time=1_700_000_000,
                end_time=1_700_000_000 + 3600,
                strategies=["macd_triple_divergence"],
                strategy_params={"fast_period": 5},
                param_id="a",
                optimization_run_id="run-1",
                auto_download=True,
            ),
            TaskConfig(
                id=2,
                ttype=TaskType.BACK_TRADER,
                symbol_interval=shared_si,
                start_time=1_700_000_000,
                end_time=1_700_000_000 + 3600,
                strategies=["macd_triple_divergence"],
                strategy_params={"fast_period": 8},
                param_id="b",
                optimization_run_id="run-1",
                auto_download=True,
            ),
        ]

        failures = await task_manager._prepare_backtest_datasets(tasks)

        assert failures == []
        assert prepare_calls == [("BTCUSDT-1h", 1_700_000_000, 1_700_000_000 + 3600, True)]
        assert tasks[0].dataset_ref.dataset_key == "BTCUSDT-1h|1700000000|1700003600"
        assert tasks[1].dataset_ref.dataset_key == "BTCUSDT-1h|1700000000|1700003600"
        assert tasks[0].dataset_ref.path is None
        assert tasks[1].dataset_ref.path is None

    asyncio.run(_test())
