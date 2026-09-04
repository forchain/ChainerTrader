## Context

The current live `TRADER` path downloads a recent REST range in a loop, builds a fresh Backtrader `Node`, processes generated operations, and then sleeps until the next K-line boundary. This works as a conservative polling loop, but it cannot distinguish open-candle updates from closed-candle execution, cannot share realtime market streams across multiple strategies, and gives the operator no visual way to diagnose whether candles, signal events, stop-loss references, take-profit references, or breakeven stop movements match TradingView-style inspection.

Existing strategy architecture already keeps the common trade lifecycle in the Chainer framework. `BaseStrategy` owns framework-level risk parameters such as ATR stop loss, risk/reward take-profit, and breakeven stop movement. `MacdTripleDivergenceStrategy` already emits structured signal metadata and divergence event details. The implementation should preserve that boundary: strategies produce signals and metadata; runtime and dashboard layers consume lifecycle outputs.

Context7 research supports using TradingView Lightweight Charts for the dashboard because it provides candlestick series, incremental `series.update(...)` behavior, markers, price lines, and pane/series support for diagnostic overlays. Binance Spot WebSocket research confirms kline streams use `<symbol>@kline_<interval>` and expose the `k.x` closed-candle flag, which should be the execution gate.

## Goals / Non-Goals

**Goals:**
- Replace live REST polling with a runtime that performs bounded REST backfill first, then consumes Binance kline WebSocket updates.
- Keep at most the latest 500 candles as the initial execution/chart window for the requested market interval, while fetching fewer when the database gap is smaller.
- Execute the strategy once after initial backfill and then only when a closed candle arrives.
- Publish every realtime candle update to Web clients, including open candles that must not trigger strategy execution.
- Run multiple live strategies concurrently and share a single exchange stream for duplicate exchange/symbol/interval subscriptions.
- Add a Web dashboard that is useful for diagnosis: strategy selector, active chart, live status, last execution details, framework parameters, signals, stops, take-profit references, and breakeven movement.
- Provide a BTCUSDT 1-minute MACD triple divergence manual-notify demo task for high-frequency manual validation.
- Cover pure runtime and dashboard contracts with automated tests, and label real exchange/email checks as credential-gated smoke/manual validation.

**Non-Goals:**
- Implement automatic exchange order placement, fill reconciliation, account-balance streaming, or exchange-side stop/OCO/bracket orders.
- Replace the Chainer framework lifecycle with strategy-local notification or risk-management logic.
- Guarantee that local manual-mode state equals the user's real exchange account after external manual trades.
- Use the closed-source TradingView Charting Library unless the project already has a valid license and chooses to add the required datafeed integration in a later change.

## Decisions

### Decision 1: Introduce a shared market stream hub

Add a market stream component keyed by `(exchange, symbol, interval)` that owns the Binance WebSocket connection, normalizes kline payloads, tracks connection status, and fans out updates to subscribed live strategy runtimes and Web clients.

Alternatives considered:
- One WebSocket per strategy: simpler locally but wasteful and harder to manage when several strategies watch the same market.
- Keep REST polling: avoids WebSocket lifecycle complexity but misses realtime open-candle rendering and creates unnecessary REST load.

### Decision 2: Separate open-candle rendering from closed-candle execution

Normalize each Binance kline message into a local `KlineUpdate` with OHLCV fields, open/close times, event time, and `is_closed`. The dashboard receives every update. The strategy runtime persists and executes only closed candles, with dedupe by candle open time.

Alternatives considered:
- Execute strategy on every open-candle update: this would create unstable signals because Backtrader would see a candle before its final close.
- Render only closed candles: easier but fails the operator workflow because the current active candle would not match live exchange movement.

### Decision 3: Use bounded REST backfill before subscribing to runtime execution

On live start, inspect the latest stored DB candle for the task market. If none exists, fetch the latest 500 candles. If a gap exists, fetch the missing closed candles up to 500. If more than 500 are missing, fetch the most recent 500 and mark the runtime status with a truncated-gap diagnostic. After persistence, run the strategy once on the latest 500 closed candles.

Alternatives considered:
- Always fetch 500 candles: safe but wastes calls and obscures whether DB continuity is healthy.
- Fetch the whole missing range: better for archival completeness but can delay live start and exceeds the user's requested bounded startup behavior.

### Decision 4: Keep first implementation as replay-on-window execution

For the first realtime version, each closed candle execution should run the existing `Node` over the latest 500 closed candles plus current manual/local runtime state as needed. This preserves current Backtrader integration and minimizes changes to strategy internals. The runtime should emit enough execution diagnostics to make later incremental-feed optimization possible.

Alternatives considered:
- Maintain a continuously running Backtrader live feed: potentially more efficient but larger architectural risk and harder to validate in the first WebSocket dashboard iteration.

### Decision 5: Use TradingView Lightweight Charts with a diagnostic event contract

The Web dashboard should use Lightweight Charts for the initial 500-candle set and incremental candle updates. Server-side events should expose chart-ready candles plus overlays: signal markers, divergence legs, stop-loss price lines, take-profit price lines, breakeven stop movement segments, and execution summaries.

Alternatives considered:
- Closed-source TradingView Charting Library: closer to TradingView product behavior but licensing and datafeed integration are heavier than needed for this diagnostic dashboard.
- Plotly/ECharts: strong general charting, but less aligned with the user's TradingView workflow and less direct for financial candle interactions.

### Decision 6: Prefer strategy tabs with a management sidebar

The dashboard should not tile every chart. It should present a strategy list/sidebar with status filters and a tabbed active workspace. This keeps many concurrent strategies manageable while allowing quick switching between BTC 1m, ETH 1d, and later task variants.

Alternatives considered:
- Flat grid of all charts: poor readability and heavy browser rendering cost.
- One page per strategy only: simple routing but slower for active monitoring and comparison.

## Risks / Trade-offs

- WebSocket disconnects or missed messages -> Track connection status, reconnect, and run a bounded REST catch-up from the latest persisted closed candle before resuming execution.
- Duplicate or out-of-order kline messages -> Dedupe by `(symbol, interval, open_time)` and ignore older open-candle revisions after a closed candle has been persisted.
- Replaying `Node` every minute can be CPU-heavy with many strategies -> Start with the 500-candle window for correctness and add metrics so incremental execution can be prioritized if needed.
- Chart overlays can become noisy -> Provide layer toggles for signals, divergence legs, stop-loss, take-profit, breakeven, and framework params.
- Manual-mode local state can diverge from real exchange state -> Keep email/dashboard wording explicit that events are local strategy recommendations, not exchange fill confirmations.
- Real Binance and SMTP behavior cannot be fully automated in CI -> Unit-test normalization, gating, and contracts; keep credential-gated smoke tests for live exchange and email paths.

## Migration Plan

1. Add pure runtime primitives and tests: backfill gap calculation, Binance kline normalization, closed-candle gating, and stream fan-out.
2. Integrate the runtime into live trader task mode while preserving existing behavior behind configuration or a legacy fallback during implementation.
3. Add dashboard API/WebSocket or SSE contracts and tests with synthetic strategy events.
4. Add the Web dashboard assets and verify rendering with local test data before connecting it to live streams.
5. Add the BTCUSDT 1-minute MACD triple divergence demo task under `configs/tasks/live/`.
6. Add credential-gated smoke paths for Binance WebSocket and real email, clearly skipped when prerequisites are missing.
7. Update user-facing README/deployment docs if Web dashboard access, live-mode operation, dependencies, or configuration change.

Rollback strategy: keep the old live polling path available until the WebSocket runtime has automated coverage and manual smoke validation. If the new runtime fails in production, disable the realtime runtime flag and fall back to the existing polling behavior.

## Open Questions

- Should the dashboard transport use WebSocket for both server-to-client updates and later client commands, or SSE for one-way updates plus HTTP for commands?
- Should open-candle updates be stored only in memory, or persisted as temporary records separate from closed DB K-lines?
- Which exact execution-mode flag should select the WebSocket runtime versus the legacy polling path during rollout?
- Should future exchange execution reuse the same event stream for fill/account overlays, or remain a separate change after manual validation?
