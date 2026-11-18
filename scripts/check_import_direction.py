#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path

FRAMEWORK_MODULES = frozenset({"fastapi", "tortoise", "backtrader", "ccxt"})


def _module_parts(path: Path, core_root: Path) -> tuple[list[str], bool]:
    parts = list(path.relative_to(core_root).with_suffix("").parts)
    is_package = parts[-1] == "__init__"
    if is_package:
        parts = parts[:-1]
    return ["trader", "core", *parts], is_package


def _resolve_relative(module_parts: list[str], is_package: bool, level: int, module: str | None) -> str:
    package = module_parts if is_package else module_parts[:-1]
    package = package[: len(package) - (level - 1)]
    return ".".join([*package, module]) if module else ".".join(package)


def _imported_modules(node: ast.AST, module_parts: list[str], is_package: bool) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if not isinstance(node, ast.ImportFrom):
        return []

    if node.level:
        base = _resolve_relative(module_parts, is_package, node.level, node.module)
        return [f"{base}.{alias.name}" for alias in node.names] if base else []

    base = node.module or ""
    return [base, *(f"{base}.{alias.name}" for alias in node.names)]


def _is_forbidden(module: str) -> bool:
    if module == "trader.adapters" or module.startswith("trader.adapters."):
        return True
    top_level = module.split(".", 1)[0]
    return top_level in FRAMEWORK_MODULES or top_level.startswith("binance")


def check_import_direction(core_root: Path) -> list[str]:
    """Return violations for imports that point from core to adapters or frameworks."""
    violations: list[str] = []

    for path in sorted(core_root.rglob("*.py")):
        module_parts, is_package = _module_parts(path, core_root)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for module in _imported_modules(node, module_parts, is_package):
                if _is_forbidden(module):
                    violations.append(f"{path}:{node.lineno}: core must not import {module}")

    return violations
