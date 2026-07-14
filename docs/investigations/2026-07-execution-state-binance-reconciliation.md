# July 2026 Binance Execution Reconciliation

Related follow-up: [July 2026 Live / Backtest Signal Parity](2026-07-live-backtest-signal-parity.md) checks whether finalized Binance candles produced the same strategy operations in live processing and offline replay.

## Scope

- Log source: `logs/trader.log`
- Account: saved Binance cross-margin credential `ECaw***AFgu`
- Time zone: Asia/Shanghai (UTC+08:00)
- Period: 2026-07-01 through the supplied log's last execution on 2026-07-13
- Included: `[auto_execution] submitted` events in `auto_trade` mode
- Excluded: `Realtime warmup operation ignored for auto execution` and strategy replay/backtest messages

The Binance margin endpoints were queried read-only in one-day windows because the endpoint rejects windows longer than 24 hours. Every logged live submission below has an exact exchange-side entry order and protection order match by client order ID. The exchange normalizes quantities to symbol precision, so a few exchange quantities are slightly lower than the requested quantity in the log.

## Result

| Metric | Count |
| --- | ---: |
| Logged live entry/protection pairs | 11 |
| Exact Binance pairs found | 11 |
| Current database pairs retained | 4 |
| Pairs overwritten in `execution_states` | 7 |
| Warmup operations counted as live trades | 0 |

## Pair-by-pair Check

`DB retained` means the current `execution_states` row still represents this pair. `Overwritten` means an execution with the same unscoped signal-event key later replaced it; the exchange order is real and matched.

| Log time | Task / signal | Symbol / side | Binance entry order | Binance protection order | Current DB state |
| --- | --- | --- | --- | --- | --- |
| 2026-07-04 01:00:50 | 1781368132852 / 1 | DOGEUSDT short, 144.092219 -> 144 | `14664229190` / `ct1781368132852smacd_tri_0001`, filled at 0.07642 | `14664229206` / `_0002`, stop 0.07681, filled | Overwritten by later signal 1 |
| 2026-07-04 04:00:49 | 1781368132852 / 2 | DOGEUSDT short, 143.061516 -> 143 | `14664678781` / `_0003`, filled at 0.07719 | `14664678787` / `_0004`, stop 0.07737, filled | Overwritten by BNB signal 2 |
| 2026-07-04 08:00:40 | 1781368132847 / 3 | BTCUSDT short, 0.000175781 -> 0.00017 | `64162597872` / `ct1781368132847smacd_tri_0001`, filled at 62585.57 | `64162597946` / `_0002`, stop 62979.86, filled | Overwritten by BNB signal 3 |
| 2026-07-04 08:00:49 | 1781368132852 / 3 | DOGEUSDT short, 141.370004 -> 141 | `14665450743` / `_0005`, filled at 0.07754 | `14665450748` / `_0006`, stop 0.07848, filled | Overwritten by BNB signal 3 |
| 2026-07-05 04:00:30 | 1781368132849 / 2 | BNBUSDT short, 0.019068421 -> 0.019 | `12187326390` / `ct1781368132849smacd_tri_0001`, filled at 575.38 | `12187326455` / `_0002`, stop 578.79, filled | Retained: rows 2 and 4 |
| 2026-07-05 05:00:49 | 1781368132852 / 4 | DOGEUSDT short, 140.002546 -> 140 | `14668325747` / `_0007`, filled at 0.07803 | `14668325769` / `_0008`, stop 0.07931, `NEW` when queried | Overwritten by BTC signal 4 |
| 2026-07-05 06:00:40 | 1781368132847 / 4 | BTCUSDT short, 0.000173958 -> 0.00017 | `64185015418` / `ct1781368132847smacd_tri_0003`, filled at 63309.99 | `64185015562` / `_0004`, stop 63461.99, filled | Retained: rows 6 and 8 |
| 2026-07-06 09:00:59 | 1781368132848 / 1 | ETHUSDT short, 0.006160222 -> 0.0061 | `48176658964` / `ct1781368132848smacd_tri_0001`, filled at 1792.80 | `48176659077` / `_0002`, stop 1808.00, filled | Overwritten by later signal 1 |
| 2026-07-08 09:00:11 | 1781368132853 / 1 | ADAUSDT long, 63.001145 -> 63 | `8701067537` / `ct1781368132853smacd_tri_0001`, filled at 0.17590 | `8701067538` / `_0002`, stop 0.17330, filled | Overwritten by LINK signal 1 |
| 2026-07-12 01:00:21 | 1781368132849 / 3 | BNBUSDT short, 0.018970096 -> 0.018 | `12228207476` / `ct1781368132849smacd_tri_0001`, filled at 579.92 | `12228207482` / `_0002`, stop 583.01, filled at 583.02 | Retained: rows 5 and 7 |
| 2026-07-12 05:00:48 | 1781368132856 / 1 | LINKUSDT short, 1.361386 -> 1.36 | `7862900454` / `ct1781368132856smacd_tri_0001`, filled at 8.072 | `7862900457` / `_0002`, stop 8.12, filled | Retained: rows 1 and 3 |

The supplied exchange screenshot independently corroborates the visible subset:

- ETH sell on 2026-07-06 at 1792.80 for 0.0061.
- ADA buy then stop sell on 2026-07-08 at 0.17590 and 0.17330 for 63.
- BNB sell and stop buy on 2026-07-12 at 579.92 and 583.02 for 0.018.
- LINK sell on 2026-07-12 at 8.072 for 1.36, followed by two 8.12 buy fills totaling 1.36 on 2026-07-13.

## Root Cause

`AutoExecutionRouter` creates records with `task_id`, but `ExecutionStateRecord.from_order_intent()` and `.from_risk_intent()` previously used only the strategy-local key:

```text
intent:{signal_event_id}:{signal_event_id}:entry
risk:intent:{signal_event_id}:{signal_event_id}:place_protection
```

Every task starts its signal-event counter at 1. `execution_states.idempotency_key` is globally unique, and `ExecutionStateCol.save()` updates a row with the same key. Consequently, a later task silently overwrote an earlier task's execution state even though both exchange orders were submitted and filled.

The fix scopes the persisted key by task ID:

```text
task:{task_id}:{original_intent_key}
```

The original intent key remains in `raw_payload` for strategy-event traceability. No database migration is required because the existing global unique constraint now applies to the task-scoped value.

## Residual Historical Limitation

The seven overwritten database rows cannot be reconstructed solely from the current database, because their original values were replaced. This report preserves the forensic mapping from the immutable log and the exchange's read-only historical orders/trades. New executions after deployment will retain one database row per task-scoped execution state.
