## Context

The current persistence layer is MongoDB-specific. `DatabaseManager` initializes a `MongoClient`, `KlineCol` stores each symbol/interval in a separate collection, and DB-backed backtests are prepared by `DatasetResolver` exporting queried rows into `.cache/backtest_datasets/*.csv`. Both normal backtests and optimization workers then consume those exports through `BinanceCSVData`.

This creates two problems for the current workflow. First, local optimization is dominated by remote DB IO and CSV materialization rather than strategy execution. Second, the persistence model is tied to MongoDB collection semantics even though the project is expected to stay small-team/local for a while and may later move to PostgreSQL.

Tortoise ORM is the selected ORM. It is async-first, supports SQLite through `aiosqlite`, supports PostgreSQL through async drivers, and provides migration commands such as `tortoise makemigrations` and `tortoise migrate`. The design must therefore keep async database access contained at the orchestration/data-loading boundary while preserving synchronous Backtrader execution.

## Goals / Non-Goals

**Goals:**

- Use SQLite as the default primary database through Tortoise ORM.
- Preserve a database access abstraction so future PostgreSQL migration is mostly configuration, migrations, and backend validation rather than broad business-code rewrites.
- Store kline query fields relationally and retain the source exchange payload in a raw JSON/text field.
- Remove CSV export from DB-backed backtest and optimization execution paths.
- Keep explicit CSV tasks independent and unchanged in intent.
- Keep normal data preparation fast by checking only first/last local DB boundaries and filling edge ranges.
- Use explicit migration commands for schema evolution; do not silently mutate production schemas during backtests or app startup.

**Non-Goals:**

- Rewriting Backtrader, strategies, indicators, or feed loading into async code.
- Full internal kline gap detection or repair during normal backtest/optimization preparation.
- Maintaining MongoDB as a supported primary database after this change.
- Building a transparent MongoDB-to-SQL dual-write layer.
- Guaranteeing that PostgreSQL migration is literally only a URL change; the design minimizes coupling, but migrations and backend-specific validation remain required.

## Decisions

1. Use Tortoise ORM as the single database access layer.

   Repository classes should be backed by Tortoise models and expose project-specific operations such as `get_klines`, `add_klines`, `get_first_kline`, `get_latest_kline`, task-state persistence, and availability metadata updates. Application logic should not import Tortoise models directly outside the database package.

   Alternative considered: use raw `sqlite3` for local speed and simplicity. This was rejected because it would make the future PostgreSQL path more expensive and would spread SQL dialect decisions into repository code.

2. Make database lifecycle and repository APIs async.

   Tortoise does not provide a full synchronous ORM API. `DatabaseManager.start()`, `DatabaseManager.stop()`, and repository methods should become async and be awaited from existing async orchestration paths. The app should initialize Tortoise once per process and close connections once per process.

   The synchronous Backtrader execution layer should not call Tortoise directly. DB-backed execution should load all required klines before constructing the Backtrader data feed.

3. Keep Backtrader feeds synchronous.

   For the first implementation, DB-backed tasks should query the required kline range into `list[Kline]` and use the existing `BinanceData(klines)` feed. This avoids async work inside `feed._load()` and matches Backtrader's synchronous execution model.

   A cursor-backed SQL feed can be added later if datasets become large enough to make list loading a measured memory bottleneck.

4. Use one relational `klines` table, not one table per symbol/interval.

   The kline table should use typed columns for common query fields and a unique composite key on `(exchange, symbol, interval, open_time)`. Suggested fields:

   - `exchange`
   - `symbol`
   - `interval`
   - `open_time`
   - `open`, `high`, `low`, `close`
   - `close_time`
   - `volume`, `vol_quote`, `trades`, `vol_taker_base`, `vol_taker_quote`
   - `ignore`
   - `raw_payload`
   - `ingested_at`
   - `source`

   This schema is more portable to PostgreSQL than dynamic table names and gives the optimizer a clear composite index for range scans.

5. Keep task and availability storage relational.

   `tasks` should preserve task runtime state using typed columns for common state fields and JSON/text columns for nested configuration/result payloads. `availability` should use a unique key on `(exchange, symbol, interval)` and continue to record `earliest_known_open_time`, `updated_at`, and `source`.

   Availability is not a cache. It is coverage metadata used to avoid repeated downloads before the exchange's known earliest candle.

6. Replace `DatasetResolver` CSV materialization with DB coverage planning.

   For DB-backed tasks, the data preparation path should:

   - normalize requested `start_time`/`end_time` by the strategy interval
   - inspect the SQL database first/last open time for the requested exchange/symbol/interval
   - download only edge ranges before the local first bar or after the local last bar when auto-download is enabled
   - return a logical dataset/source descriptor, not a CSV path
   - let execution load rows from SQL and construct `BinanceData`

   Internal gaps should remain accepted in this fast path.

7. Keep CSV mode explicit.

   A task with `csv` configured should continue to use `BinanceCSVData` and apply the task's time filters to that CSV. A task without `csv` but with DB configuration should use SQL-backed data loading. The system should not export a temporary CSV merely because the source is DB.

8. Update optimization worker specs to carry source descriptors.

   `BacktestSampleSpec` currently requires `data_path`. It should distinguish at least:

   - `source_type="csv"` with `data_path`
   - `source_type="db"` with `db_url`, `exchange`, `symbol`, `interval`, `start_time`, and `end_time`

   Each worker process should initialize Tortoise for its process, load the kline list once, close DB connections, and then run Backtrader synchronously.

9. Use explicit Tortoise migrations.

   The project should configure Tortoise migrations for the database models and provide project-level wrappers for migration commands. `generate_schemas()` should be reserved for empty test databases or local throwaway setup, not for runtime schema evolution. Backtest, optimization, and server startup should fail clearly if required tables/migrations are missing.

10. Treat MongoDB data as legacy.

   The implementation should remove MongoDB from the primary runtime path. Existing users can re-download market data into SQLite or import CSV data. A one-off Mongo export/import tool can be considered separately if historical Mongo data must be preserved, but it should not complicate the primary DB design.

## Risks / Trade-offs

- Tortoise async APIs can spread through synchronous code → Keep Tortoise calls inside database/data-loading orchestration and pass `list[Kline]` into synchronous Backtrader components.
- SQLite write concurrency is limited → Use SQLite for the current local/small-team deployment, keep writes batched/idempotent, and document PostgreSQL as the scale-up path.
- Loading all klines into memory can become expensive for very large ranges → Start with list-backed `BinanceData`; add a cursor feed only after memory usage is measured.
- SQLite and PostgreSQL JSON behavior differs → Store raw payload through a repository abstraction and avoid backend-specific JSON queries in core backtest logic.
- Migration autodetection can misinterpret renames or complex changes → Require generated migrations to be reviewed and include tests for schema changes.
- Removing CSV materialization changes report/debug assumptions around `dataset_ref.path` → Replace path-oriented metadata with logical dataset identifiers and source descriptors in reports.
- Existing active OpenSpec work targets a local cache over MongoDB → Supersede that change rather than layering this design on top of it.

## Migration Plan

1. Add Tortoise dependencies, model modules, migration configuration, and initial migrations.
2. Implement async SQL-backed `DatabaseManager`, kline repository, task repository, and availability repository behind the existing database package boundary.
3. Update app and task orchestration to initialize and close the async DB lifecycle correctly.
4. Update download/import/check tasks to use async SQL repositories.
5. Replace DB-backed dataset preparation with interval-aligned SQL coverage planning and edge-only auto-download.
6. Update normal backtest execution to load DB klines directly into `BinanceData`.
7. Update optimization sample specs and workers to support DB source descriptors.
8. Rewrite DB tests around isolated SQLite databases and Tortoise migrations.
9. Update README, database architecture docs, runtime-context checks, and CLI help.
10. Remove or quarantine MongoDB-specific code, scripts, and tests after SQL paths are covered.

Rollback before release is to keep the MongoDB code path on the previous branch. After release, rollback requires restoring MongoDB dependencies and data access code from version control; there should not be a dual-write fallback in the new primary path.

## Open Questions

- Should the first implementation include a one-off MongoDB-to-SQL migration command, or is re-download/CSV import sufficient for current users?
- Should `TRADER_DB_NAME` be removed immediately or kept as a deprecated no-op for one release?
- Should DB-backed optimization workers keep DB connections open for the full sample run, or load/close before Backtrader starts to reduce connection lifetime?
