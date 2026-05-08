## Why

Realtime live trading currently has a safe `manual_notify` path for strategy validation, while automatic exchange execution exists only in the older polling live path. Operators need a staged path from realtime simulated execution to small real orders and finally full automatic execution, without jumping directly from email recommendations to unrestricted live trading.

## What Changes

- Add explicit staged realtime live execution modes:
  - `paper_auto`: automatically converts realtime strategy operations into simulated order executions and paper account state updates without calling exchange order APIs.
  - `small_live_auto`: places real exchange orders with a fixed per-order notional cap such as `live_trade_max_notional`.
  - `full_live_auto`: places real exchange orders using the task or strategy sizing policy.
- Keep `manual_notify` behavior unchanged: it continues to send actionable recommendations and MUST NOT place orders.
- Add mode-level order safety controls for realtime automatic execution, including explicit opt-in, invalid price/quantity rejection, duplicate operation prevention, position/balance checks, and order result recording.
- Add guarded Binance cross-margin short execution for real automatic modes. Real `SHORT` execution MUST remain disabled unless `live_short_execution` explicitly selects `margin_cross`.
- Leave Binance isolated margin and Binance futures out of scope for the first implementation, but keep the execution boundary extensible for those future modes.

## Capabilities

### New Capabilities
- `staged-live-auto-execution`: Defines realtime `paper_auto`, `small_live_auto`, and `full_live_auto` execution semantics and their relationship to `manual_notify`.
- `live-auto-order-safety`: Defines safety requirements for automatic realtime order routing, sizing caps, duplicate prevention, validation, recording, and failure handling.
- `live-cross-margin-short-execution`: Defines guarded Binance cross-margin short execution for real automatic live modes.

### Modified Capabilities
- `manual-live-trade-notifications`: Clarify that `manual_notify` remains the no-order safety baseline when staged automatic execution modes are added.

## Impact

- Affected code areas:
  - `src/trader/task/trader_task.py`
  - `src/trader/task/task_config.py`
  - `src/trader/live/backtrader_runtime.py`
  - `src/trader/live/dashboard.py`
  - `src/trader/live/monitor.py`
  - `src/trader/exchange/binance/exchange.py`
  - `src/trader/exchange/binance/margin.py`
  - `src/trader/notify/`
  - `src/trader/strategy/trader_result.py`
  - `configs/tasks/live/`
  - tests covering staged mode routing, simulated execution, real order safety gates, cross-margin short gating, and unchanged manual notification behavior
- External systems:
  - Binance Spot REST order API for real long-side orders.
  - Binance Cross Margin order API for explicitly enabled real short-side orders.
  - Existing realtime Binance kline WebSocket and REST backfill flows remain the market data source.
- Operational impact:
  - Real order placement requires explicit task configuration and valid exchange credentials.
  - Cross-margin short execution requires explicit operator opt-in and margin account readiness.
