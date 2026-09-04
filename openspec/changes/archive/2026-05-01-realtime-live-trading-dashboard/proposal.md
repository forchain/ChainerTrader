## Why

Live strategy execution currently relies on periodic REST polling and does not expose enough realtime market state, strategy lifecycle state, or risk-management diagnostics for manual validation. The next live-mode iteration needs a WebSocket-driven runtime plus a chart dashboard so multiple strategies can run concurrently while the operator can verify candles, signals, stops, take-profit references, and breakeven movement visually.

## What Changes

- Add a realtime live strategy runtime that performs an initial REST backfill of at most 500 missing candles, runs the strategy once after the backfill, and then consumes Binance kline WebSocket updates.
- Persist and publish open and closed kline updates, but only execute strategies on completed candles.
- Support multiple concurrent live strategies while sharing market streams for identical exchange/symbol/interval subscriptions.
- Add a Web-mode monitoring dashboard for live strategies using TradingView Lightweight Charts unless implementation research finds a stronger fit during implementation.
- Show the latest 500 candles initially, update the active candle in realtime, append closed candles, and render strategy diagnostics such as signal markers, divergence legs, stop-loss lines, take-profit lines, breakeven stop movements, and framework parameter state.
- Provide an end-to-end BTCUSDT 1-minute MACD triple divergence demo live task for manual validation in `manual_notify` mode.
- Keep automatic exchange execution out of scope for this change; signal emails and chart diagnostics are the primary validation path.

## Capabilities

### New Capabilities
- `realtime-live-strategy-runtime`: Defines initial backfill, WebSocket kline ingestion, closed-candle strategy execution, multi-strategy stream sharing, and demo live task behavior.
- `live-strategy-monitor-dashboard`: Defines the Web monitoring dashboard, chart data contract, realtime candle rendering, multi-strategy navigation, and diagnostic overlays.

### Modified Capabilities
- `manual-live-trade-notifications`: Clarify that realtime live-mode signal notifications are emitted from closed-candle strategy executions and may include chart-diagnostic risk references without implying exchange order placement.

## Impact

- Affected code areas:
  - `src/trader/task/trader_task.py`
  - `src/trader/task/update_klines_task.py`
  - `src/trader/exchange/binance/`
  - `src/trader/database/kline.py`
  - `src/trader/strategy/node.py`
  - `src/trader/strategy/base_strategy.py`
  - `src/trader/strategy/macd_triple_divergence.py`
  - `src/trader/notify/`
  - `src/trader/rpc/`, templates, and static assets
  - `configs/tasks/live/`
  - tests covering runtime backfill, WebSocket payload normalization, closed-candle gating, stream fan-out, notification emission, and dashboard contracts
- External systems:
  - Binance REST klines for initial backfill.
  - Binance Spot WebSocket kline streams for realtime updates.
  - Existing email notification providers for manual signal notifications.
- Frontend dependency impact:
  - The dashboard may introduce a browser-side chart dependency such as TradingView Lightweight Charts and, if justified, a lightweight frontend build step.
