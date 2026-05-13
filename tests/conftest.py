import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
PROJECT_VENV = REPO_ROOT / ".venv"
# Make src-layout importable during test collection (before any fixtures run).
sys.path.insert(0, str(SRC_DIR))


def pytest_configure(config):
    executable = Path(sys.executable)
    prefix = Path(sys.prefix)
    if PROJECT_VENV not in executable.parents and prefix != PROJECT_VENV:
        raise RuntimeError(
            "Tests must run with the project virtual environment. "
            f"Expected Python under {PROJECT_VENV}, got {sys.executable}. "
            "Run: uv run python -m pytest ..."
        )


# each test runs on cwd to its temp dir
@pytest.fixture(autouse=True)
def go_to_tmpdir(request):
    # Get the fixture dynamically by its name.
    tmpdir = request.getfixturevalue("tmpdir")
    # ensure local test created packages can be imported
    sys.path.insert(0, str(tmpdir))
    # Chdir only for the duration of the test.
    with tmpdir.as_cwd():
        yield
