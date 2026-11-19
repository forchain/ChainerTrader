"""Strategy discovery for the Backtrader adapter package."""

from __future__ import annotations

import os
from pathlib import Path

_PACKAGE_DIR = Path(__file__).resolve().parent

# Engine, feed, and runner modules that live next to the strategy modules.
_NON_STRATEGY_MODULES = frozenset(
    {
        "__init__.py",
        "backtest_runner.py",
        "backtrader_adapter.py",
        "base_strategy.py",
        "catalog.py",
        "chainer_trader.py",
        "csvdata.py",
        "data.py",
        "dataset_feed.py",
        "execution_gateway.py",
        "feed.py",
        "live_runtime.py",
        "live_trader_runner.py",
        "node.py",
        "optimization_runner.py",
        "smoke_test.py",
        "trilogy_strategy.py",
    }
)


def list_strategy_options() -> list[str]:
    """Return the strategy names available in this package, as used by the task console."""
    options: set[str] = set()
    for name in os.listdir(_PACKAGE_DIR):
        full_path = _PACKAGE_DIR / name
        if full_path.is_file() and name.endswith(".py") and name not in _NON_STRATEGY_MODULES:
            options.add(name[:-3])
            continue
        if full_path.is_dir() and (full_path / f"{name}.py").is_file():
            options.add(name)
    return sorted(options)


def strategy_param_defaults(strategy_name: str) -> dict:
    """Return the default strategy params declared by a Backtrader strategy module."""
    import importlib

    from trader.adapters.outbound.backtrader.base_strategy import BaseStrategy

    try:
        module = importlib.import_module(f"trader.adapters.outbound.backtrader.{strategy_name}")
    except Exception:
        return {}

    candidates = []
    for attr in dir(module):
        obj = getattr(module, attr, None)
        if not isinstance(obj, type):
            continue
        try:
            if not issubclass(obj, BaseStrategy) or obj is BaseStrategy:
                continue
        except Exception:
            continue
        params = getattr(obj, "params", None)
        if params is not None:
            candidates.append((obj.__name__, params))

    if not candidates:
        return {}

    # Prefer the class name matching the module stem (case-insensitive), otherwise the first candidate.
    selected = None
    lowered = strategy_name.lower()
    for class_name, params in candidates:
        if class_name.lower() == lowered:
            selected = params
            break
    if selected is None:
        selected = candidates[0][1]

    defaults = {}
    try:
        for item in selected:
            if not isinstance(item, tuple) or len(item) != 2:
                continue
            key, value = item
            key_text = str(key or "").strip()
            if not key_text:
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                defaults[key_text] = value
    except Exception:
        return {}
    return defaults
