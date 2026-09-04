# Database Design

This document describes ChainerTrader's MongoDB storage model from a structural point of view.

## Overview

ChainerTrader uses MongoDB as its primary persistent store for:

- historical kline data
- task runtime state
- market-data availability metadata

The design is intentionally simple. It does not use relational joins. Relationships are established through symbol, interval, exchange, and task configuration.

## Collections

### `klines-<symbol-interval>`

One collection per market stream, for example:

- `klines-BTCUSDT-1h`
- `klines-ETHUSDT-4h`

Purpose:

- persistent historical price storage
- source of database-backed backtests
- source of optimization dataset preparation
- cache for update/download tasks

Fields:

- `open_time`: primary key, candle open timestamp
- `open_datetime`: human-readable open timestamp
- `open`: open price
- `high`: high price
- `low`: low price
- `close`: close price
- `close_time`: close timestamp
- `close_datetime`: human-readable close timestamp
- `volume`: base-asset volume
- `vol_quote`: quote-asset volume
- `trades`: number of trades in the candle
- `vol_taker_base`: taker buy base volume
- `vol_taker_quote`: taker buy quote volume
- `ignore`: exchange compatibility field

Indexes:

- unique index on `open_time`

### `tasks`

Purpose:

- persist task execution state
- expose runtime task information to the admin/API layer
- store task-level summary configuration and result metadata

Fields:

- `task_id`: primary key
- `state`: task state, such as `READY`, `RUNNING`, `DONE`
- `name`: task display name
- `start_time`: task start time
- `commission`: configured commission
- `strategy_start_time`: strategy window start
- `strategy_end_time`: strategy window end
- `initial_cash`: initial cash value
- `config_json`: serialized task configuration snapshot
- `tret`: serialized trader/backtest result payload

Indexes:

- unique index on `task_id`

### `availability`

Purpose:

- record known market-data coverage
- support dataset preparation
- avoid unnecessary repeated backward-fill work

Fields:

- `exchange`: exchange name
- `symbol`: market symbol
- `interval`: candle interval
- `earliest_known_open_time`: earliest known available candle open time
- `updated_at`: metadata update timestamp
- `source`: reason/source of the latest availability update

Indexes:

- unique composite index on `(exchange, symbol, interval)`

## Relationships

```text
availability
    |
    | (exchange, symbol, interval)
    v
klines-<symbol-interval>
    |
    | referenced indirectly by
    v
tasks
```

Relationship rules:

- `availability` describes what data coverage exists for a market stream
- `klines-<symbol-interval>` stores the actual candles for that market stream
- `tasks` references that data indirectly through the task's symbol, interval, and time-window configuration

There is no database-level foreign key. Coordination happens in application logic.

## Design Notes

- The model favors append/query simplicity over normalization
- Historical data is partitioned by market stream for straightforward range scans
- Task state is centralized for runtime monitoring
- Availability metadata is kept separate from the raw kline store so coverage checks stay cheap
