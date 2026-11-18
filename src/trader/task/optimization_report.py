from __future__ import annotations

from pathlib import Path

from trader.adapters.outbound.files.optimization_html import build_rankings_html as _build_rankings_html
from trader.adapters.outbound.files.optimization_store import FileRankingReportStore
from trader.core.optimization.domain import (
    REPORT_VERSION,
    SCORE_VERSION,
    build_optimization_artifacts,
    normalize_report_params,
)
from trader.core.optimization.domain import (
    classify_failure_counts as _classify_failure_counts,
)
from trader.core.optimization.domain import (
    display_param_name as _display_param_name,
)


def write_optimization_artifacts(base_dir: str | Path, optimization_run_id: str, sample_reports: list[dict], failures: list[dict]) -> Path:
    store = FileRankingReportStore(base_dir)
    store.write_artifacts(optimization_run_id, sample_reports, failures)
    return store.run_dir(optimization_run_id)


__all__ = [
    "REPORT_VERSION",
    "SCORE_VERSION",
    "_build_rankings_html",
    "_classify_failure_counts",
    "_display_param_name",
    "build_optimization_artifacts",
    "normalize_report_params",
    "write_optimization_artifacts",
]
