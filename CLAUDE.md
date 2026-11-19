# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ChainerTrader is a Python-based algorithmic trading system implementing TradingView algorithms from YouTube channel "Shi Hun". It provides backtesting, live trading, and analysis capabilities for cryptocurrency markets using the backtrader framework.

**Key Technologies**: Python 3.11+, backtrader, FastAPI, Tortoise ORM (SQLite by default), Binance API

## Commands

### Worktree Development

Shared agent rule: if you are operating inside a git worktree and the local Python environment is missing, restore it before running other repository commands that depend on Python or `.env` values.

Use this trigger:

```bash
[ -f .git ] && [ ! -d .venv ]
```

When it matches, run:

```bash
bash scripts/setup_worktree.sh
```

The script is idempotent and safe to re-run. It creates symlinks `.venv → <main_repo>/.venv` and `.env → <main_repo>/.env` so that `uv run` and `python-dotenv` work transparently. If recovery fails, stop and surface the error before continuing with Python-dependent work.

### Development Setup
```bash
# Install project and dependencies (supports uv or pip)
make install

# Format code with black and ruff
make fmt

# Run linters
make lint

# Run tests (includes linting)
make test

# Build documentation
make docs

# Clean build artifacts
make clean
```

### Running the Application
```bash
# Basic CLI usage
python -m trader -h
trader -h

# Start web API server (default: 127.0.0.1:8000)
python -m trader --api

# Start with custom host/port and bootstrap administrator login
python -m trader --api 0.0.0.0:8080 --auth-username admin --auth-password password123A --secret-key replace-with-service-secret

# Run with configuration (using @ prefix to load from file)
python -m trader @configs/tasks/examples/backtrader_strategy.json

# Run backtesting with specific task configuration
python -m trader --tasks configs/tasks/examples/backtrader_strategy.json --db sqlite://data/trader.db --log_level DEBUG
```

### Testing
```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=trader

# Run specific test file
pytest tests/test_strategy.py

# Run specific test
pytest tests/test_strategy.py::test_function_name
```

### Configuration
- Environment variables are loaded from `.env` file (copy from `example.env`)
- All environment variables use `TRADER_` prefix (e.g., `TRADER_LOG_LEVEL`, `TRADER_API`, `TRADER_DB`)
- Task configurations are JSON files in `configs/tasks/`

## Architecture

The repository uses a hexagonal (ports and adapters) layout. Dependencies point inward (`adapters` → `core`); `scripts/check_import_direction.py` and `tests/test_import_direction.py` enforce the boundary, and `scripts/check_repo_layout.py` enforces the file layout.

### Application Entry Points
- **Main Entry**: `src/trader/__main__.py` → `src/trader/main.py`, the single composition root that instantiates concrete adapters and injects them into use cases and inbound adapters
- **Web API**: `src/trader/adapters/inbound/http/factory.py` (`create_app(composition)`, FastAPI)
- **CLI**: `src/trader/adapters/inbound/cli/` (console runner, terminal rendering, signal scanner, `src/trader/adapters/inbound/cli/db.py` for the `trader-db` command)

### Core (`src/trader/core/`)
Business rules, use cases, and outbound port definitions, organized by bounded context:
- `shared/` — shared value objects (`Kline`, `SymbolInterval`, `OperateType`), config, interfaces
- `task/` — task domain, config codec, lifecycle/submission/recovery/cleanup use cases, fund reservation, statistics
- `execution/` — live execution modes, order semantics selection, gateway resolution, execution state
- `marketdata/` — kline coverage, dataset preparation, backfill/update use cases
- `exchange/` — exchange account and credential aggregate
- `identity/` — users, sessions, password policy, credential encryption
- `notification/` — notification rendering and use cases
- `strategy/` — framework-free strategy kernel (signal routing, lifecycle, risk, indicators, `TraderResult`)
- `optimization/` — optimization, market scanning, and selection use cases

### Adapters (`src/trader/adapters/`)
- `inbound/http/` — FastAPI factory, API routers, HTTP templates, static assets
- `inbound/cli/` — console entry points
- `outbound/persistence/` — Tortoise ORM models, migrations, connection lifecycle, repositories
- `outbound/binance/` — exchange client, REST access, execution gateway
- `outbound/backtrader/` — engine, feeds, strategy discovery and subclasses, task runners, gateway, custom indicators
- `outbound/marketstream/` — websocket and polling market-data connectors
- `outbound/{notification,email,execution,logging,identity,files}/` — supporting adapters

### Task System
Task types are `TRADER`, `BACK_TRADER`, `UPDATE_KLINES`, `CHECK_KLINES`, and `IMPORT_CSV`. Task domain rules and lifecycle use cases live in `src/trader/core/task/`; runners are implemented by outbound adapters such as `src/trader/adapters/outbound/backtrader/backtest_runner.py` and `live_trader_runner.py`.

**Task Configuration**: JSON files in `configs/` define task parameters:
- `configs/tasks/examples/backtrader_strategy.json` - Multiple backtest configurations
- `configs/tasks/downloads/update_klines.json` - Data update settings
- `configs/notices/notice.json` - Notification configuration

### Strategy Framework
Strategies live under `src/trader/adapters/outbound/backtrader/` and inherit from `BaseStrategy`; `TrilogyStrategy` is the intermediate base for inflection-point trend detection. The framework-free kernel lives in `src/trader/core/strategy/domain/` and must not import backtrader.

`BaseStrategy` provides:
- Order management with commission tracking
- Risk management (stop-loss, take-profit with ATR calculations)
- Trend analysis modes (NORMAL, UP, DOWN)
- **Chainer Framework v3** engine: `enter_trade()`/`exit_trade()` methods with `chainer_mode` param (`LONG_ONLY`, `SHORT_ONLY`, `BOTH`), auto-signal processing via `get_long_signal()`/`get_short_signal()`, breakeven management, and configurable confirmation bars

**Strategy Categories**:
- **Shi Hun Strategies**: `ShihunMACD`, `ShihunMACD2`, `ShihunRSI`, `ShihunRSI2`, `ShihunMACDRISBB`
- **Technical Strategies**: `MACDRSI`, `ChainerMACDRSI`, `TURTLE`, `KDJ`, `RSRS`, `DeviationMACD`, `MACDTripleDivergence`
- **Utility Strategies**: `DUALMA`, `DUALTHRUST`, `GRID`, `BOLLMEANREG`, `Aberration`, `SuperTrendQqeMod`
- **AI-variant Strategies**: `DeviationMACDClaude4`, `DeviationMACDGemini`, `DeviationMACDO3`, `DeviationMACDOptimized`

**Pine Script counterparts** live in `src/pine_scripts/` (indicators, libraries, and strategies directories) for TradingView compatibility.

### Exchange Integration
`src/trader/core/exchange/` defines the exchange ports; `src/trader/adapters/outbound/binance/` implements REST access, market data, and live order execution. Historical CSV feeds live in `src/trader/adapters/outbound/backtrader/csvdata.py` (data in `data/`).

**Supported Intervals**: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M

### Database Layer
Tortoise ORM over SQL; local development defaults to SQLite (`TRADER_DB`, default `sqlite://data/trader.db`). Models, migrations, and repositories live in `src/trader/adapters/outbound/persistence/` and store klines, availability metadata, tasks, execution state, users, and encrypted credentials.

### Web API
FastAPI app built by `create_app(composition)`; routers live in `src/trader/adapters/inbound/http/routers/`:
- **Public Endpoints**: `/api/config`, `/api/info`, `/api/health`
- **Admin Interface**: `/admin` dashboard, `/admin/tasks`, `/admin/klines`, `/admin/live`, `/admin/logs`, `/admin/users`
- **Authentication**: database-backed login with HTTP-only session cookies

### Supporting Systems

**ChainerTrader Library** (`src/trader/adapters/outbound/backtrader/libraries/chainer_trader.py`): Pine Script–compatible helper class (`ChainerTraderLib`) used inside strategies. Provides `stop_price()`, `entry_confirm()`, `exit_confirm()`, and static `breakeven_price()` methods. Mirrors `src/pine_scripts/libraries/chainer_trader.pine`.

**Configuration**: `src/trader/core/shared/config.py` - Centralized configuration with environment variable support

**Statistics**: `src/trader/core/task/use_cases/statistics.py` - Performance metrics and reporting

**Notifications**: `src/trader/core/notification/` with delivery through `src/trader/adapters/outbound/email/`

**Indicators**: `src/trader/adapters/outbound/backtrader/indicators/` - Custom technical indicators (KDJ, RSRS, QQE, SuperTrend, ChainerRSI, PivotHigh, PivotLow)

## Development Guidelines

### Creating New Strategies
1. Inherit from `BaseStrategy` (or `TrilogyStrategy` for inflection-point strategies)
2. Define strategy parameters using backtrader's `params` tuple
3. Initialize indicators in `__init__()`
4. Implement trading logic in `next()` method; use `enter_trade()`/`exit_trade()` for Chainer Framework v3 or `buy()`/`sell()` for direct orders
5. **No registration needed** — discovery in `src/trader/adapters/outbound/backtrader/catalog.py` uses dynamic loading. Name your file using snake_case and the class using the corresponding PascalCase + `Strategy` suffix (e.g., `my_signal.py` → `MySignalStrategy`). Place the file directly in `src/trader/adapters/outbound/backtrader/` or in a subfolder `<Name>/<Name>.py` with the same class name.
6. Reference via task config JSON using the file/folder name (e.g., `"strategy": "my_signal"` or `"strategy": "MySignal"`).

### Code Style
- **Line Length**: 150 characters (configured in `pyproject.toml`)
- **Formatter**: Black with target Python 3.12
- **Linter**: Ruff with E, F, I rules (errors, format, import sorting)
- **Type Hints**: Use for all public functions and methods
- **Imports**: Absolute imports from `trader` package, grouped by standard/third-party/local

### Git Workflow
- **Main Branch**: `main` (use for PRs)
- **Development Branch**: `dev` (currently active)
- **Commit Format**: Conventional commits (e.g., `feat:`, `fix:`, `docs:`)

### Testing Best Practices
- Test files in `tests/` directory
- Use `tests/conftest.py` for shared fixtures
- Mock external dependencies (APIs, databases)
- Test both success and failure cases
- Aim for high coverage (project targets 100%)

## Important Paths

- **Source Code**: `src/trader/`
- **Historical Data**: `data/` (CSV files)
- **Configuration**: `configs/` (JSON task configs and notices)
- **Tests**: `tests/`
- **Documentation**: `docs/`, `docs/strategies/`
- **Entry Point**: `src/trader/__main__.py`
- **Web Templates**: `src/trader/adapters/inbound/http/templates/`

## Security Notes

- **API Keys**: Never commit to version control. Use environment variables or `.env` file
- **Configuration**: `example.env` template provided - copy to `.env` and configure
- **Authentication**: Web console uses session login; `TRADER_AUTH_USERNAME` and `TRADER_AUTH_PASSWORD` bootstrap the first admin account
- **Exchange Credentials**: Per-user exchange API keys are encrypted with `TRADER_SECRET_KEY`; keep it stable and backed up
