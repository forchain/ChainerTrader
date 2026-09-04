## 1. Dependency And Migration Setup

- [x] 1.1 Add Tortoise ORM and SQLite driver dependencies to project packaging.
- [x] 1.2 Add Tortoise ORM configuration that reads `TRADER_DB` as the database URL.
- [x] 1.3 Add initial migration configuration for the project database models.
- [x] 1.4 Add project-level CLI or script wrappers for database migration commands.
- [ ] 1.5 Document that runtime workflows must not call schema generation or auto-migrate on startup.

## 2. SQL Data Models

- [x] 2.1 Add Tortoise model for relational kline storage with typed OHLCV fields.
- [x] 2.2 Add unique composite constraint and range-query index for kline exchange, symbol, interval, and open time.
- [x] 2.3 Add raw source payload and ingestion metadata fields to the kline model.
- [x] 2.4 Add Tortoise model for task runtime state.
- [x] 2.5 Add Tortoise model for availability metadata with unique exchange, symbol, and interval constraint.
- [x] 2.6 Generate and review the initial database migration.

## 3. Async Repository Layer

- [x] 3.1 Replace MongoDB `DatabaseManager` startup and shutdown with async Tortoise lifecycle management.
- [x] 3.2 Implement async kline repository methods equivalent to current kline collection behavior.
- [x] 3.3 Implement async task repository methods equivalent to current task collection behavior.
- [x] 3.4 Implement async availability repository methods equivalent to current availability collection behavior.
- [x] 3.5 Keep Tortoise model imports inside the database package boundary.
- [ ] 3.6 Remove or quarantine MongoDB-specific collection naming and pymongo code from the primary runtime path.

## 4. Data Ingestion And Coverage Preparation

- [x] 4.1 Update kline download tasks to await SQL repository reads and writes.
- [x] 4.2 Preserve edge-only update behavior using local first and last SQL kline boundaries.
- [x] 4.3 Ensure normal preparation does not scan or repair internal kline gaps.
- [ ] 4.4 Capture raw exchange payloads during ingestion when the source provides them.
- [x] 4.5 Update CSV import tasks to write imported klines through the SQL repository.
- [x] 4.6 Update kline check/debug/statistics paths to use async SQL repositories.

## 5. Backtest And Optimization Data Flow

- [x] 5.1 Refactor DB-backed backtest startup to load SQL klines directly into `BinanceData`.
- [x] 5.2 Keep CSV-backed tasks on `BinanceCSVData` with existing time-window behavior.
- [x] 5.3 Replace file-path-only `dataset_ref` assumptions with logical dataset/source descriptors for DB-backed tasks.
- [x] 5.4 Update dataset preparation to return DB source metadata instead of materialized CSV paths.
- [x] 5.5 Extend optimization sample specs to support `source_type=csv` and `source_type=db`.
- [x] 5.6 Update optimization workers to initialize Tortoise, load DB klines once, close DB connections, and then run Backtrader synchronously.
- [x] 5.7 Preserve optimization report dataset identity without requiring a CSV path.

## 6. Configuration And CLI Surface

- [x] 6.1 Update CLI help so `--db` describes a generic Tortoise database URL and defaults to SQLite.
- [x] 6.2 Deprecate or remove MongoDB-specific `--db_name` / `TRADER_DB_NAME` behavior.
- [ ] 6.3 Update runtime context checks for database-backed backtests and optimizations to validate SQL DB configuration.
- [ ] 6.4 Update scripts that currently inspect MongoDB directly to use SQL repositories or documented migration commands.

## 7. Tests

- [x] 7.1 Add isolated SQLite/Tortoise test setup for repository tests.
- [x] 7.2 Add tests for kline uniqueness, ordered range queries, first/last lookup, and idempotent upsert behavior.
- [x] 7.3 Add tests for task state upsert/retrieval behavior.
- [x] 7.4 Add tests for availability metadata lookup and monotonic earliest-known-time updates.
- [x] 7.5 Add tests proving DB-backed backtests construct `BinanceData` without creating a CSV export.
- [x] 7.6 Add tests proving CSV-backed backtests still construct `BinanceCSVData`.
- [x] 7.7 Add tests for edge-only SQL coverage preparation before local first and after local last.
- [x] 7.8 Add tests proving internal gaps are not scanned or repaired during normal preparation.
- [x] 7.9 Add optimization worker tests for DB source descriptors and CSV source descriptors.
- [ ] 7.10 Remove or rewrite pymongo stubs and MongoDB-specific tests.

## 8. Documentation And Cleanup

- [ ] 8.1 Update README database setup, environment variables, migration workflow, and CSV-vs-DB backtest usage.
- [ ] 8.2 Rewrite `docs/architecture/database-design.md` for the Tortoise/SQL schema.
- [ ] 8.3 Update OpenSpec/docs references that say backtest data must come from MongoDB.
- [ ] 8.4 Document the one-time data transition path from existing MongoDB usage to SQLite re-download or CSV import.
- [x] 8.5 Validate the full OpenSpec change with `openspec validate tortoise-sqlite-primary-database --strict`.
