# Repository Layout

This document defines where new files belong in ChainerTrader.

## Directory Responsibilities

- `src/trader/`: reusable application logic, product code, CLI modules, internal tools
- `configs/`: non-executable configuration assets such as task JSON and notice JSON
- `scripts/`: operational shell scripts and thin compatibility wrappers
- `tests/`: automated verification, fixtures, and test-only helpers
- `docs/architecture/`: durable architecture and repository-structure guidance

## File Placement Rules

| New Asset | Correct Location | Incorrect Location |
| --- | --- | --- |
| Backtest task JSON | `configs/tasks/backtests/...` or `configs/tasks/examples/...` | `scripts/` |
| Optimization task JSON | `configs/tasks/optimizations/...` | `scripts/` |
| Download/update task JSON | `configs/tasks/downloads/...` | `scripts/` |
| Notice JSON | `configs/notices/...` | `scripts/` |
| Reusable Python logic | `src/trader/...` | `scripts/...` |
| Operational shell script | `scripts/ops/...` | `src/trader/...` |
| Thin compatibility wrapper | `scripts/wrappers/...` | root directory |
| Test fixtures | `tests/fixtures/...` | random paths under `tests/` |

## Common Examples

- Add a new backtest template:
  `configs/tasks/backtests/<name>.json`
- Add a new optimization task template:
  `configs/tasks/optimizations/<name>.json`
- Add a reusable status summarizer:
  `src/trader/tools/<name>.py`
- Add a product CLI entry:
  `src/trader/cli/<name>.py`
- Add a shell helper for developers:
  `scripts/ops/<name>.sh`

## Anti-Patterns

- Adding new `scripts/*.json` task files
- Leaving reusable, unit-testable Python logic in `scripts/*.py`
- Making tests depend on `scripts/...` when they could target `src/trader/...`
- Committing generated reports or other runtime output under `tests/output/`

## Structural Refactor Policy

Structural changes must be executed in a git worktree when they involve:

- multi-directory file migration
- bulk path or import updates
- changes to repository layout rules or directory responsibilities
- coordinated updates across `src/`, `scripts/`, `configs/`, and `tests/`

Update documentation, agent guidance, and automated guardrails in the same change.
