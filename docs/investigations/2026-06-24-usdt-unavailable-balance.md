# USDT Unavailable Balance Investigation

## Summary

As of the read-only investigation on 2026-06-24, the exchange backend's unavailable USDT balance is explained by open Binance cross-margin stop-market BUY orders.

The user-provided exchange backend figures were:

| Asset | Total | Available | Unavailable |
| --- | ---: | ---: | ---: |
| USDT | 76.63484216 | 5.81213216 | 70.82271000 |

The live cross-margin account query reproduced the same numbers:

| Source | Total | Free | Locked | Borrowed | Interest | Net asset |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Binance cross-margin `USDT` row | 76.63484216 | 5.81213216 | 70.82271000 | 0 | 0 | 76.63484216 |

Conclusion: the unavailable balance is exchange-side `locked` USDT in the cross-margin account. It is not caused by ChainerTrader's local fund reservation table, and it is not a USDT liability.

## Evidence

Environment validation:

```bash
bash scripts/setup_worktree.sh --profile base --require-env TRADER_EXCHANGE
```

Result: `TRADER_EXCHANGE` was present and the worktree runtime context was complete.

Read-only diagnostics performed:

- Parsed `TRADER_EXCHANGE` from `.env`.
- Queried Binance spot balance through the configured ccxt driver.
- Queried Binance cross-margin balance through the configured ccxt driver.
- Queried cross-margin open orders per relevant symbol.
- Queried local `account_fund_reservations` and `execution_states` tables.

Sanitized diagnostic artifact:

```text
tmp/usdt_unavailable_investigation.json
```

That file is intentionally not committed because it is a local generated artifact under ignored `tmp/`.

## Source Semantics

Binance Spot account documentation defines balance rows with `free` and `locked` amounts. Binance cross-margin account rows expose the same account-level concepts plus margin-specific fields such as `borrowed`, `interest`, and `netAsset`.

Relevant Binance docs:

- Spot account information: `GET /api/v3/account` (`https://developers.binance.com/docs/binance-spot-api-docs/rest-api/account-endpoints`)
- Cross-margin account details: `GET /sapi/v1/margin/account` (`https://developers.binance.com/docs/margin_trading/account/Query-Cross-Margin-Account-Details`)
- Cross-margin max borrowable: `GET /sapi/v1/margin/maxBorrowable` (`https://developers.binance.com/docs/margin_trading/borrow-and-repay/Query-Max-Borrow`)

In this repo, `CcxtExchangeDriver.get_account_balances()` maps `locked` as `total - free` for display-level balances. For margin mode, the raw ccxt payload also includes Binance `userAssets` rows.

For borrow-capacity checks, Binance's `maxBorrowable` response is the authoritative input. Binance documents:

- `amount`: the account's current max borrowable amount, assuming sufficient system availability.
- `borrowLimit`: the max borrowable amount limited by the account level.

Do not locally reimplement the full risk formula. The current borrowable amount is affected by margin risk, collateral valuation, system liquidity, account-level limits, and exchange-side rules. The local strategy gate should call `maxBorrowable` immediately before accepting or submitting a margin order, and should record `marginLevel` / `collateralMarginLevel` for explanation.

## Findings

### 1. Spot Account Is Not The Source

The configured spot account reported USDT as fully free:

| Mode | USDT total | USDT free | USDT locked |
| --- | ---: | ---: | ---: |
| Spot | 77.90706534 | 77.90706534 | 0 |

This does not match the exchange backend screenshot. The screenshot matches cross-margin, not spot.

### 2. Cross-Margin USDT Is Locked By Open Orders

The cross-margin USDT row exactly matched the user-provided figures:

| Mode | USDT total | USDT free | USDT locked |
| --- | ---: | ---: | ---: |
| Cross margin | 76.63484216 | 5.81213216 | 70.82271000 |

Open cross-margin order queries found 15 open stop-market orders across `ETH/USDT`, `TRX/USDT`, `SOL/USDT`, and `BNB/USDT`.

The BUY-side stop-market orders reserve USDT at `amount * stopPrice`. Their aggregate quote reservation is exactly:

```text
70.82271000 USDT
```

That equals:

```text
76.63484216 total - 5.81213216 available = 70.82271000 unavailable
```

### 3. Order Group Attribution

The locked USDT is attributable to these open BUY stop-market order groups:

| Symbol | Side | Type | Stop price | Count | Total amount | Estimated USDT lock |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| BNB/USDT | buy | market | 900.71 | 3 | 0.033 | 29.72343000 |
| SOL/USDT | buy | market | 180.26 | 4 | 0.228 | 41.09928000 |
| **Total** |  |  |  | **7** |  | **70.82271000** |

Other open stop-market orders lock non-USDT assets rather than USDT:

| Symbol | Side | Type | Count | Locked asset impact |
| --- | --- | --- | ---: | --- |
| ETH/USDT | sell | market | 5 | Locks ETH, not USDT |
| TRX/USDT | sell | market | 3 | Locks TRX, not USDT |

The cross-margin account confirms this asset-level lock pattern:

| Asset | Free | Locked | Borrowed | Interest | Net asset |
| --- | ---: | ---: | ---: | ---: | ---: |
| ETH | 0 | 0.03030000 | 0.00003062 | 0.00000985 | 0.03025953 |
| TRX | 36.25479600 | 108.80000000 | 0 | 0 | 145.05479600 |
| USDT | 5.81213216 | 70.82271000 | 0 | 0 | 76.63484216 |

### 4. Margin Liabilities Exist But Do Not Explain The USDT Lock

The account has cross-margin liabilities in non-USDT assets:

| Asset | Borrowed | Interest | Liability |
| --- | ---: | ---: | ---: |
| BNB | 0.03300000 | 0.00011984 | 0.03311984 |
| BTC | 0.00252542 | 0.00000463 | 0.00253005 |
| ETH | 0.00003062 | 0.00000985 | 0.00004047 |

USDT itself has:

```text
borrowed = 0
interest = 0
```

So the unavailable USDT is not borrowed USDT or USDT interest. It is order collateral locked by open cross-margin BUY stop orders.

### 5. ChainerTrader Local Reservations Are Not The Source

The local database query found:

```text
active USDT fund reservations = 0
```

Therefore ChainerTrader's `account_fund_reservations` table is not causing the exchange backend unavailable amount.

There are non-terminal local execution-state rows for older USDT symbols, but the exchange-side open order query is the authoritative source for the current locked balance. The current lock attribution comes from Binance cross-margin open orders, not local bookkeeping.

### 6. Current Borrow Capacity

A follow-up read-only query on 2026-06-25 returned:

| Field | Value |
| --- | ---: |
| Cross-margin USDT free | 5.81213216 |
| Cross-margin USDT locked | 70.82271000 |
| Cross-margin USDT borrowed | 0 |
| Cross-margin USDT interest | 0 |
| Binance `maxBorrowable(USDT).amount` | 22.89384497 |
| Binance `maxBorrowable(USDT).borrowLimit` | 100000 |
| Effective new USDT quote capacity | 28.70597713 |

Calculation:

```text
effective new USDT quote capacity
= current free USDT + current max borrowable USDT
= 5.81213216 + 22.89384497
= 28.70597713 USDT
```

The same query reported:

| Risk field | Value |
| --- | ---: |
| `marginLevel` | 1.46095273 |
| `collateralMarginLevel` | 1.28268724 |
| `totalAssetOfBtc` | 0.00414293 |
| `totalLiabilityOfBtc` | 0.00283578 |
| `totalNetAssetOfBtc` | 0.00130716 |

Interpretation:

- A new cross-margin BUY using USDT should be treated as operable only when its required quote shortfall is less than or equal to `maxBorrowable(USDT)`.
- With the current account state, a strategy requiring more than `28.70597713 USDT` of fresh quote capacity should not be allowed to start or submit a new margin BUY order.
- `borrowLimit=100000` is not the practical capacity. The practical current capacity is `amount=22.89384497` because that value already incorporates current account/risk conditions and exchange-side availability.

### 7. Strategy Gate Behavior

ChainerTrader already has two relevant checks for real auto cross-margin strategies:

| Stage | Code path | Rule |
| --- | --- | --- |
| Task startup / reservation | `TaskManager._reservation_capacity()` | Capacity is `free quote balance + get_max_borrowable(quote).amount` for short-capable cross-margin tasks. If configured strategy funds exceed that capacity, task creation fails. |
| Runtime order submission | `AutoExecutionRouter._margin_borrow_precheck()` | Before margin `BUY`, compute quote shortfall as `notional - free quote balance`; before margin `SHORT`, compute base shortfall as `quantity - free base balance`; skip the order if `maxBorrowable.amount < shortfall`. |

Existing regression coverage:

```bash
uv run python -m pytest \
  tests/test_account_fund_reservation.py::test_task_manager_accepts_cross_margin_budget_when_borrowable_capacity_covers_shortfall \
  tests/test_account_fund_reservation.py::test_task_manager_rejects_cross_margin_budget_when_balance_plus_borrowable_is_insufficient \
  tests/test_live_auto_execution.py::test_margin_borrow_precheck_skips_margin_long_when_quote_borrow_capacity_is_too_low \
  tests/test_live_auto_execution.py::test_margin_borrow_precheck_skips_margin_short_when_base_borrow_capacity_is_too_low \
  -q
```

Important boundary:

- This automatic borrow-aware path applies to real auto cross-margin strategies, currently represented by short-capable task configuration such as `strategy_params.chainer_mode = "BOTH"` or `"SHORT_ONLY"`.
- Long-only tasks are routed through spot mode by default, so they do not borrow USDT unless the strategy/configuration is explicitly routed through cross margin.

## Operational Interpretation

The account currently has open cross-margin protection/stop orders. Binance locks the assets needed to execute those orders:

- BUY stop-market orders on `SOL/USDT` and `BNB/USDT` lock USDT.
- SELL stop-market orders on `ETH/USDT` and `TRX/USDT` lock those base assets.

The 70.82271 USDT unavailable balance will remain unavailable while those BUY stop-market orders remain open.

## Suggested Follow-Up

If the unavailable USDT should be released, review and cancel only the unwanted open cross-margin stop-market BUY orders:

- `BNB/USDT` BUY stop-market orders at stop price `900.71`
- `SOL/USDT` BUY stop-market orders at stop price `180.26`

Do not cancel them automatically from this report. These may be protective or strategy-generated orders, and cancellation changes live trading risk.

Separately, the local `execution_states` table contains stale-looking non-terminal records. That did not cause the exchange lock, but it is worth reconciling in a separate maintenance task so local state better reflects exchange reality.

For strategy sizing:

- Set cross-margin strategy budget no higher than `free quote + maxBorrowable(quote)` at task startup.
- Re-check `maxBorrowable` immediately before each margin entry order because borrow capacity changes with prices, liabilities, open orders, and risk level.
- Treat `maxBorrowable.amount` as the executable limit, not `borrowLimit`.
- Keep a small safety buffer below the returned amount because market prices and risk metrics can change between precheck and order submission.

## Verification

Checks run:

```bash
bash scripts/setup_worktree.sh --profile base --require-env TRADER_EXCHANGE
uv run python - <<'PY'
# read-only account/order/local-reservation diagnostic
PY
uv run python -m pytest \
  tests/test_account_fund_reservation.py::test_task_manager_accepts_cross_margin_budget_when_borrowable_capacity_covers_shortfall \
  tests/test_account_fund_reservation.py::test_task_manager_rejects_cross_margin_budget_when_balance_plus_borrowable_is_insufficient \
  tests/test_account_fund_reservation.py::test_task_manager_uses_current_max_borrowable_amount_not_account_borrow_limit_for_margin_capacity \
  -q
```

No exchange mutation commands were run.
