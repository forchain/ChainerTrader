from pathlib import Path

import pytest

from scripts.check_import_direction import check_import_direction

CORE_ROOT = Path(__file__).resolve().parents[1] / "src" / "trader" / "core"


def _write_core_module(tmp_path: Path, source: str) -> Path:
    core_root = tmp_path / "core"
    module = core_root / "task" / "module.py"
    module.parent.mkdir(parents=True, exist_ok=True)
    module.write_text(source + "\n", encoding="utf-8")
    return core_root


def test_current_core_tree_passes_import_direction_guardrail():
    assert check_import_direction(CORE_ROOT) == []


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
