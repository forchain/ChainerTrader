## ADDED Requirements

### Requirement: CSV and database data sources remain independent

The system SHALL choose the backtest data source from task configuration: tasks with `csv` SHALL read CSV files, and tasks without `csv` SHALL read from the configured database when a database is available.

#### Scenario: CSV task reads CSV
- **WHEN** a backtest task config includes `csv`
- **THEN** the task SHALL construct its Backtrader data feed from that CSV file

#### Scenario: Database task reads database
- **WHEN** a backtest task config omits `csv` and database configuration is available
- **THEN** the task SHALL load kline data directly from the database for the requested symbol, interval, and time range

#### Scenario: Database task does not export temporary CSV
- **WHEN** a database-backed backtest prepares data successfully
- **THEN** the system SHALL NOT require an intermediate CSV export before executing Backtrader

### Requirement: Database-backed Backtrader feed construction

The system SHALL construct synchronous Backtrader feeds from database-loaded kline objects.

#### Scenario: Klines loaded before Backtrader starts
- **WHEN** a database-backed backtest starts execution
- **THEN** the system SHALL query the required kline rows before invoking the synchronous Backtrader runtime

#### Scenario: Feed load does not await database calls
- **WHEN** Backtrader calls the data feed load method
- **THEN** the feed SHALL read from already-loaded kline objects and SHALL NOT await Tortoise ORM queries inside the feed load path

#### Scenario: Empty database result fails clearly
- **WHEN** the database contains no klines for the requested backtest range
- **THEN** the task SHALL fail with a clear data-unavailable error instead of running a backtest with an empty feed

### Requirement: Database coverage preparation uses interval-aligned edges

The system SHALL normalize database-backed data preparation ranges by strategy interval and fill only missing edge ranges.

#### Scenario: Requested start precedes local first kline
- **WHEN** the requested start time is earlier than the local first kline open time
- **THEN** data preparation SHALL download only the range from the requested start through the interval immediately before the local first kline

#### Scenario: Requested end follows local last kline
- **WHEN** the requested end time is later than the local last kline open time
- **THEN** data preparation SHALL download only the range from the interval immediately after the local last kline through the requested end

#### Scenario: Requested range is inside local edges
- **WHEN** the requested start and end are within the local first and last kline open times
- **THEN** data preparation SHALL avoid remote download for that request

#### Scenario: Internal gaps are not scanned in normal preparation
- **WHEN** local data has first and last klines covering the requested range but has missing bars in the middle
- **THEN** normal backtest and optimization preparation SHALL NOT scan or repair those internal gaps

### Requirement: Optimization samples support database sources

The system SHALL allow optimization worker sample specifications to describe database-backed data sources without requiring a CSV path.

#### Scenario: Worker receives database source descriptor
- **WHEN** an optimization sample is backed by the database
- **THEN** the worker specification SHALL include enough information to initialize the database connection and query exchange, symbol, interval, start time, and end time

#### Scenario: Worker loads database klines before sample execution
- **WHEN** a worker executes a database-backed sample
- **THEN** it SHALL load the required klines through the database repository before running the synchronous Backtrader sample

#### Scenario: Multiple samples reuse logical dataset identity
- **WHEN** multiple optimization samples share the same exchange, symbol, interval, and normalized time range
- **THEN** reporting and scheduling SHALL be able to represent that shared logical dataset without depending on a filesystem CSV path

### Requirement: Dataset metadata is logical rather than file-path-only

The system SHALL identify database-backed datasets by logical source metadata instead of requiring `dataset_ref.path`.

#### Scenario: Database report context includes dataset identity
- **WHEN** a database-backed backtest report is generated
- **THEN** the report context SHALL include a stable dataset identifier derived from exchange, symbol, interval, and normalized range

#### Scenario: CSV report context can still include path metadata
- **WHEN** a CSV-backed backtest report is generated
- **THEN** the report context MAY include the CSV path as source metadata
