import ast
from pathlib import Path

TRADER_ROOT = Path(__file__).resolve().parents[1] / "src" / "trader"
BACKTRADER_ADAPTER_ROOT = TRADER_ROOT / "adapters" / "outbound" / "backtrader"


def _imports_backtrader(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "backtrader" or alias.name.startswith("backtrader."):
                    return True
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "backtrader" or node.module.startswith("backtrader."):
                return True
    return False


def test_backtrader_is_imported_only_inside_backtrader_adapter():
    leaking = []
    for path in sorted(TRADER_ROOT.rglob("*.py")):
        try:
            path.relative_to(BACKTRADER_ADAPTER_ROOT)
            continue
        except ValueError:
            pass
        if _imports_backtrader(path):
            leaking.append(path.relative_to(TRADER_ROOT).as_posix())

    assert leaking == []
