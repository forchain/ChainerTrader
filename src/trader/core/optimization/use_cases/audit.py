from __future__ import annotations

from typing import Any

from trader.core.optimization.audit import evaluate_audit_blockers
from trader.core.optimization.exceptions import RankingError
from trader.core.optimization.interfaces import RankingReportStore


class RunOptimizationAuditUseCase:
    """Recompute optimization artifacts, audit blocking rules, and persist agent review summary."""

    def __init__(self, report_store: RankingReportStore):
        self.report_store = report_store

    def execute(self, run_id: str, *, block_on_failure: bool = True) -> dict[str, Any]:
        sample_reports = self.report_store.load_sample_reports(run_id)
        failures = self.report_store.load_failures(run_id)
        artifacts = self.report_store.write_artifacts(run_id, sample_reports, failures)

        audit = artifacts["audit"]
        clusters = artifacts["clusters"]
        local_best = artifacts["local_best"]
        shortlist = artifacts["shortlist"]

        blocker_codes = evaluate_audit_blockers(audit, clusters)
        status = "blocked" if blocker_codes else "passed"
        summary = {
            "run_id": run_id,
            "status": status,
            "run_health": audit.get("run_health", "unknown"),
            "blocker_codes": blocker_codes,
            "unclassified_exit_rate": audit.get("unclassified_exit_rate", 0.0),
            "parameter_statuses": {
                item["parameter"]: item["status"] for item in audit.get("parameter_effectiveness", [])
            },
            "cluster_count": len(clusters.get("items", [])),
            "local_best_groups": len(local_best.get("items", [])),
            "shortlist_count": len(shortlist.get("items", [])),
        }
        summary_path = self.report_store.write_agent_review_summary(run_id, summary)

        result = {
            "run_dir": getattr(self.report_store, "run_dir_str", lambda rid: f"reports/optimizations/{rid}")(run_id),
            "status": status,
            "blocker_codes": blocker_codes,
            "agent_review_summary_path": summary_path,
        }
        if blocker_codes and block_on_failure:
            raise RankingError(f"optimization audit blocked: {', '.join(blocker_codes)}")
        return result
