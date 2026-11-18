from pathlib import Path

import pytest

from scripts.check_repo_layout import check_paths


def test_check_repo_layout_accepts_configs_and_wrapper_paths():
    violations = check_paths(
        [
            Path("configs/tasks/backtests/backtest_test.json"),
            Path("configs/notices/notice.sample.json"),
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


def _create_path(tmp_path: Path, monkeypatch, relative: str) -> Path:
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return Path(relative)


@pytest.mark.parametrize(
    "relative",
    [
        "src/trader/core/__init__.py",
        "src/trader/core/shared/__init__.py",
        "src/trader/core/task/domain.py",
        "src/trader/core/task/use_cases/run_task.py",
        "src/trader/adapters/__init__.py",
        "src/trader/adapters/inbound/__init__.py",
        "src/trader/adapters/inbound/http/routes.py",
        "src/trader/adapters/inbound/cli/console.py",
        "src/trader/adapters/outbound/__init__.py",
        "src/trader/adapters/outbound/persistence/repositories.py",
        "src/trader/adapters/outbound/binance/exchange.py",
        "src/trader/adapters/outbound/backtrader/engine.py",
        "src/trader/adapters/outbound/marketstream/hub.py",
        "src/trader/adapters/outbound/notification/execution_gateway.py",
        "src/trader/adapters/outbound/email/sender.py",
        "src/trader/adapters/outbound/files/store.py",
    ],
)
def test_check_repo_layout_allows_hexagonal_package_paths(tmp_path: Path, monkeypatch, relative: str):
    path = _create_path(tmp_path, monkeypatch, relative)

    assert check_paths([path]) == []


@pytest.mark.parametrize(
    "relative",
    [
        "src/trader/core/rogue.py",
        "src/trader/core/unknown/thing.py",
        "src/trader/adapters/rogue.py",
        "src/trader/adapters/middleware/http.py",
        "src/trader/adapters/inbound/rogue.py",
        "src/trader/adapters/inbound/unknown/thing.py",
        "src/trader/adapters/outbound/rogue.py",
        "src/trader/adapters/outbound/unknown/thing.py",
    ],
)
def test_check_repo_layout_rejects_python_outside_hexagonal_packages(tmp_path: Path, monkeypatch, relative: str):
    path = _create_path(tmp_path, monkeypatch, relative)

    violations = check_paths([path])

    assert violations
    assert relative in violations[0]
