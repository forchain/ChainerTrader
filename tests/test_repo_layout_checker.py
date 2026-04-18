from pathlib import Path

import pytest

from scripts.check_repo_layout import check_paths


def test_check_repo_layout_accepts_configs_and_wrapper_paths():
    violations = check_paths(
        [
            Path("configs/tasks/backtests/backtest_test.json"),
            Path("configs/notices/notice.json"),
            Path("scripts/ops/setup_worktree.sh"),
            Path("scripts/wrappers/run_top_volume_signal_scanner.py"),
            Path("src/trader/tools/repo_layout.py"),
        ]
    )

    assert violations == []


def test_check_repo_layout_rejects_new_json_under_scripts(tmp_path: Path, monkeypatch):
    path = tmp_path / "scripts" / "new_task.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    violations = check_paths([Path("scripts/new_task.json")])

    assert violations
    assert "scripts/new_task.json" in violations[0]


def test_check_repo_layout_rejects_generated_artifacts_under_tests_output(tmp_path: Path, monkeypatch):
    path = tmp_path / "tests" / "output" / "new-report.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    violations = check_paths([Path("tests/output/new-report.json")])

    assert violations
    assert "tests/output/new-report.json" in violations[0]


def test_check_repo_layout_rejects_task_json_outside_configs(tmp_path: Path, monkeypatch):
    path = tmp_path / "docs" / "examples" / "backtest.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    violations = check_paths([Path("docs/examples/backtest.json")])

    assert violations
    assert "docs/examples/backtest.json" in violations[0]


@pytest.mark.parametrize(
    "path",
    [
        Path("configs/tasks/optimizations/macd_triple_divergence_engine_optimization.json"),
        Path("configs/tasks/downloads/update_klines.json"),
    ],
)
def test_check_repo_layout_allows_task_json_inside_configs(path: Path):
    assert check_paths([path]) == []
