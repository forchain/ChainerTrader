"""Strategy discovery for the Backtrader adapter package."""

from __future__ import annotations

import importlib
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


def capitalize_first(s: str) -> str:
    return s[:1].upper() + s[1:]


def dynamic_load_create(module_name, class_name, *args, **kwargs):
    try:
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name)
        return cls(*args, **kwargs)
    except (ModuleNotFoundError, AttributeError) as e:
        print(f"Error: {e}")
        return None


def dynamic_load(module_name, class_name):
    try:
        module = importlib.import_module(module_name)
        cls = getattr(module, class_name)
        return cls
    except (ModuleNotFoundError, AttributeError) as e:
        print(f"Error: {e}")
        return None


def parse_strategy(stype):
    # 如果 stype 包含., 则.之前的部分为模块，.之后的部分为类名
    groups = stype.split(".")
    if len(groups) > 1:
        module_name = f"trader.adapters.outbound.backtrader.{groups[0]}"
        class_name = get_strategy_class_name(groups[1])
        return dynamic_load(module_name, class_name)

    folder_path = _PACKAGE_DIR / stype

    if folder_path.is_dir():
        mod = f"trader.adapters.outbound.backtrader.{stype}.{stype}"
    else:
        mod = f"trader.adapters.outbound.backtrader.{stype}"

    return dynamic_load(mod, get_strategy_class_name(stype))


def parse_strategies(stypes: [str]):
    ret = []
    for st in stypes:
        cl = parse_strategy(st)
        if cl is None:
            continue
        ret.append(cl)
    if len(ret) <= 0:
        return None
    return ret


def get_strategy_class_name(file_name: str) -> str:
    parts = file_name.split("_")
    class_name = "".join(capitalize_first(word) for word in parts if word)
    if class_name:
        class_name = class_name[0].upper() + class_name[1:]
    return class_name + "Strategy"


class BacktraderStrategyCatalog:
    """Backtrader strategy adapter implementing StrategyLoader and StrategyCatalog."""

    def load(self, strategy_names: list[str]) -> list | None:
        return parse_strategies(list(strategy_names))

    def load_one(self, strategy_name: str):
        return parse_strategy(strategy_name)

    def list_options(self) -> list[str]:
        return list_strategy_options()

    def param_defaults(self, strategy_name: str) -> dict:
        return strategy_param_defaults(strategy_name)
