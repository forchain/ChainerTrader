# ChainerTrader

ChainerTrader is a Python-based crypto trading system for running strategy backtests, batch optimizations, market scans, and a lightweight operations API around the same task engine.

This README is user-facing. It explains what the project does, how it is structured from an operator's point of view, how to deploy it, and how to use its exposed interfaces.

## What It Does

ChainerTrader exposes one runtime with several user-visible capabilities:

- Historical backtesting from CSV or database-backed market data
- Parameter optimization over declared task matrices
- Market-data preparation and kline synchronization
- Strategy signal scanning
- Web API and admin pages for monitoring tasks and runtime state

## Architecture

### High-Level Flow

```text
                +----------------------+
                |   User Interfaces    |
                |----------------------|
                | CLI / JSON configs   |
                | REST API / Admin UI  |
                +----------+-----------+
                           |
                           v
                +----------------------+
                |   Task Orchestrator  |
                |----------------------|
                | Task parsing         |
                | Task scheduling      |
                | Backtest execution   |
                | Optimization runs    |
                +----+------------+----+
                     |            |
                     |            |
                     v            v
          +----------------+   +------------------+
          | Strategy Layer |   | Data Preparation |
          |----------------|   |------------------|
          | Backtrader     |   | CSV datasets     |
          | Chainer engine |   | MongoDB klines   |
          | Strategy logic |   | Exchange sync    |
          +--------+-------+   +---------+--------+
                   |                     |
                   +----------+----------+
                              |
                              v
                   +----------------------+
                   | Outputs & Operations |
                   |----------------------|
                   | JSON reports         |
                   | Optimization reports |
                   | Logs / runtime state |
                   | Admin pages / API    |
                   +----------------------+
```

### Module Overview

- `src/trader/app/`
  User entrypoint and application startup.
- `src/trader/task/`
  Task parsing, task scheduling, background optimization orchestration, and report generation.
- `src/trader/strategy/`
  Trading and backtesting strategies, including the Chainer framework-based strategies.
- `src/trader/exchange/`
  Exchange access and market-data handling.
- `src/trader/database/`
  Database-facing storage and query logic.
- `src/trader/rpc/`
  Web API and admin pages.
- `src/trader/scanner/`
  Market scanning workflows and signal extraction.
- `configs/`
  User-facing task and notice configuration assets.

## Database Design

ChainerTrader uses MongoDB as its primary persistent store for runtime and historical market data workflows.

Detailed database design reference:

- [docs/architecture/database-design.md](docs/architecture/database-design.md)

### Collections Overview

ChainerTrader uses three main collection families in MongoDB.

#### 1. `klines-<symbol-interval>`

One collection per trading pair and timeframe, for example:

- `klines-BTCUSDT-1h`
- `klines-ETHUSDT-4h`

Purpose:

- historical market data for backtests
- source data for optimization runs
- persistent cache for update/download tasks

Fields:

- `open_time`
  Primary key. Candle open timestamp.
- `open_datetime`
  Human-readable open timestamp.
- `open`
  Candle open price.
- `high`
  Candle high price.
- `low`
  Candle low price.
- `close`
  Candle close price.
- `close_time`
  Candle close timestamp.
- `close_datetime`
  Human-readable close timestamp.
- `volume`
  Base-asset traded volume in the candle.
- `vol_quote`
  Quote-asset traded volume in the candle.
- `trades`
  Number of trades in the candle.
- `vol_taker_base`
  Taker buy base-asset volume.
- `vol_taker_quote`
  Taker buy quote-asset volume.
- `ignore`
  Exchange compatibility field carried through from source kline payloads.

Indexes:

- unique index on `open_time`

#### 2. `tasks`

Stores persisted runtime task state.

Purpose:

- track task execution state
- expose task status to the admin/API layer
- persist summary information for running or finished tasks

Fields:

- `task_id`
  Primary key for the task state record.
- `state`
  Current state, for example `READY`, `RUNNING`, `DONE`.
- `name`
  User-visible task name.
- `start_time`
  Task start timestamp.
- `commission`
  Commission configured for the task.
- `strategy_start_time`
  Backtest/strategy window start when applicable.
- `strategy_end_time`
  Backtest/strategy window end when applicable.
- `initial_cash`
  Initial capital used by the task when applicable.
- `config_json`
  Serialized task configuration snapshot.
- `tret`
  Serialized trader/backtest result payload when present.

Indexes:

- unique index on `task_id`

#### 3. `availability`

Stores market-data coverage metadata by exchange, symbol, and interval.

Purpose:

- track earliest known historical coverage
- support backward-fill and dataset preparation logic
- help optimization and backtest flows avoid unnecessary downloads

Fields:

- `exchange`
  Exchange name, for example `BINANCE`.
- `symbol`
  Trading symbol, for example `BTCUSDT`.
- `interval`
  Candle interval, for example `1h` or `1d`.
- `earliest_known_open_time`
  Earliest candle open time known to exist for this market stream.
- `updated_at`
  Timestamp of the latest metadata update.
- `source`
  Why or how the availability record was updated, for example `backward_fill`.

Indexes:

- unique composite index on `(exchange, symbol, interval)`

### Collection Relationships

The database is intentionally simple and uses loose relationships instead of heavy joins.

```text
availability
    |
    | (exchange, symbol, interval) coverage metadata
    v
klines-<symbol-interval>
    |
    | used by
    +--------------------+
                         |
                         v
                       tasks
```

Relationship rules:

- `availability` describes coverage for a market stream
- `klines-<symbol-interval>` stores the actual candles for that market stream
- `tasks` references that data indirectly through task configuration, symbol, interval, and time-window fields

There is no relational foreign key between these collections. The relationship is established by:

- exchange
- symbol
- interval
- task configuration / task window

### Design Intent

This database design supports:

- reuse of downloaded market data across multiple backtests
- database-backed backtests without requiring users to maintain every CSV by hand
- incremental kline updates
- optimization runs that reuse prepared datasets instead of repeatedly downloading the same data
- lightweight runtime state tracking without a complex relational schema

### Operational Data Flow

```text
Exchange / CSV
     |
     v
Data preparation
     |
     v
MongoDB kline storage
     |
     +--> backtests
     +--> optimization runs
     +--> update/check tasks
     +--> scans using prepared market windows
```

### When README Must Change

If the project changes any of the following, README should be updated:

- database design
- schema / collection responsibilities
- storage layout
- user-visible data preparation model

## Repository Layout For Users

The main user-facing assets are:

- `configs/tasks/...`
  Task JSON files for backtests, optimizations, and data preparation
- `configs/notices/...`
  Notice configuration
- `scripts/`
  Operational helper scripts and thin wrappers

Representative config locations:

- `configs/tasks/examples/backtrader_strategy.json`
- `configs/tasks/backtests/multi_backtrader.json`
- `configs/tasks/downloads/update_klines.json`
- `configs/tasks/optimizations/macd_triple_divergence_engine_optimization.json`
- `configs/notices/notice.json`

## Deployment

### Requirements

- Python 3.11+
- `uv` recommended for environment management
- MongoDB if you want database-backed workflows
- Exchange credentials if you want live exchange-backed data operations

### Local Setup

```bash
git clone https://github.com/ChainerLabs/Trader.git
cd trader
make install
```

### Environment Configuration

Create a `.env` file from `example.env` and fill in the values you need.

Common settings:

```env
TRADER_LOG_LEVEL="INFO"
TRADER_DB="mongodb://localhost:27017/"
TRADER_EXCHANGE='{"ty":"BINANCE","api_key":"","api_secret":""}'
TRADER_API="127.0.0.1:8000"
TRADER_NOTICE="./configs/notices/notice.json"
```

### Runtime Modes

- CLI mode
  Run backtests, optimizations, data tasks, or scans directly
- API mode
  Start the HTTP service for admin pages and API access

## CLI Manual

### Show Help

```bash
python -m trader -h
# or
trader -h
```

### Run a Task File

```bash
python -m trader --tasks configs/tasks/examples/backtrader_strategy.json
```

### Run a Backtest Against MongoDB / Exchange-Prepared Data

```bash
python -m trader \
  --tasks configs/tasks/backtests/multi_backtrader.json \
  --db mongodb://localhost:27017/ \
  --exchange=BINANCE \
  --log_level INFO
```

### Run an Optimization Background Job

```bash
python scripts/run_optimization_background.py \
  --tasks configs/tasks/optimizations/macd_triple_divergence_engine_optimization.json \
  --stat 500
```

### Check Optimization Run Status

```bash
python scripts/check_optimization_status.py --run-id <run-id>
```

### Validate Runtime Context

```bash
python scripts/check_runtime_context.py --profile base
python scripts/check_runtime_context.py --profile db-backtest
python scripts/check_runtime_context.py --profile optimization
```

### Update / Check Kline Data

```bash
python -m trader \
  --tasks configs/tasks/downloads/update_klines.json \
  --db mongodb://localhost:27017/ \
  --exchange=BINANCE
```

### Notice Configuration

If you want runtime notices, point `TRADER_NOTICE` or CLI configuration at:

```text
configs/notices/notice.json
```

## API Manual

ChainerTrader exposes a web API and admin interface.

### Start the Web Server

```bash
python -m trader --api
python -m trader --api 0.0.0.0:8080
python -m trader --api --auth-username admin --auth-password your_secure_password
```

### Authentication

The web interface supports HTTP Basic Auth with path-based protection.

Environment variables:

```bash
export TRADER_AUTH_USERNAME="admin"
export TRADER_AUTH_PASSWORD="your_secure_password"
export TRADER_PROTECTED_PATHS="/admin,/api/admin"
```

CLI example:

```bash
python -m trader \
  --api \
  --auth-username admin \
  --auth-password your_secure_password \
  --protected-paths "/admin,/api/admin"
```

### API Surface

Web pages:

- `/`
- `/admin`
- `/admin/tasks`
- `/admin/klines`
- `/admin/logs`

Public endpoints by default:

- `/api/config`
- `/api/info`
- `/api/tasks`
- `/api/health`
- `/api/health/ready`

Protected endpoints when configured:

- `/admin`
- `/api/admin`
- `/api/admin/users`
- `/api/admin/system`

## Common User Workflows

### 1. Run a backtest from a task file

```bash
python -m trader --tasks configs/tasks/examples/backtrader_strategy.json
```

### 2. Prepare or update market data

```bash
python -m trader \
  --tasks configs/tasks/downloads/update_klines.json \
  --db mongodb://localhost:27017/ \
  --exchange=BINANCE
```

### 3. Launch an optimization run and inspect its status

```bash
python scripts/run_optimization_background.py \
  --tasks configs/tasks/optimizations/macd_triple_divergence_engine_optimization.json

python scripts/check_optimization_status.py --run-id <run-id>
```

### 4. Start the operations API

```bash
python -m trader --api
```

## Notes

- README is for users and operators. Internal implementation detail belongs in developer-facing docs and code.
- If a change affects project introduction, architecture presentation, deployment, database structure, CLI usage, API usage, or any other user-facing interface, README should be updated with the same change.

## Development

Developer-specific guidance lives outside README. Start with:

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [AGENTS.md](AGENTS.md)
