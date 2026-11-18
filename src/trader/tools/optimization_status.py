from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from trader.adapters.outbound.files.optimization_store import FileTaskConfigFileStore
from trader.core.optimization.domain import TERMINAL_STAGES
from trader.core.optimization.use_cases.workbench import OptimizationBackgroundStatusUseCase


def default_process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def build_status(
    repo_root: Path,
    run_id: str,
    tail: int = 20,
    process_exists: Callable[[int], bool] = default_process_exists,
) -> tuple[dict, int]:
    return OptimizationBackgroundStatusUseCase(
        config_store=FileTaskConfigFileStore(),
        base_dir=repo_root,
    ).build_status(run_id, tail=tail, process_exists=process_exists)


__all__ = ["TERMINAL_STAGES", "build_status", "default_process_exists"]
