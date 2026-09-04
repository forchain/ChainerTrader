# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ChainerTrader is a Python-based algorithmic trading system implementing TradingView algorithms from YouTube channel "Shi Hun". It provides backtesting, live trading, and analysis capabilities for cryptocurrency markets using the backtrader framework.

**Key Technologies**: Python 3.11+, backtrader, FastAPI, MongoDB, Binance API

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

# Start with custom host/port and authentication
python -m trader --api 0.0.0.0:8080 --auth-username admin --auth-password pass --protected-paths "/admin"

# Run with configuration (using @ prefix to load from file)
python -m trader @configs/tasks/examples/backtrader_strategy.json

# Run backtesting with specific task configuration
python -m trader --tasks configs/tasks/examples/backtrader_strategy.json --db mongodb://localhost:27017/ --log_level DEBUG
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

### Application Entry Points
- **Main Entry**: `src/trader/__main__.py` → `src/trader/app/main.py`
- **Core Application**: `src/trader/app/app.py` (orchestrates all components)
- **Web API**: `src/trader/rpc/rpc_app.py` (FastAPI application)

### Core Systems

#### Task System (`src/trader/task/`)
The application is built around an asynchronous task-based architecture managed by `task_manager.py`. Tasks communicate via message queues (`common/message.py`). All tasks inherit from `base_task.py`.

**Task Types** (defined in `task_type.py`):
- `TRADER`: Live trading execution (`trader_task.py`)
- `BACK_TRADER`: Historical backtesting (`backtrader_task.py`)
- `UPDATE_KLINES`: Real-time data updates (`update_klines_task.py`)
- `CHECK_KLINES`: Data validation (`check_klines_task.py`)
- `IMPORT_CSV`: CSV data import (`import_csv_task.py`)

**Task Configuration**: JSON files in `configs/` define task parameters:
- `configs/tasks/examples/backtrader_strategy.json` - Multiple backtest configurations
- `configs/tasks/downloads/update_klines.json` - Data update settings
- `configs/notices/notice.json` - Notification configuration

#### Strategy Framework (`src/trader/strategy/`)
All strategies inherit from `base_strategy.py`. There is also an intermediate base `TrilogyStrategy` (in `trilogy_strategy.py`) for strategies using inflection-point trend detection.

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

#### Exchange Integration (`src/trader/exchange/`)
Modular exchange system currently supporting Binance:
- **Main Interface**: `binance/exchange.py` - Exchange operations
- **REST API**: `binance/restapi.py` - HTTP client
- **Data Management**: `binance/data.py` - Real-time market data
- **CSV Import**: `binance/csvdata.py` - Historical data from `data/` directory

**Supported Intervals**: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M

#### Database Layer (`src/trader/database/`)
MongoDB integration for:
- Kline data storage and retrieval
- Task state persistence (`task.py`)
- Historical data caching

#### Web API (`src/trader/rpc/`)
FastAPI-based REST API with automatic routing (`fastapi-auto-router`):
- **Public Endpoints**: `/api/config`, `/api/info`, `/api/tasks`, `/api/health`
- **Admin Interface**: `/admin` dashboard, `/admin/tasks`, `/admin/klines`, `/admin/logs`
- **Authentication**: HTTP Basic Auth with path-based protection

### Supporting Systems

**ChainerTrader Library** (`libraries/chainer_trader.py`): Pine Script–compatible helper class (`ChainerTraderLib`) used inside strategies. Provides `stop_price()`, `entry_confirm()`, `exit_confirm()`, and static `breakeven_price()` methods. Mirrors `src/pine_scripts/libraries/chainer_trader.pine`.

**Configuration**: `common/config.py` - Centralized configuration with environment variable support

**Statistics**: `statistics/statistics.py` - Performance metrics and reporting

**Notifications**: `notify/notify_manager.py` - Email and notification system

**Indicators**: `indicators/` - Custom technical indicators (KDJ, RSRS, QQE, SuperTrend, ChainerRSI, PivotHigh, PivotLow)

**Utilities**: `utils/` - Technical analysis helpers (MA, trend detection, kline utils, win rate, profit/loss ratio)

## Development Guidelines

### Creating New Strategies
1. Inherit from `BaseStrategy` (or `TrilogyStrategy` for inflection-point strategies)
2. Define strategy parameters using backtrader's `params` tuple
3. Initialize indicators in `__init__()`
4. Implement trading logic in `next()` method; use `enter_trade()`/`exit_trade()` for Chainer Framework v3 or `buy()`/`sell()` for direct orders
5. **No registration needed** — the factory (`strategy/strategy.py`) uses dynamic loading. Name your file using snake_case and the class using the corresponding PascalCase + `Strategy` suffix (e.g., `my_signal.py` → `MySignalStrategy`). Place the file directly in `strategy/` or in a subfolder `strategy/MySignal/MySignal.py` with the same class name.
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
- **Web Templates**: `src/trader/rpc/templates/` (if present)

## Security Notes

- **API Keys**: Never commit to version control. Use environment variables or `.env` file
- **Configuration**: `example.env` template provided - copy to `.env` and configure
- **Authentication**: Web API supports path-based HTTP Basic Auth for admin endpoints
- **Protected Paths**: Configure via `--protected-paths` or `TRADER_PROTECTED_PATHS` env var
