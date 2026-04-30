## 1. Runtime Foundations

- [x] 1.1 Add pure backfill planning logic that computes missing closed candles from latest DB kline, current time, interval, and the 500-candle cap.
- [x] 1.2 Add tests for no-history startup, 100-candle gap startup, over-500-candle truncated startup, and no-gap startup.
- [x] 1.3 Define a normalized realtime `KlineUpdate` model with exchange, symbol, interval, open time, close time, OHLCV, event time, and closed flag.
- [x] 1.4 Add Binance kline payload normalization for WebSocket messages, including validation of the `k.x` closed-candle flag.
- [x] 1.5 Add tests for open kline payloads, closed kline payloads, malformed payloads, duplicate payloads, and out-of-order payload handling.

## 2. Market Stream Hub

- [x] 2.1 Implement a market stream hub keyed by exchange, symbol, and interval.
- [x] 2.2 Add subscription fan-out so multiple live strategy runtimes can consume the same market stream without opening duplicate WebSocket subscriptions.
- [x] 2.3 Implement Binance Spot WebSocket kline subscription using the installed Binance SDK or a thin adapter compatible with the SDK's async stream API.
- [x] 2.4 Add reconnect handling that marks stream status, performs REST catch-up from the latest persisted closed candle, and resumes WebSocket consumption.
- [x] 2.5 Add tests for shared subscription reuse, independent subscriptions for different markets, reconnect catch-up, and subscriber cleanup.

## 3. Live Strategy Runtime

- [x] 3.1 Add a realtime live runtime that performs startup REST backfill, persists closed candles, and records startup diagnostics.
- [x] 3.2 Execute the strategy once after startup backfill using the latest 500 closed candles.
- [x] 3.3 Route open WebSocket candle updates to dashboard consumers without strategy execution or final DB persistence.
- [x] 3.4 Route closed WebSocket candle updates through DB persistence, latest-500 window loading, strategy execution, notification handling, and dashboard publication.
- [x] 3.5 Preserve manual_notify semantics so realtime runtime signal handling never calls exchange order placement.
- [x] 3.6 Add tests for startup execution, open-candle non-execution, closed-candle execution, DB persistence dedupe, and manual_notify no-order behavior.

## 4. Strategy Diagnostics And Events

- [x] 4.1 Define structured dashboard events for runtime status, kline updates, strategy execution summaries, signal markers, risk overlays, divergence metadata, and notification results.
- [x] 4.2 Map Chainer framework stop-loss, take-profit, risk/reward, and breakeven movement state into dashboard risk overlay events.
- [x] 4.3 Map MACD triple divergence signal metadata and divergence legs into chart-diagnostic events with stable event ids.
- [x] 4.4 Add tests that generated dashboard events contain enough fields for candle rendering, signal lookup, stop/take-profit lines, breakeven movement, and MACD divergence diagnosis.

## 5. Notification Integration

- [x] 5.1 Ensure realtime manual_notify emails are emitted only from closed-candle strategy executions.
- [x] 5.2 Include dashboard correlation fields in manual_notify events and emails, such as strategy id, signal event id, symbol, interval, signal time, signal price, and risk references.
- [x] 5.3 Add tests proving open-candle updates do not send emails and closed-candle signal operations do send manual_notify emails.
- [x] 5.4 Add tests proving realtime manual_notify emails label stop-loss, take-profit, and breakeven values as local strategy references rather than exchange-submitted orders.

## 6. Web API And Realtime Transport

- [x] 6.1 Add Web-mode endpoints for listing live strategies and loading a selected strategy's initial chart snapshot.
- [x] 6.2 Add a server-to-dashboard realtime transport using WebSocket or SSE for kline updates, strategy events, risk overlays, and runtime status.
- [x] 6.3 Define stable JSON schemas or typed response builders for initial snapshots and realtime update events.
- [x] 6.4 Add tests for live strategy list responses, initial latest-500 snapshot payloads, realtime event serialization, and client subscription filtering by strategy id.

## 7. Dashboard Frontend

- [x] 7.1 Add TradingView Lightweight Charts integration or document and implement the selected alternative if implementation research rejects Lightweight Charts.
- [x] 7.2 Build the live strategy monitor dashboard with a strategy sidebar or tab workspace, active chart, status summary, parameter panel, and diagnostic event panel.
- [x] 7.3 Render initial latest-500 candlesticks and incrementally update candles from realtime Kline update events.
- [x] 7.4 Render signal markers, MACD divergence diagnostics, stop-loss lines, take-profit lines, and breakeven stop movement overlays with layer toggles.
- [x] 7.5 Verify with browser-based tests or Playwright that multiple strategies are navigable without flat chart tiling and that candle updates do not break layout on desktop and mobile widths.

## 8. Demo Task And Smoke Validation

- [x] 8.1 Add a BTCUSDT 1-minute MACD triple divergence demo live task under `configs/tasks/live/` using manual_notify mode.
- [x] 8.2 Ensure the demo task uses framework parameters for stop-loss, take-profit, and optional breakeven so the dashboard can show those overlays.
- [x] 8.3 Add a synthetic end-to-end test path that drives the realtime runtime with fake kline updates and verifies dashboard events plus manual_notify output.
- [x] 8.4 Add a credential-gated Binance WebSocket smoke check that is skipped with a concrete prerequisite message when exchange connectivity is unavailable.
- [x] 8.5 Add a credential-gated real email smoke check that is skipped with a concrete prerequisite message when SMTP or recipient configuration is unavailable.

## 9. Documentation And Verification

- [x] 9.1 Update README or user-facing docs for Web dashboard access, live runtime configuration, demo task usage, and any new frontend dependency or build step.
- [x] 9.2 Run the relevant automated unit and integration tests for runtime, notifications, API contracts, and frontend behavior.
- [x] 9.3 Run OpenSpec validation for `realtime-live-trading-dashboard`.
- [x] 9.4 Record manual validation steps for the BTCUSDT 1m demo, including what chart fields, overlays, emails, and runtime diagnostics the operator should inspect.
