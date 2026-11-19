"""Pure strategy-node configuration normalisation."""

from __future__ import annotations

from typing import Any


def build_strategy_kwargs(
    cfg: Any,
    log: Any,
    position: float,
    trader: bool,
    strategy_params: dict | None = None,
) -> dict:
    kwargs = {
        "mode": cfg.mode,
        "period": cfg.period,
        "log": log,
        "position": position,
        "trader": trader,
    }
    if strategy_params:
        normalized = dict(strategy_params)
        if "position_percent" in normalized and "chainer_position_percent" not in normalized:
            normalized["chainer_position_percent"] = normalized.pop("position_percent")
        if "position_price_buffer" in normalized and "chainer_position_price_buffer" not in normalized:
            normalized["chainer_position_price_buffer"] = normalized.pop("position_price_buffer")
        kwargs.update(normalized)
    return kwargs
