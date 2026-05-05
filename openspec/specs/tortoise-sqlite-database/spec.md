## Purpose
Defines the Tortoise ORM primary database layer, default SQLite configuration, relational schemas, and explicit migration expectations.

## Requirements
### Requirement: Tortoise ORM primary database

The system SHALL use Tortoise ORM as the project database access layer for runtime state, historical kline data, and availability metadata.

#### Scenario: Application initializes configured SQL database
- **WHEN** `TRADER_DB` is configured with a supported SQL database URL
- **THEN** the application SHALL initialize Tortoise ORM for that database before executing database-backed tasks

#### Scenario: Application closes database connections
- **WHEN** the application stops after using the database
- **THEN** the application SHALL close Tortoise ORM connections for the current process

#### Scenario: Database access is isolated behind repositories
- **WHEN** application code needs kline, task, or availability data
- **THEN** it SHALL access that data through repository interfaces under `src/trader/database/` rather than importing Tortoise models directly

### Requirement: SQLite default database URL

The system SHALL support SQLite as the default local database engine using Tortoise ORM database URLs.

#### Scenario: Relative SQLite database URL
- **WHEN** `TRADER_DB` is set to a relative SQLite URL such as `sqlite://data/trader.db`
- **THEN** the system SHALL use that SQLite file as the primary database

#### Scenario: Absolute SQLite database URL
- **WHEN** `TRADER_DB` is set to an absolute SQLite URL such as `sqlite:///Users/example/data/trader.db`
- **THEN** the system SHALL use that absolute SQLite file as the primary database

#### Scenario: PostgreSQL URL remains a future-compatible target
- **WHEN** `TRADER_DB` is set to a supported PostgreSQL Tortoise URL
- **THEN** repository code SHALL avoid MongoDB-specific assumptions and SHALL keep backend-specific behavior inside the database layer

### Requirement: Relational kline schema

The system SHALL store historical klines in a relational table keyed by exchange, symbol, interval, and open time.

#### Scenario: Kline uniqueness
- **WHEN** two kline records have the same exchange, symbol, interval, and open time
- **THEN** the database SHALL treat them as the same logical kline and SHALL prevent duplicate rows for that key

#### Scenario: Kline range query
- **WHEN** code requests klines for an exchange, symbol, interval, start time, and end time
- **THEN** the repository SHALL return matching klines ordered by ascending open time

#### Scenario: Raw source payload is preserved
- **WHEN** kline data is ingested from an exchange or other data source
- **THEN** the system SHALL persist common kline fields in typed columns and SHALL preserve the source payload in a raw JSON/text field when available

### Requirement: Task state relational storage

The system SHALL persist task runtime state through Tortoise-backed relational storage.

#### Scenario: Task state upsert
- **WHEN** task state is saved for an existing task identifier
- **THEN** the repository SHALL update the existing task state instead of inserting a duplicate task

#### Scenario: Task state retrieval
- **WHEN** code requests a task by task identifier
- **THEN** the repository SHALL return the saved task state or `None` when no such task exists

### Requirement: Availability metadata relational storage

The system SHALL persist market-data availability metadata through Tortoise-backed relational storage.

#### Scenario: Availability uniqueness
- **WHEN** availability metadata is saved for the same exchange, symbol, and interval
- **THEN** the database SHALL maintain one logical availability record for that market stream

#### Scenario: Earliest known open time lookup
- **WHEN** data preparation checks a market stream's known earliest available kline
- **THEN** the repository SHALL return the saved `earliest_known_open_time` or `None` when no metadata exists

### Requirement: Explicit database migrations

The system SHALL manage schema changes through explicit Tortoise migration commands rather than runtime schema mutation.

#### Scenario: Generate migration after model change
- **WHEN** a developer changes a Tortoise model
- **THEN** the project SHALL provide a documented command path to generate a migration file without manually writing SQL

#### Scenario: Apply pending migrations
- **WHEN** a database has pending migrations
- **THEN** the project SHALL provide a documented command path to apply those migrations before running database-backed workflows

#### Scenario: Backtest does not auto-migrate schema
- **WHEN** a backtest or optimization run starts
- **THEN** it MUST NOT silently alter the database schema as part of normal execution
