import json
from pathlib import Path

from trader.tools.optimization_status import build_status


def test_check_optimization_status_treats_terminal_status_as_not_running(tmp_path: Path):
    run_id = "run-terminal-1"
    run_dir = tmp_path / "tmp" / "optimization_runs" / run_id
    run_dir.mkdir(parents=True)
    log_path = run_dir / "runner.log"
    log_path.write_text("line 1\nline 2\n", encoding="utf-8")
    (run_dir / "meta.json").write_text(
        json.dumps({"run_id": run_id, "pid": 999999, "log_path": str(log_path)}),
        encoding="utf-8",
    )
    (run_dir / "status.json").write_text(
        json.dumps({"run_id": run_id, "stage": "finished", "health": "healthy"}),
        encoding="utf-8",
    )

    payload, exit_code = build_status(tmp_path, run_id, tail=1)

    assert exit_code == 0
    assert payload["run_id"] == run_id
    assert payload["status"] == "finished"
    assert payload["process_running"] is False
    assert payload["runtime_status"]["stage"] == "finished"
    assert payload["log_tail"] == ["line 2"]
