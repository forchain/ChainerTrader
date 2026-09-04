from __future__ import annotations

import json
from pathlib import Path

from trader.tools.optimization_background import launch_background_run


class DummyProcess:
    def __init__(self, pid: int = 4242):
        self.pid = pid


def test_launch_background_run_creates_run_artifacts(tmp_path: Path):
    tasks_path = tmp_path / "tasks.json"
    tasks_path.write_text(
        json.dumps(
            [
                {
                    "task_type": "BACK_TRADER",
                    "symbol": "BTC-USDT",
                    "interval": "1h",
                    "strategy": "macd_triple_divergence",
                    "param_grid": {"fast_period": [5]},
                }
            ]
        ),
        encoding="utf-8",
    )

    popen_calls = {}

    def fake_popen(command, cwd, stdout, stderr, env):
        popen_calls["command"] = command
        popen_calls["cwd"] = cwd
        popen_calls["stderr"] = stderr
        popen_calls["env"] = env
        stdout.write("runner booted\n")
        stdout.flush()
        return DummyProcess()

    payload, exit_code = launch_background_run(tmp_path, tasks_path, stat=321, popen=fake_popen)

    assert exit_code == 0
    assert payload["pid"] == 4242
    assert payload["run_id"] != "adhoc-run"
    assert popen_calls["command"][-2:] == ["--stat", "321"]
    assert Path(payload["log_path"]).exists()
    assert Path(payload["meta_path"]).exists()


def test_launch_background_run_returns_error_when_no_tasks_expand(tmp_path: Path):
    tasks_path = tmp_path / "tasks.json"
    tasks_path.write_text("[]", encoding="utf-8")

    payload, exit_code = launch_background_run(tmp_path, tasks_path, stat=100)

    assert exit_code == 1
    assert payload["status"] == "no_tasks"
