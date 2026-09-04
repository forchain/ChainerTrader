from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values

PROFILE_REQUIREMENTS = {
    "base": [],
    "db-backtest": ["TRADER_DB", "TRADER_EXCHANGE"],
    "optimization": ["TRADER_DB", "TRADER_EXCHANGE"],
}


def validate_runtime_context(env_file: Path, profile: str = "base", require_env: list[str] | None = None) -> tuple[dict, int]:
    if not env_file.exists():
        return {
            "status": "missing_env_file",
            "env_file": str(env_file),
            "profile": profile,
            "required": [],
            "missing": [],
        }, 1

    values = dotenv_values(env_file)
    required = list(PROFILE_REQUIREMENTS[profile])
    for key in require_env or []:
        if key not in required:
            required.append(key)

    missing = []
    for key in required:
        value = values.get(key)
        present = value is not None and str(value).strip() != ""
        if not present:
            missing.append(key)

    payload = {
        "status": "complete" if not missing else "incomplete",
        "env_file": str(env_file.resolve()),
        "profile": profile,
        "required": required,
        "missing": missing,
    }
    return payload, 0 if not missing else 2
