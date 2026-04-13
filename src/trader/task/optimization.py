from __future__ import annotations

import hashlib
import itertools
import json
from datetime import datetime, timezone


def has_parameter_search(task_definition: dict) -> bool:
    return bool(task_definition.get("param_grid") or task_definition.get("param_combinations"))


def expand_parameter_space(task_definition: dict) -> list[dict]:
    combinations = task_definition.get("param_combinations")
    if combinations is not None:
        return [dict(item) for item in combinations]

    grid = task_definition.get("param_grid")
    if not grid:
        return [{}]

    keys = list(grid.keys())
    values = [grid[key] for key in keys]
    return [dict(zip(keys, combo)) for combo in itertools.product(*values)]


def make_param_id(params: dict) -> str:
    payload = json.dumps(params, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def make_optimization_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
