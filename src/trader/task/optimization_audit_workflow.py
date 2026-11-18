from __future__ import annotations

from pathlib import Path
from typing import Any

from trader.adapters.outbound.files.optimization_store import FileRankingReportStore
from trader.core.optimization.use_cases.audit import RunOptimizationAuditUseCase


def run_optimization_audit(base_dir: str | Path, run_id: str, *, block_on_failure: bool = True) -> dict[str, Any]:
    return RunOptimizationAuditUseCase(FileRankingReportStore(base_dir)).execute(
        run_id,
        block_on_failure=block_on_failure,
    )
