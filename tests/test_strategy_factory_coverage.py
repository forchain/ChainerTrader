"""Factory coverage for strategy subclasses moved into the backtrader adapter."""

import pytest

from trader.strategy.strategy import parse_strategy

ADAPTER_PREFIX = "trader.adapters.outbound.backtrader"

STRATEGY_NAMES = [
    "Aberration",
    "BOLLMEANREG",
    "chainer_macdrsi",
    "chainer_trader",
    "DeviationMACD",
    "DeviationMACDClaude4",
    "DeviationMACDGemini",
    "DeviationMACDO3",
    "DUALMA",
    "DUALTHRUST",
    "GRID",
    "KDJ",
    "MACDRSI",
    "macd_triple_divergence",
    "RSRS",
    "ShihunMACD",
    "ShihunMACD2",
    "ShihunMACDRISBB",
    "ShihunRSI",
    "ShihunRSI2",
    "smoke_test",
    "TURTLE",
]


@pytest.mark.parametrize("strategy_name", STRATEGY_NAMES)
def test_factory_loads_strategy_from_backtrader_adapter(strategy_name):
    strategy_cls = parse_strategy(strategy_name)

    assert strategy_cls is not None
    assert strategy_cls.__module__.startswith(ADAPTER_PREFIX)


def test_factory_preserves_snake_case_file_to_pascal_case_strategy_name():
    assert parse_strategy("macd_triple_divergence").__name__ == "MacdTripleDivergenceStrategy"
    assert parse_strategy("smoke_test").__name__ == "SmokeTestStrategy"
