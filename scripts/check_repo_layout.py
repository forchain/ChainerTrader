#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

ALLOWED_JSON_ROOTS = (
    Path("configs/tasks"),
    Path("configs/notices"),
    Path("tests/fixtures"),
    Path(".claude"),
)

CORE_ROOT = Path("src/trader/core")
CORE_PACKAGES = frozenset(
    {
        "shared",
        "task",
        "execution",
        "marketdata",
        "exchange",
        "identity",
        "notification",
        "strategy",
        "optimization",
    }
)

ADAPTERS_ROOT = Path("src/trader/adapters")
ADAPTER_PACKAGES = {
    "inbound": frozenset({"http", "cli"}),
    "outbound": frozenset({"persistence", "binance", "backtrader", "marketstream", "email", "files"}),
}


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _check_hexagonal_placement(path: Path) -> str | None:
    if path.suffix != ".py":
        return None

    if _is_under(path, CORE_ROOT):
        parts = path.relative_to(CORE_ROOT).parts
        if parts == ("__init__.py",):
            return None
        if parts[0] not in CORE_PACKAGES:
            allowed = ", ".join(sorted(CORE_PACKAGES))
            return f"{path}: core modules must live under a bounded-context package: {allowed}"
        return None

    if _is_under(path, ADAPTERS_ROOT):
        parts = path.relative_to(ADAPTERS_ROOT).parts
        if parts == ("__init__.py",):
            return None
        if parts[0] not in ADAPTER_PACKAGES:
            return f"{path}: adapters must live under inbound/ or outbound/"
        if len(parts) > 1 and parts[1] != "__init__.py" and parts[1] not in ADAPTER_PACKAGES[parts[0]]:
            allowed = ", ".join(sorted(ADAPTER_PACKAGES[parts[0]]))
            return f"{path}: adapter packages must be one of: {allowed}"

    return None


def check_paths(paths: list[Path]) -> list[str]:
    violations: list[str] = []

    for raw_path in paths:
        path = Path(str(raw_path).replace("\\", "/"))
        if not path.exists():
            continue

        placement_violation = _check_hexagonal_placement(path)
        if placement_violation:
            violations.append(placement_violation)

        if path.suffix == ".json" and _is_under(path, Path("scripts")):
            violations.append(f"{path}: JSON configuration assets must not live under scripts/")
            continue

        if path.suffix == ".json" and not any(_is_under(path, root) for root in ALLOWED_JSON_ROOTS):
            violations.append(f"{path}: JSON assets must live under configs/ or approved fixture directories")
            continue

        if _is_under(path, Path("tests/output")):
            violations.append(f"{path}: generated artifacts must not be committed under tests/output/")

    return violations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate repository layout guardrails")
    parser.add_argument("paths", nargs="*", help="Paths to validate")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    paths = [Path(item) for item in args.paths]
    violations = check_paths(paths)

    if violations:
        for violation in violations:
            print(violation)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
