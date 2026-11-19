import asyncio
import gc
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


@pytest.fixture(scope="session", autouse=True)
def close_database_connections():
    """Close every database connection the suite opened before the interpreter exits.

    The SQLite backend runs each Tortoise connection on a non-daemon aiosqlite worker
    thread, so a connection left open after the last test keeps the interpreter in
    shutdown forever instead of letting pytest return (#118). ``Tortoise`` can only
    close the connections of its currently active context, so connections opened
    inside a test's own ``asyncio.run`` loop (whose context is discarded when that
    loop closes) are swept separately.
    """
    yield
    asyncio.run(_close_database_connections())


async def _close_database_connections() -> None:
    from tortoise import Tortoise

    await Tortoise.close_connections()

    failures = []
    for connection in _live_aiosqlite_connections():
        try:
            await connection.close()
        except Exception as exc:  # pragma: no cover - defensive teardown
            failures.append(exc)
    if failures:
        raise RuntimeError(f"failed to close {len(failures)} leftover aiosqlite connection(s): {failures!r}")


def _live_aiosqlite_connections() -> list:
    from aiosqlite.core import Connection as AiosqliteConnection

    # aiosqlite clears its private _running flag once the worker thread has stopped.
    return [obj for obj in gc.get_objects() if isinstance(obj, AiosqliteConnection) and getattr(obj, "_running", False)]
