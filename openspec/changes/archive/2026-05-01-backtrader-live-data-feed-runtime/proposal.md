## Why

The current realtime live runtime reruns a fresh Backtrader `Node` over the latest candle window every time a closed K-line arrives. That does not match Backtrader's live trading model and creates fragile state behavior around duplicated signals, local manual positions, stop-loss handling, and strategy lifecycle.

Backtrader live trading should keep one `Cerebro` and one strategy instance alive while a live data feed advances the strategy one bar at a time. This change moves ChainerTrader's realtime live execution to that model.

## What Changes

- Add a Backtrader-compatible live K-line data feed for Binance-backed realtime tasks.
- Replace replay-on-window realtime strategy execution with a persistent `Cerebro` runtime per live task.
- Feed initial REST backfill and reconnect catch-up candles through the same data feed in chronological order.
- Route startup warmup strategy events through the same dashboard and manual notification path as live candles for development validation.
- Preserve open-candle dashboard rendering while sending only closed candles into Backtrader strategy execution.
- Keep automatic exchange order placement out of scope; first implementation continues to support `manual_notify` live validation.
- Deprecate the replay-on-window realtime execution path for configured realtime live tasks once the new feed runtime is in place.

## Capabilities

### New Capabilities
- `backtrader-live-data-feed-runtime`: Defines the persistent Backtrader live data feed runtime, warmup/live status transitions, closed-candle advancement, reconnect catch-up, and runtime diagnostics.

### Modified Capabilities
- `manual-live-trade-notifications`: Clarifies that realtime manual notifications are emitted from incremental strategy events delivered through the persistent live feed, including startup warmup during development validation, not from full-window reruns.

## Impact

- Affected code areas:
  - `src/trader/live/`
  - `src/trader/task/trader_task.py`
  - `src/trader/strategy/node.py`
  - `src/trader/strategy/base_strategy.py`
  - `src/trader/strategy/trader_result.py`
  - `src/trader/utils/operation_state.py`
  - `src/trader/notify/`
  - `src/trader/rpc/api/live.py`
  - tests covering live feed advancement, warmup notification behavior, reconnect catch-up, manual notification behavior, and dashboard event contracts
- External systems:
  - Binance REST klines for bounded warmup and reconnect catch-up.
  - Binance Spot Kline WebSocket streams for live closed/open candle updates.
  - Existing email providers for manual notifications.
- Compatibility:
  - Backtest behavior should remain unchanged.
  - Existing realtime dashboard contracts should remain compatible, but execution event timing will shift from window rerun results to incremental strategy events.
