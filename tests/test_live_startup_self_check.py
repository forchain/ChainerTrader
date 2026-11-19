from types import SimpleNamespace

from trader.adapters.outbound.files.task_config_loader import TaskConfig
from trader.core.exchange.domain import MarginMode
from trader.core.shared.domain import Interval, SymbolInterval
from trader.core.task.domain import TaskType
from trader.core.task.use_cases.startup_self_check import evaluate_live_startup_self_check, infer_required_margin_mode


class _FakeStrategyLoader:
    def __init__(self, loaded=True):
        self.loaded = loaded
        self.calls = []

    def load(self, strategy_names):
        self.calls.append(list(strategy_names))
        return [object()] if self.loaded else None

    def load_one(self, strategy_name):
        return object() if self.loaded else None


def _task(mode: str) -> TaskConfig:
    return TaskConfig(
        1,
        TaskType.TRADER,
        SymbolInterval("BTC-USDT", Interval("1h")),
        strategies=["macd_triple_divergence"],
        strategy_params={"chainer_mode": mode},
    )


def test_infer_required_margin_mode_defaults_to_spot_for_long_only():
    assert infer_required_margin_mode([_task("LONG_ONLY")]) == MarginMode.SPOT


def test_infer_required_margin_mode_promotes_short_capable_tasks_to_cross_margin():
    assert infer_required_margin_mode([_task("BOTH"), _task("SHORT_ONLY")]) == MarginMode.CROSS_MARGIN


def test_infer_required_margin_mode_ignores_short_capable_backtests():
    task = TaskConfig(
        1,
        TaskType.BACK_TRADER,
        SymbolInterval("BTC-USDT", Interval("1d")),
        strategies=["macd_triple_divergence"],
        strategy_params={"chainer_mode": "BOTH"},
    )

    assert infer_required_margin_mode([task]) == MarginMode.SPOT


def test_live_startup_self_check_reports_exchange_and_kline_and_short_capability():
    class FakeExchange:
        def __init__(self):
            self.ping_calls = 0
            self.time_calls = 0
            self.latest_klines_calls = 0
            self.margin_mode = MarginMode.CROSS_MARGIN

        def ping(self):
            self.ping_calls += 1
            return True

        def time(self):
            self.time_calls += 1
            return SimpleNamespace()

        def get_latest_klines(self, symbol_interval, limit):
            self.latest_klines_calls += 1
            return [SimpleNamespace(open_time=1), SimpleNamespace(open_time=2)]

    exchange = FakeExchange()
    result = evaluate_live_startup_self_check(
        exchange=exchange,
        tasks=[_task("BOTH")],
        strategy_loader=_FakeStrategyLoader(),
    )

    assert result.passed
    assert result.required_margin_mode == MarginMode.CROSS_MARGIN
    assert result.exchange_connected is True
    assert result.klines_available is True
    assert result.short_capable is True
    assert exchange.ping_calls == 1
    assert exchange.latest_klines_calls == 1


def test_live_startup_self_check_skips_kline_probe_for_backtests():
    class FakeExchange:
        margin_mode = MarginMode.SPOT

        def ping(self):
            return True

        def time(self):
            return SimpleNamespace()

        def get_latest_klines(self, symbol_interval, limit):
            raise AssertionError("backtests should not use live startup kline probes")

    task = TaskConfig(
        1,
        TaskType.BACK_TRADER,
        SymbolInterval("BTC-USDT", Interval("1d")),
        strategies=["macd_triple_divergence"],
        strategy_params={"chainer_mode": "BOTH"},
    )

    result = evaluate_live_startup_self_check(
        exchange=FakeExchange(),
        tasks=[task],
        strategy_loader=_FakeStrategyLoader(),
    )

    assert result.passed
    assert result.kline_checks == []
    assert result.klines_available is True


def test_live_startup_self_check_uses_injected_strategy_loader():
    class FakeExchange:
        margin_mode = MarginMode.SPOT

        def ping(self):
            return True

        def time(self):
            return SimpleNamespace()

        def get_latest_klines(self, symbol_interval, limit):
            return [SimpleNamespace(open_time=1)]

    loader = _FakeStrategyLoader(loaded=False)
    result = evaluate_live_startup_self_check(
        exchange=FakeExchange(),
        tasks=[_task("LONG_ONLY")],
        strategy_loader=loader,
    )

    assert loader.calls == [["macd_triple_divergence"]]
    assert result.passed is False
    assert "strategy_load_failed" in result.details


def test_backtrader_strategy_catalog_loads_real_strategy_classes():
    from trader.adapters.outbound.backtrader.catalog import BacktraderStrategyCatalog

    catalog = BacktraderStrategyCatalog()

    assert [cls.__name__ for cls in catalog.load(["ShihunRSI2"])] == ["ShihunRSI2Strategy"]
    assert catalog.load_one("macd_triple_divergence").__name__ == "MacdTripleDivergenceStrategy"
    assert "ShihunRSI2" in catalog.list_options()
