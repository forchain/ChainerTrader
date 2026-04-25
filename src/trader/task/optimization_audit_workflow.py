from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from trader.task.optimization_report import write_optimization_artifacts


def run_optimization_audit(base_dir: str | Path, run_id: str, *, block_on_failure: bool = True) -> dict[str, Any]:
    run_dir = Path(base_dir) / "reports" / "optimizations" / run_id
    runs_dir = run_dir / "runs"
    sample_reports = _load_sample_reports(runs_dir)
    failures_path = run_dir / "failures.json"
    failures = json.loads(failures_path.read_text(encoding="utf-8")) if failures_path.exists() else []

    write_optimization_artifacts(base_dir, run_id, sample_reports, failures)

    audit = json.loads((run_dir / "audit.json").read_text(encoding="utf-8"))
    clusters = json.loads((run_dir / "clusters.json").read_text(encoding="utf-8"))
    local_best = json.loads((run_dir / "local_best.json").read_text(encoding="utf-8"))
    shortlist = json.loads((run_dir / "shortlist.json").read_text(encoding="utf-8"))

    blocker_codes = _evaluate_blockers(audit, clusters)
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
    (run_dir / "agent_review_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    result = {
        "run_dir": str(run_dir),
        "status": status,
        "blocker_codes": blocker_codes,
        "agent_review_summary_path": str(run_dir / "agent_review_summary.json"),
    }
    if blocker_codes and block_on_failure:
        raise RuntimeError(f"optimization audit blocked: {', '.join(blocker_codes)}")
    return result


def _load_sample_reports(runs_dir: Path) -> list[dict]:
    if not runs_dir.exists():
        return []
    reports = []
    for path in sorted(runs_dir.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["report_path"] = str(path.resolve())
        reports.append(payload)
    return reports


def _evaluate_blockers(audit: dict, clusters: dict) -> list[str]:
    blockers = []
    if float(audit.get("unclassified_exit_rate", 0.0)) > 0.0:
        blockers.append("unclassified_exit_rate")
    if any(item.get("status") in {"shadowed_or_overridden", "suspicious"} for item in audit.get("parameter_effectiveness", [])):
        blockers.append("shadowed_parameter")
    if any(item.get("cluster_type") == "shadowed_behavior_cluster" for item in clusters.get("items", [])):
        blockers.append("shadowed_behavior_cluster")
    if any(item.get("cluster_type") == "suspicious_same_behavior" for item in clusters.get("items", [])):
        blockers.append("suspicious_duplicate_cluster")
    return blockers
