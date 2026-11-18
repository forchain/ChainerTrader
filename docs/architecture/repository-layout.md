# Repository Layout

This document defines where new files belong in ChainerTrader.

## Directory Responsibilities

- `src/trader/`: reusable application logic, product code, CLI modules, internal tools
- `src/trader/core/`: stable domain and application layer, organized by bounded context
- `src/trader/adapters/inbound/`: HTTP and CLI entry adapters
- `src/trader/adapters/outbound/`: persistence, exchange, backtrader, market-stream, email, and file adapters
- `configs/`: non-executable configuration assets such as task JSON and notice JSON
- `scripts/`: operational shell scripts and thin compatibility wrappers
- `tests/`: automated verification, fixtures, and test-only helpers
- `docs/architecture/`: durable architecture and repository-structure guidance

## Hexagonal Package Layout

Layering follows ADR-0003. Dependencies point inward: `adapters/` may import `core/`, but `core/` must never import `adapters/` or a framework.

```text
src/trader/
├── core/                      # stable domain + application layer
│   ├── shared/                # Symbol, SymbolInterval, Kline, Operate, time ranges
│   ├── task/                  # task bounded context
│   ├── execution/             # execution state records bounded context
│   ├── marketdata/            # kline and dataset bounded context
│   ├── exchange/              # exchange account bounded context
│   ├── identity/              # users, sessions, credentials
│   ├── notification/          # notice rendering and delivery use cases
│   ├── strategy/              # framework-free signal/risk kernel and indicators
│   └── optimization/          # candidate universes, task templates, selection results
└── adapters/
    ├── inbound/
    │   ├── http/              # routes, session middleware, SSE, error translation
    │   └── cli/               # console-mode execution and report rendering
    └── outbound/
        ├── persistence/       # Tortoise models, migrations, repositories
        ├── binance/           # exchange and market-data clients
        ├── backtrader/        # engine, live feeds, strategy subclasses, gateway
        ├── marketstream/      # websocket connector and hub
        ├── email/             # notice sender
        └── files/             # CSV, task-config, and report storage
```

Rules:

- New business rules and use cases belong under `src/trader/core/<bounded-context>/`
- New outbound integrations belong under `src/trader/adapters/outbound/<kind>/`
- New inbound interfaces belong under `src/trader/adapters/inbound/{http,cli}/`
- Only the composition root may instantiate concrete adapters
- `scripts/check_repo_layout.py` rejects Python files outside the bounded-context and adapter packages above
- `tests/test_import_direction.py` rejects any `core/` import of `trader.adapters` or a framework

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
| Business rule or use case | `src/trader/core/<bounded-context>/...` | `src/trader/adapters/...` |
| Outbound integration | `src/trader/adapters/outbound/<kind>/...` | `src/trader/core/...` |
| Inbound HTTP or CLI adapter | `src/trader/adapters/inbound/{http,cli}/...` | `src/trader/core/...` |

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
- Importing `trader.adapters` or a framework from `src/trader/core/`
- Putting outbound integrations or inbound routes under `src/trader/core/`
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
