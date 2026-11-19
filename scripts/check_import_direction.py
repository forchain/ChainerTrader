#!/usr/bin/env python3
from __future__ import annotations

import ast
from pathlib import Path

FRAMEWORK_MODULES = frozenset({"fastapi", "tortoise", "backtrader", "ccxt", "pydantic", "cryptography", "argon2", "requests"})

# Legacy test-compatibility shims and operational tools that still re-export or
# construct concrete adapters for backwards compatibility with pre-hexagonal callers.
# No new module outside ``src/trader/main.py`` and ``src/trader/adapters/`` may be
# added here; new code must accept ports and wire concrete adapters in ``main.py``.
LEGACY_SHIM_ADAPTER_ALLOWLIST = frozenset(
    {
        "auth/context.py",
        "auth/credentials.py",
        "auth/passwords.py",
        "common/config.py",
        "common/log_buffer.py",
        "common/logger.py",
        "common/path.py",
        "live/market_data.py",
        "live/stream.py",
        "notify/notify_type.py",
        "notify/trade_notification.py",
        "rpc/api/tasks.py",
        "rpc/app.py",
        "rpc/rpc_app.py",
        "task/optimization_audit.py",
        "task/optimization_audit_workflow.py",
        "task/optimization_report.py",
        "task/optimization_runtime.py",
        "task/optimization_workbench.py",
        "task/task_config.py",
        "tools/auto_coin_selection.py",
        "tools/binance_live_smoke.py",
        "tools/db.py",
        "tools/live_signal_reconciliation.py",
        "tools/optimization_status.py",
        "tools/rolling_annual_auto_selection.py",
    }
)


def _module_parts(path: Path, root: Path, prefix: list[str]) -> tuple[list[str], bool]:
    parts = list(path.relative_to(root).with_suffix("").parts)
    is_package = bool(parts and parts[-1] == "__init__")
    if is_package:
        parts = parts[:-1]
    return [*prefix, *parts], is_package


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


def _is_forbidden_in_core(module: str) -> bool:
    if module == "trader.adapters" or module.startswith("trader.adapters."):
        return True
    top_level = module.split(".", 1)[0]
    return top_level in FRAMEWORK_MODULES or top_level.startswith("binance")


def _is_adapter_import(module: str) -> bool:
    return module == "trader.adapters" or module.startswith("trader.adapters.")


def _is_outbound_adapter_import(module: str) -> bool:
    return module == "trader.adapters.outbound" or module.startswith("trader.adapters.outbound.")


def check_import_direction(core_root: Path) -> list[str]:
    """Return violations for imports that point from core to adapters or frameworks."""
    violations: list[str] = []

    for path in sorted(core_root.rglob("*.py")):
        module_parts, is_package = _module_parts(path, core_root, ["trader", "core"])
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            for module in _imported_modules(node, module_parts, is_package):
                if _is_forbidden_in_core(module):
                    violations.append(f"{path}:{node.lineno}: core must not import {module}")

    return violations


def check_composition_boundary(
    trader_root: Path,
    *,
    legacy_allowlist: frozenset[str] = LEGACY_SHIM_ADAPTER_ALLOWLIST,
) -> list[str]:
    """Ensure concrete adapters are wired only in composition root (main.py), not arbitrary non-adapter modules."""
    violations: list[str] = []

    for path in sorted(trader_root.rglob("*.py")):
        rel = path.relative_to(trader_root).as_posix()
        if rel == "main.py":
            continue
        if rel.startswith("adapters/outbound/"):
            continue

        module_parts, is_package = _module_parts(path, trader_root, ["trader"])
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        for node in ast.walk(tree):
            for module in _imported_modules(node, module_parts, is_package):
                if rel.startswith("adapters/inbound/"):
                    if _is_outbound_adapter_import(module):
                        violations.append(f"{path}:{node.lineno}: inbound adapter must not import outbound adapter {module}")
                    continue
                if _is_adapter_import(module):
                    if rel.startswith("adapters/"):
                        continue
                    if rel in legacy_allowlist:
                        continue
                    violations.append(f"{path}:{node.lineno}: only main.py (composition root) may import {module}")

    return violations
