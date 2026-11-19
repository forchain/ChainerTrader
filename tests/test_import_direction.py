from pathlib import Path

import pytest

from scripts.check_import_direction import (
    LEGACY_SHIM_ADAPTER_ALLOWLIST,
    check_composition_boundary,
    check_import_direction,
    check_transitive_core_imports,
)

ROOT = Path(__file__).resolve().parents[1]
TRADER_ROOT = ROOT / "src" / "trader"
CORE_ROOT = TRADER_ROOT / "core"


def _write_core_module(tmp_path: Path, source: str) -> Path:
    core_root = tmp_path / "core"
    module = core_root / "task" / "module.py"
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text(source + "\n", encoding="utf-8")
    return core_root


def test_current_core_tree_passes_import_direction_guardrail():
    assert check_import_direction(CORE_ROOT) == []


def test_current_trader_tree_passes_composition_boundary_guardrail():
    assert check_composition_boundary(TRADER_ROOT) == []


def test_legacy_shim_allowlist_is_empty():
    assert LEGACY_SHIM_ADAPTER_ALLOWLIST == frozenset()


def test_current_trader_tree_passes_transitive_core_guardrail():
    assert check_transitive_core_imports(TRADER_ROOT) == []


def _write_module(root: Path, relative: str, source: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source + "\n", encoding="utf-8")


def test_transitive_guardrail_detects_core_path_to_adapters(tmp_path: Path):
    trader_root = tmp_path / "trader"
    _write_module(trader_root, "core/task/mod.py", "from trader.core.shared.helper import value")
    _write_module(trader_root, "core/shared/helper.py", "from trader.adapters.outbound.store import thing")
    _write_module(trader_root, "adapters/outbound/store.py", "thing = 1")

    violations = check_transitive_core_imports(trader_root)

    assert violations
    assert "trader.core.shared.helper" in violations[0]
    assert "trader.adapters.outbound" in violations[0]


def test_transitive_guardrail_detects_core_path_to_framework(tmp_path: Path):
    trader_root = tmp_path / "trader"
    _write_module(trader_root, "core/task/mod.py", "from trader.core.shared.helper import value")
    _write_module(trader_root, "core/shared/helper.py", "import aiohttp")

    assert check_transitive_core_imports(trader_root)


def test_guardrail_fails_when_forbidden_import_is_added_to_core_tree(tmp_path: Path):
    core_root = _write_core_module(tmp_path, "from trader.core.shared import Symbol")
    assert check_import_direction(core_root) == []

    _write_core_module(tmp_path, "from trader.core.shared import Symbol\nimport fastapi")

    violations = check_import_direction(core_root)

    assert violations
    assert "fastapi" in violations[0]


@pytest.mark.parametrize(
    "source",
    [
        "import fastapi",
        "from tortoise import fields",
        "import backtrader as bt",
        "from ccxt.binance import Exchange",
        "from binance_sdk_spot import Spot",
        "import trader.adapters.persistence.repository",
        "from trader.adapters.inbound.http import routes",
        "from trader import adapters",
        "from ...adapters import outbound",
    ],
)
def test_guardrail_detects_forbidden_imports_from_core(tmp_path: Path, source: str):
    core_root = _write_core_module(tmp_path, source)

    assert check_import_direction(core_root)


@pytest.mark.parametrize(
    "source",
    [
        "import asyncio",
        "from trader.core.shared import Symbol",
        "from trader.core.task.domain import Task",
        "from .domain import Task",
        "from ..shared import Symbol",
        "from ...core import shared",
    ],
)
def test_guardrail_allows_core_internal_imports(tmp_path: Path, source: str):
    core_root = _write_core_module(tmp_path, source)

    assert check_import_direction(core_root) == []


def test_composition_boundary_rejects_adapter_imports_outside_main_and_allows_main(tmp_path: Path):
    trader_root = tmp_path / "trader"
    (trader_root / "main.py").parent.mkdir(parents=True, exist_ok=True)
    (trader_root / "main.py").write_text(
        "from trader.adapters.outbound.binance.exchange import BinanceExchange\n",
        encoding="utf-8",
    )
    (trader_root / "app").mkdir(parents=True, exist_ok=True)
    (trader_root / "app" / "app.py").write_text(
        "from trader.adapters.outbound.binance.exchange import BinanceExchange\n",
        encoding="utf-8",
    )
    (trader_root / "adapters" / "inbound" / "http").mkdir(parents=True, exist_ok=True)
    (trader_root / "adapters" / "inbound" / "http" / "bad.py").write_text(
        "from trader.adapters.outbound.persistence.manager import DatabaseManager\n",
        encoding="utf-8",
    )

    violations = check_composition_boundary(trader_root, legacy_allowlist=frozenset())
    assert violations
    assert any("app/app.py" in item for item in violations)
    assert any("adapters/inbound/http/bad.py" in item for item in violations)
    assert not any(item.startswith(str(trader_root / "main.py")) for item in violations)
