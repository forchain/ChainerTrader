## Why

Backtest and parameter optimization runs currently spend too much time in data preparation because database-backed tasks are routed through remote MongoDB reads and intermediate CSV materialization. The project should use a local SQL database as the primary historical-data store so repeated backtests read from fast local indexed storage and avoid cache/export churn.

SQLite with Tortoise ORM fits the current deployment stage: it keeps setup and operations simple, supports structured querying for common kline fields, and leaves a clearer path to PostgreSQL than a MongoDB-specific persistence layer.

## What Changes

- **BREAKING** Replace MongoDB as the primary project database with a Tortoise ORM-backed SQL database, defaulting to SQLite.
- **BREAKING** Change DB-backed backtests and optimization samples so they read kline data directly from the database instead of exporting and consuming an intermediate Backtrader CSV file.
- Add Tortoise ORM models and repository implementations for klines, task state, and availability metadata.
- Store common kline fields in typed relational columns and preserve source exchange payloads in a raw JSON/text field for future data-source flexibility.
- Keep CSV mode independent: tasks configured with `csv` continue to read CSV files directly; tasks without `csv` use the configured database.
- Use explicit Tortoise migrations for schema changes; application startup and backtest execution must not silently mutate database schema.
- Preserve interval-aligned edge-fill behavior for database data preparation: fill only before the local first bar or after the local last bar, and do not scan or repair internal gaps during normal backtest/optimization preparation.
- Supersede the local-cache direction from `incremental-local-dataset-cache`; the SQL database is the primary local store rather than an added cache layer over MongoDB.

## Capabilities

### New Capabilities

- `tortoise-sqlite-database`: Defines the Tortoise ORM-backed SQL database, schema ownership, migrations, repository contracts, and SQLite/PostgreSQL portability expectations.
- `db-backed-backtest-data`: Defines direct database-backed data loading for regular backtests and optimization workers while keeping CSV mode independent.

### Modified Capabilities

- `backtest-data-split`: Replace MongoDB-specific data-source requirements with the project SQL database and preserve the existing auto-download/backtest split intent.

## Impact

- Dependencies: add Tortoise ORM and its SQLite driver support; remove MongoDB/pymongo as the primary runtime database dependency.
- Configuration: `TRADER_DB` becomes a generic database URL such as `sqlite://data/trader.db`; `TRADER_DB_NAME` becomes Mongo-specific legacy state and should be removed or deprecated.
- Database layer: `src/trader/database/manager.py`, `kline.py`, `task.py`, and `availability.py` need async Tortoise-backed implementations.
- Backtest data path: `src/trader/task/backtrader_task.py`, `dataset_resolver.py`, and `task_manager.py` need to stop assuming `dataset_ref.path` points to a CSV file for DB-backed tasks.
- Optimization workers: `BacktestSampleSpec` and `run_backtest_sample()` need a DB source descriptor in addition to CSV paths.
- Data ingestion: `update_klines_task.py`, `import_csv_task.py`, and download scripts need to write/read through the SQL repositories.
- Tests: Mongo/pymongo stubs and DB-backed backtest tests need to be rewritten around Tortoise/SQLite test databases.
- Docs: README and `docs/architecture/database-design.md` need to describe the SQL schema, migration workflow, and CSV-vs-DB data-source behavior.
