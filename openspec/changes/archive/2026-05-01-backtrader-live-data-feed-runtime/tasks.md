## 1. Live Feed Foundation

- [x] 1.1 Add failing tests for a Backtrader live K-line feed declaring `islive() == True`, delivering one closed bar per `_load()`, returning `None` while alive with no data, and returning `False` after stop.
- [x] 1.2 Implement the live K-line feed primitive with queue-based closed-bar input, qcheck-aware waiting, status notifications, duplicate suppression, and clean shutdown.
- [x] 1.3 Add tests proving open K-line updates are not accepted into the Backtrader feed and closed K-line updates are converted into correct Backtrader OHLCV lines.

## 2. Persistent Backtrader Runtime

- [x] 2.1 Add failing tests for a persistent live `Cerebro` runner that warms a strategy with historical candles and then advances the same strategy instance on later live bars.
- [x] 2.2 Implement the persistent live runner around one `Cerebro`, one strategy instance, the live feed, broker cash/commission setup, strategy params, and managed thread/executor shutdown.
- [x] 2.3 Add tests proving realtime closed candles do not create new `Node` or `Cerebro` instances and instead advance the persistent runner once per unique closed candle.

## 3. Warmup And Notification Flow

- [x] 3.1 Add failing tests proving startup warmup/backfill operations send manual notifications for development validation.
- [x] 3.2 Add failing tests proving LIVE incremental operations do send manual notifications and LIVE no-op bars do not resend already-sent operations.
- [x] 3.3 Implement feed status tracking and notification flow so manual_notify emits from persistent-feed incremental events.
- [x] 3.4 Add stable live event identity and notification dedupe keyed by task, market, side, time, and signal event id when available.

## 4. Incremental Strategy Event Capture

- [x] 4.1 Add tests for capturing newly produced strategy operations from a persistent live strategy without relying on full-window `TraderResult` replay.
- [x] 4.2 Implement an incremental live event sink or analyzer path that exposes new operations, risk references, signal metadata, and lifecycle diagnostics to the runtime.
- [x] 4.3 Preserve existing backtest `Node.start()` and `TraderResult` behavior unchanged.

## 5. TraderTask And Stream Integration

- [x] 5.1 Add tests for `TraderTask.start_realtime` using the Backtrader live data feed runtime for `live_data_mode = realtime`.
- [x] 5.2 Integrate startup REST backfill into the live feed warmup path with the existing 500-candle cap and truncated-gap diagnostics.
- [x] 5.3 Integrate Binance WebSocket closed updates into the feed and keep open updates dashboard-only.
- [x] 5.4 Integrate reconnect catch-up so missing closed candles are enqueued chronologically through the same feed.
- [x] 5.5 Mark or isolate the replay-on-window realtime runtime as legacy fallback rather than the default realtime path.

## 6. Dashboard And API Compatibility

- [x] 6.1 Add tests proving existing live dashboard event schemas still receive kline updates, strategy execution summaries, signal markers, risk overlays, and notification events from the persistent runtime.
- [x] 6.2 Adapt dashboard event builders or runtime publishers to consume incremental live events without requiring a full-window strategy result.
- [x] 6.3 Ensure runtime status exposes feed phase, latest delivered closed candle, warmup completion, LIVE transition, disconnect/reconnect state, and legacy fallback usage when applicable.

## 7. Verification And Documentation

- [x] 7.1 Run targeted automated tests for live feed, persistent runtime, manual notifications, stream integration, and dashboard API contracts.
- [x] 7.2 Run OpenSpec validation for `backtrader-live-data-feed-runtime`.
- [x] 7.3 Update README live-mode documentation to describe the Backtrader live feed runtime, warmup notification policy, and manual_notify semantics.
- [x] 7.4 Record credential-gated smoke validation steps for Binance WebSocket and manual email after automated tests pass.
