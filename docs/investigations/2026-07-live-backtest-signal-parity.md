# July 2026 Live / Backtest Signal Parity

## Scope

- Strategy: `macd_triple_divergence`
- Markets: BTC, ETH, BNB, SOL, XRP, DOGE, ADA, TRX, AVAX, and LINK against USDT
- Interval: 1h
- Time zone: Asia/Shanghai (UTC+08:00)
- Evidence window: 2026-07-01 00:00:00 through 2026-07-14 16:01:25
- Last comparable closed candle: 2026-07-14 15:00:00
- Live evidence: `logs/trader.log`
- Production parameters: `configs/tasks/live/auto_trade_macd_triple_divergence_top10_production.json`

This investigation complements the [Binance execution reconciliation](2026-07-execution-state-binance-reconciliation.md). That report proves that logged submissions reached Binance. This report checks the earlier question: whether live processing produced the same operations as an offline replay of the finalized Binance candles.

## Method

The replay used Binance's public historical kline endpoint and the same `BacktraderLiveRunner` used by production. It did not load exchange credentials or instantiate `AutoExecutionRouter`.

Three replay shapes were run:

1. Continuous replay from the first July runtime session through the cutoff.
2. Restart-state replay using every logged restart and warmup size, with ideal continuous candle delivery.
3. Restart-and-delivery-faithful replay that also removes candles during logged polling-stream outages.

Live candles were delivered one at a time and allowed to finish processing before the next candle. Queuing all live candles at once changes Backtrader stop-order notification timing and is not representative of the hourly production feed.

The public dataset contains 832 consecutive candles per market from 2026-06-10 00:00 through 2026-07-14 15:00, with zero gaps. The reconciliation tool enforces the expected first candle, last candle, count, and one-hour cadence before replaying. A separate one-off read-only database comparison found that every stored OHLCV row in the overlapping interval exactly matches the public Binance history; that database comparison is investigation evidence rather than a committed automated test.

## Result

| Metric | Count |
| --- | ---: |
| Logged non-warmup live operations | 37 |
| Continuous / restart-state replay operations with ideal delivery | 40 |
| Restart-and-delivery-faithful replay operations | 37 |
| Logged operations reproduced exactly by symbol, time, and type | 37 |
| Logged operations absent from replay | 0 |
| Ideal-delivery replay operations absent from live processing | 3 |
| Logged live entry operations (`LONG` / `SHORT`) | 16 |
| Logged exchange entry submissions | 12 |

All 37 operations that live processing emitted are valid and reproducible. The restart-and-delivery-faithful replay matches those 37 operations exactly. The ideal-delivery replays produce three additional operations, showing what the same strategy state would have emitted if the two failed streams had continued advancing.

The continuous replay produced the same ideal-delivery operation set, but three submitted-entry `signal_event_id` values differed because continuous counters do not reset. Both restart-based replays matched all retained submitted-entry IDs. The final 2026-07-13 22:45 restart reduced warmup from 500 to 100 candles; it did not introduce another operation difference before the cutoff.

| Market | Replay operation | Signal time | Live evidence |
| --- | --- | --- | --- |
| XRPUSDT | `SHORT` | 2026-07-12 03:00 | Reappeared only as warmup operation after the 2026-07-13 21:01 restart |
| XRPUSDT | `CLOSE` | 2026-07-12 06:00 | Consequence of the missed short; no live execution outcome |
| SOLUSDT | `LONG` | 2026-07-13 13:00 | Reappeared only as warmup operation after the 2026-07-13 21:01 restart |

Per-market operation counts:

| Market | Live | Replay | Difference |
| --- | ---: | ---: | --- |
| BTCUSDT | 4 | 4 | 0 |
| ETHUSDT | 2 | 2 | 0 |
| BNBUSDT | 4 | 4 | 0 |
| SOLUSDT | 5 | 6 | Missing one `LONG` live operation |
| XRPUSDT | 2 | 4 | Missing one `SHORT` and its `CLOSE` live operation |
| DOGEUSDT | 16 | 16 | 0 |
| ADAUSDT | 2 | 2 | 0 |
| TRXUSDT | 0 | 0 | 0 |
| AVAXUSDT | 0 | 0 | 0 |
| LINKUSDT | 2 | 2 | 0 |

## Root Cause

At 2026-07-12 00:01, the XRP public kline request timed out. The polling scheduler removed `xrpusdt@kline_1h`, then its catch-up callback also timed out:

```text
CCXT polling fetch failed: stream=xrpusdt@kline_1h
CCXT polling scheduler stream removed: stream=xrpusdt@kline_1h reason=websocket disconnected
CCXT polling disconnect recovery failed: stream=xrpusdt@kline_1h
```

There were no further XRP polls until the 2026-07-13 21:01 task restart. Startup backfill then fetched 46 candles and replayed the missed short and close as warmup operations with `execution_outcomes=0`.

SOL followed the same failure sequence at 2026-07-13 00:01. Its stream did not poll again until the 21:01 restart, when startup backfill fetched 22 candles and rediscovered the 13:00 long as a warmup operation. Warmup suppression correctly prevented historical orders, but by then the original live entry opportunity had already been missed.

The defect is therefore in the shared stream recovery lifecycle, not in the MACD strategy.

## Execution-Layer Limitation

The log contains 16 live entry operations and 12 `[auto_execution] submitted` entries. The other four are DOGEUSDT `LONG` operations at signal times 2026-07-07 14:00, 2026-07-08 13:00, 15:00, and 18:00.

Each has `execution_outcomes=1`, but no submitted, failed, or margin-blocked audit line. `AutoExecutionRouter` currently logs all submitted and failed outcomes, but most generic `SKIPPED` outcomes are silent. The persisted task row no longer retains these historical outcomes. Consequently, this evidence proves that the four signals reached the router and did not submit an order, but it cannot recover the exact skip reason.

This is an observability gap: complete execution parity cannot be proven for those four entries from retained evidence.

## Conclusions And Follow-up

- Strategy parity for processed candles: **pass**. All 37 emitted live operations match both replay forms.
- Complete live candle processing: **fail**. Three operations were missed during unrecovered XRP/SOL stream outages.
- Retained submission correlation: **12 of 16 entry operations** can be tied to an explicit submitted audit event.
- Complete execution-layer parity: **fail**. Four DOGE long outcomes have no retained status or reason, so the approved dual-layer gate is not satisfied.

The framework-level fixes should:

1. Keep retrying or re-register a polling stream when both the primary poll and disconnect catch-up fail.
2. Alert when an expected live stream's last closed candle falls behind its interval.
3. Audit and persist every `AutoExecutionOutcome`, including ordinary `SKIPPED` reasons.

The machine-readable replay output is generated under `tmp/2026-07-live-signal-reconciliation-second.json` and is intentionally not committed.
