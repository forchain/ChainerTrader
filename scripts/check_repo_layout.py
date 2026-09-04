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


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def check_paths(paths: list[Path]) -> list[str]:
    violations: list[str] = []

    for raw_path in paths:
        path = Path(str(raw_path).replace("\\", "/"))
        if not path.exists():
            continue

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
