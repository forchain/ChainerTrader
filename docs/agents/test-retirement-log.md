# Test Retirement Log

Record of tests retired because they no longer express a valid contract for the current
architecture. The policy that governs this log is the `Testing Policy` section of
`AGENTS.md` and issue #119.

## Policy summary

- A test that times out at the 60-second per-test budget, hangs, spins, or blocks on a
  resource is invalidated by the architecture. Default action: delete the test, or the
  whole file when every test in it targets a removed design, together with the imports,
  helpers, and fixtures it owned. The remaining module must stay importable.
- Exception: if the test targets behaviour that still exists and the repair is a
  one-liner inside the test itself, repair it in place instead of deleting it.
- No deletion is silent. Every retired test is recorded here with its id, file, category,
  why it was invalidated, and the new-architecture area it must be re-authored against.
- Slowness alone is not a retirement reason. Only exceeding the 60-second budget is.

## Retired tests

_None._ No test has been retired.

## Measurement evidence

- Measured 2026-11-19 on branch `butterflyray` (base `5d580a1`) with
  `uv run python -m pytest -q --timeout=60 --timeout-method=signal --durations=0`.
- Suite result: `1165 passed, 21 skipped`, whole run about 24 seconds.
- Slowest test: **6.29s**
  `tests/test_cli_task_handling.py::test_app_start_runs_startup_self_check_before_task_launch`.
  The next slowest is 2.01s; everything else is under 0.5s.
- No test exceeds the 60-second budget, so nothing qualified for retirement on this
  measurement.

## Guarded instead of retired

These files reach the network but still express valid contracts, so they were guarded
with an opt-in skip and kept (#116):

- `tests/test_binanceconnector.py` — skips unless `TRADER_BINANCE_INTEGRATION` is set.
- `examples/test_admin_pages.py` — an interactive smoke script, excluded from default
  collection by `testpaths = tests` in `pytest.ini`; still runnable manually.

## Queued for re-authoring

_None._ No coverage area is queued because no test was retired.

## Harness-level fixes that avoided retirement

The suite used to print its summary and then never exit (#118). The cause was leaked
non-daemon aiosqlite worker threads from tests that closed Tortoise in the wrong event
loop, not a slow test. It was fixed in `tests/conftest.py` and in the two indicator tests
(#118), with no test deleted.
