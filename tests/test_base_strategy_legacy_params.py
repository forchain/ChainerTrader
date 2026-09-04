from __future__ import annotations

import backtrader as bt
import pandas as pd
import pytest

from trader.strategy.base_strategy import BaseStrategy
from trader.strategy.node import build_strategy_kwargs
from trader.strategy.strategy import parse_strategy


def _build_feed():
    rows = []
    for idx in range(80):
        swing = ((idx % 12) - 6) * 0.35
        trend = idx * 0.12
        price = 100 + trend + swing
        rows.append(
            {
                "datetime": pd.Timestamp("2024-01-01") + pd.Timedelta(hours=idx),
                "open": price,
                "high": price + 1.2,
                "low": price - 1.1,
                "close": price + (0.2 if idx % 2 == 0 else -0.15),
                "volume": 1000 + idx,
                "openinterest": 0,
            }
        )

    frame = pd.DataFrame(rows).set_index("datetime")
    return bt.feeds.PandasData(dataname=frame)


def test_base_strategy_no_longer_declares_legacy_stoploss_engine_params():
    param_names = {name for name, _ in BaseStrategy.params._getitems()}

    assert "atr" not in param_names
    assert "atrperiod" not in param_names
    assert "atrdist" not in param_names
    assert "stoploss" not in param_names
    assert "takeprofit" not in param_names
    assert "position_percent" not in param_names
    assert "position_price_buffer" not in param_names
    assert "chainer_position_percent" in param_names
    assert "chainer_position_price_buffer" in param_names


def test_build_strategy_kwargs_maps_legacy_position_params_to_prefixed_names():
    kwargs = build_strategy_kwargs(
        cfg=type("Cfg", (), {"mode": None, "period": None})(),
        log=None,
        position=0,
        trader=True,
        strategy_params={
            "position_percent": 75,
            "position_price_buffer": 0.01,
        },
    )

    assert "position_percent" not in kwargs
    assert "position_price_buffer" not in kwargs
    assert kwargs["chainer_position_percent"] == 75
    assert kwargs["chainer_position_price_buffer"] == 0.01


@pytest.mark.parametrize("strategy_name", ["DUALMA", "MACDRSI", "TURTLE"])
def test_legacy_strategy_smoke_run_without_removed_base_params(strategy_name: str):
    strategy_cls = parse_strategy(strategy_name)
    assert strategy_cls is not None

    cerebro = bt.Cerebro(stdstats=False)
    cerebro.addstrategy(strategy_cls)
    cerebro.adddata(_build_feed())
    cerebro.broker.setcash(100000.0)

    result = cerebro.run()

    assert len(result) == 1
