## Context

The previous realtime live implementation deliberately chose replay-on-window execution: after startup backfill and after every closed WebSocket candle, the runtime loads the latest 500 closed candles, creates a new Backtrader `Node`, and reruns the strategy over that window. That choice preserved existing backtest wiring, but it violates the live Backtrader execution model. Backtrader live integrations keep `Cerebro` running and let a live data feed advance the strategy one bar at a time.

This mismatch is now the primary source of live-mode bugs. Replaying the full window repeatedly makes every strategy run reconstruct historical operations, so the runtime needs ad hoc operation dedupe, local position restoration, stop state reconstruction, and notification gating. Those patches are symptoms of the wrong ownership boundary.

The new boundary should be:

```text
Binance REST backfill / catch-up / WebSocket closed bars
                    |
                    v
          Backtrader live K-line feed
          islive=True, qcheck enabled
                    |
                    v
       one persistent Cerebro + strategy
                    |
                    v
    incremental operations, dashboard events, manual_notify
```

Backtrader feed semantics are important:
- a live feed returns `islive() == True`, which disables `preload` and `runonce`;
- `_load()` returns `True` when one bar is delivered, `None` when no bar is currently available but the feed remains alive, and `False` when the feed is done;
- `put_notification()` can publish `DELAYED`, `LIVE`, `DISCONNECTED`, and related data statuses to strategies through `notify_data`;
- `qcheck` lets Cerebro wake periodically while waiting for live feed messages.

## Goals / Non-Goals

**Goals:**
- Run one persistent Backtrader `Cerebro` and one strategy instance per realtime live task.
- Implement a live data feed that warms the strategy with historical closed candles, then switches to `LIVE` for incremental closed candles.
- Ensure each closed K-line advances strategy execution at most once.
- Keep open K-line updates out of strategy execution while preserving dashboard rendering.
- Feed reconnect catch-up candles through the same live feed in chronological order.
- Emit manual notifications for strategy events delivered through the persistent feed, including startup warmup events during development validation.
- Preserve current dashboard and manual-notify user-facing behavior where possible.
- Keep backtests and non-realtime live polling behavior unchanged unless explicitly migrated.

**Non-Goals:**
- Implement a full Backtrader Binance Store/Broker with automatic exchange order placement.
- Add exchange-side bracket, stop, OCO, margin, or fill reconciliation behavior.
- Guarantee local manual state matches external manual trades placed by the user.
- Rewrite strategy signal logic or move framework risk logic into strategy-local workarounds.
- Replace the dashboard frontend.

## Decisions

### Decision 1: Implement a project-owned Backtrader live data feed first

Create a `bt.feed.DataBase` subclass, likely under `src/trader/live/`, that accepts normalized `Kline`/`KlineUpdate` objects and writes OHLCV values into Backtrader lines from `_load()`.

The feed should own a thread-safe or async-bridged queue:
- startup backfill candles are enqueued before Cerebro starts;
- WebSocket closed candles and reconnect catch-up candles are enqueued while Cerebro is running;
- `_load()` blocks up to Backtrader's `_qcheck` interval and returns `None` when no candle is available.

Alternatives considered:
- Full Backtrader Store/Broker immediately: closer to official integrations, but too large for this correction and unnecessary while execution stays `manual_notify`.
- Keep replay-on-window and harden dedupe/state: lower immediate code churn, but preserves the architectural defect.

### Decision 2: Treat startup backfill as feed warmup, but publish validation events

Startup backfill should bring the persistent strategy instance to the latest closed candle through the same Backtrader feed path. During development validation, operations produced while processing this warmup segment should use the same dashboard marker, risk overlay, strategy execution, and `manual_notify` path as later live candles. This makes a known BTC 1d signal visible immediately after server startup and gives operators a deterministic smoke check.

This means warmup is not a separate replay-on-window path. It is normal incremental Backtrader execution before the feed reaches `LIVE`. If production needs quieter startup behavior later, that should be a separate policy switch rather than changing the feed model.

Alternatives considered:
- Suppress startup notifications from warmup: quieter for production, but makes development validation much harder because a known startup signal would not appear in email or dashboard checks.
- Skip warmup entirely and start only at the next live candle: avoids historical notifications but breaks indicator readiness and strategy state.

### Decision 3: Keep dashboard open-candle handling outside Backtrader execution

Open Binance kline updates continue to publish dashboard candle updates only. The live feed receives closed candles only. This preserves deterministic Backtrader strategy semantics and avoids intrabar signal instability.

Alternatives considered:
- Replay open candle updates into Backtrader: closer to tick-by-tick live operation, but existing strategies and risk logic are written around closed-candle signals.
- Persist open candles as DB records: increases database complexity and risks mixing provisional candles with finalized historical data.

### Decision 4: Preserve the market stream hub as the exchange transport

The existing `MarketStreamHub` can remain the shared WebSocket fan-out layer keyed by `(exchange, symbol, interval)`. Each live task subscribes once and forwards closed updates to its own live feed. Dashboard consumers can still receive every kline update through existing dashboard events.

The hub should not execute strategy logic. Its responsibility remains connection state, message normalization, fan-out, and reconnect/catch-up orchestration.

Alternatives considered:
- Let each live data feed open its own WebSocket: simpler feed encapsulation, but loses stream sharing and increases exchange connection load.

### Decision 5: Capture live strategy output incrementally

The current `Node.start()` returns a final `TraderResult` after `cerebro.run()` completes, which fits backtests but not a long-running live loop. The live runtime needs an incremental sink for strategy operations and diagnostics.

Preferred shape:
- keep analyzers and existing `TraderResult` for backtests;
- add a live event sink or analyzer path that observes new operations/order lifecycle events as the persistent strategy advances;
- route those events to manual notification and dashboard publishers.

Alternatives considered:
- Periodically inspect the full analyzer output from the running strategy: likely brittle and still encourages replay-style dedupe.
- Force strategies to call notification code directly: violates the framework-first boundary and makes strategy testing harder.

### Decision 6: Run persistent Cerebro without blocking the async task loop

`cerebro.run()` is blocking. The realtime task should run Cerebro in a managed worker thread or executor while the async WebSocket consumer enqueues candles into the feed. Shutdown must signal the feed to stop, wait for Cerebro to exit, unsubscribe from the market stream, and close cleanly.

Alternatives considered:
- Convert the whole live path to threads: lower async complexity but conflicts with existing async task manager and stream hub.
- Poll the feed manually without `cerebro.run()`: fights Backtrader internals and defeats the point of a live feed.

## Risks / Trade-offs

- Blocking runtime and async stream coordination can deadlock -> Use a small feed interface with explicit `put_bar`, `mark_live`, `mark_disconnected`, and `stop` methods; test shutdown and no-message qcheck behavior.
- Warmup notification semantics can be noisy -> Document the development validation behavior and add tests proving warmup and LIVE operations both flow through the same event path.
- Existing strategies may depend on final `TraderResult` analyzers -> Keep backtest `Node` unchanged and add live-specific output capture instead of replacing all execution paths.
- Reconnect catch-up may duplicate a bar already delivered by WebSocket -> Deduplicate by `(exchange, symbol, interval, open_time)` before enqueueing closed bars.
- Dashboard may expect execution summaries in the old batch result shape -> Preserve event schemas where possible and adapt payload builders to incremental events.
- Local manual position can still diverge from the user's real account -> Keep manual-mode wording explicit and consider a future operator-controlled state reset/reconciliation feature.

## Migration Plan

1. Add the live feed primitive and deterministic tests for `_load()`, `islive()`, qcheck timeout behavior, status notifications, closed-bar delivery, duplicate suppression, and stop behavior.
2. Add a persistent live Cerebro runner that can warm up from historical candles, transition to live, accept new closed bars, and shut down cleanly.
3. Add incremental operation capture for live strategies without changing backtest result generation.
4. Integrate the new runner into `TraderTask.start_realtime` behind the existing `live_data_mode = realtime` path.
5. Preserve open-candle dashboard updates in the stream/runtime layer while routing closed candles into the feed.
6. Replace replay-on-window notification handling with persistent-feed incremental event handling for warmup, reconnect catch-up, and LIVE bars.
7. Keep or mark the old `RealtimeLiveStrategyRuntime` as legacy until tests and smoke validation prove the new path covers startup, live bars, reconnect, and shutdown.
8. Update README live-mode docs and OpenSpec archive notes to state that Backtrader live feed execution is the supported realtime architecture.

Rollback strategy: keep the previous replay-on-window runtime reachable behind an internal fallback during implementation. If the persistent feed runner fails validation, switch `start_realtime` back to the legacy runtime while preserving the new feed tests for continued development.

## Open Questions

- Should startup notification stay completely disabled, or should there be a future explicit "notify latest unsent startup signal" policy?
- Should manual local state be initialized only from task config, or should a future change add operator-controlled state reconciliation from saved task state?
- Should a full Binance Store/Broker become a separate follow-up change after the manual-notify feed runtime is stable?
