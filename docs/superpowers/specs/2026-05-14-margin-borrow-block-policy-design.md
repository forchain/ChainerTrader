# Margin Borrow Block Policy Design

## Goal

Make Binance cross-margin borrow failures controllable at the execution framework layer, without requiring strategy code changes.

The framework should:

- Prefer pre-trade checks when Binance exposes reliable account data.
- Keep post-error handling for `-3006` because exchange-side borrow decisions can still change at submit time.
- Support cross-symbol liabilities by adding an explicit account-level repayment policy.
- Emit enough structured evidence for operators and agents to explain every skip, repayment, retry, and failure.

## Current Problem

Binance margin orders can fail with:

```text
-3006 Your borrow amount has exceed maximum borrow amount.
```

In cross-margin mode, this does not necessarily mean the current symbol assets are the only problem. A `BTC-USDT` order can be blocked because the margin account already has liabilities on other assets, for example `ETH`, `SOL`, or accumulated `BNB` interest.

The current project already has a framework-level setting:

```json
"live_margin_borrow_block_policy": "repay_single"
```

But the existing implementation only applies the borrow-block handler to `SHORT` margin entries. A `BUY`/long entry routed through cross margin can hit the same `-3006` path and currently fails instead of applying the configured policy.

## Documentation Findings

Sources checked:

- Binance Margin Level and Risk Control: https://www.binance.com/en/support/faq/binance-margin-level-and-risk-control-360030493931
- Binance Query Cross Margin Account Details: https://developers.binance.com/docs/margin_trading/account/Query-Cross-Margin-Account-Details
- Binance Query Max Borrow: https://developers.binance.com/docs/margin_trading/borrow-and-repay/Query-Max-Borrow
- Binance Margin Error Code: https://developers.binance.com/docs/margin_trading/error-code
- CCXT manual: https://github.com/ccxt/ccxt/wiki/manual
- Context7 lookup for Binance connector docs confirmed `maxBorrowable` API shape for Binance margin APIs.

Binance defines `-3006 EXCEED_MAX_BORROWABLE` as exceeding the maximum borrowable amount.

Binance exposes `GET /sapi/v1/margin/maxBorrowable`, which returns the current maximum borrowable amount for an asset. This is the best direct precheck signal for whether a planned order can borrow the required shortfall.

Binance cross-margin account details expose:

- `borrowEnabled`
- `tradeEnabled`
- `marginLevel`
- `collateralMarginLevel`
- account-level asset and liability totals
- per-asset `free`, `locked`, `borrowed`, `interest`, and `netAsset`

Binance's margin risk docs distinguish normal margin risk from borrow eligibility. For Cross Margin Classic:

- 3x account: borrow is allowed only when Borrow Margin Level is greater than `1.5`.
- 5x account: borrow is allowed only when Borrow Margin Level is greater than `1.25`.
- Margin call and liquidation use lower `Margin Level` thresholds.

Do not fully reimplement Binance's borrow-risk calculation locally. Borrow Margin Level depends on collateral valuation, collateral ratios, mark prices, account type, asset haircuts, and exchange-side conditions. The framework should use Binance's `maxBorrowable` result as the authoritative precheck and record `marginLevel` / `collateralMarginLevel` for observability.

## Architecture Decision

Handle this in the execution framework, not in strategies.

Flow:

```text
Strategy -> Operation -> AutoExecutionRouter -> ExecutionGateway -> ExchangeDriver -> Binance/CCXT
```

Responsibilities:

- Strategy: emit `BUY`, `SELL`, `SHORT`, `CLOSE`, and risk-update operations.
- `AutoExecutionRouter`: decide whether to submit, skip, repay, retry, or fail based on task config and execution context.
- `ExecutionGateway`: normalize live exchange responses into execution results and events.
- `ExchangeDriver`: expose Binance account, max-borrow, order, and repay primitives.
- Task config: control behavior through configuration rather than strategy edits.

This follows the repository's framework-first policy. Borrow availability, margin account health, exchange error classification, and retry policy are shared execution concerns.

## Policy Model

Existing policies should be clarified and extended:

```text
skip_continue
repay_single
repay_all
stop_task
```

Backward-compatible aliases:

- `skip_short_continue` maps to `skip_continue`.
- `auto_repay_then_retry_once` and `repay_symbol_assets_retry` map to `repay_single`.
- `repay_all_liabilities_retry` maps to `repay_all`.
- `hard_fail_stop_task` maps to `stop_task`.

Policy behavior:

- `skip_continue`: skip the blocked signal and continue the task.
- `repay_single`: repay liabilities only for the current symbol's base and quote assets, then retry the original order once.
- `repay_all`: scan all cross-margin assets with `borrowed + interest > 0`, repay what can be repaid within configured limits, then retry the original order once.
- `stop_task`: surface the blocked order as a hard execution failure.

`repay_all` should default to scanning all assets with liabilities when explicitly selected. It should not require an allowlist by default because the intended use case is cross-symbol borrow blockage. It may support optional exclusions.

## Configuration Contract

Recommended configuration fields:

```json
{
  "live_margin_borrow_precheck": true,
  "live_margin_borrow_block_policy": "repay_all",
  "live_margin_auto_repay_max_total": 100.0,
  "live_margin_auto_repay_max_per_asset": 50.0,
  "live_margin_auto_repay_min_amount": 0.000001,
  "live_margin_auto_repay_excluded_assets": [],
  "live_margin_auto_repay_retry_once": true
}
```

Defaults:

- `live_margin_borrow_precheck`: `true` for cross-margin live modes.
- `live_margin_borrow_block_policy`: defaults to `skip_continue`; repayment requires explicit opt-in.
- `live_margin_auto_repay_max_total`: required for `repay_all`.
- `live_margin_auto_repay_max_per_asset`: required for `repay_all`.
- `live_margin_auto_repay_excluded_assets`: empty by default.
- `live_margin_auto_repay_retry_once`: always true for this feature. More retries should not be added initially.

If `repay_all` is configured without repayment caps, fail task config validation before live execution starts.

## Precheck Design

Before submitting a cross-margin order that may auto-borrow:

1. Read the local/free balance for the asset that may need to be borrowed.
2. Estimate the borrow shortfall.
3. Query Binance max-borrow data for that asset.
4. Skip before order submission when max borrowable capacity is below the estimated shortfall.
5. Attach account and max-borrow evidence to the execution outcome.

Asset selection:

- `BUY` / long entry: quote asset may need borrowing. For `BTC-USDT`, check `USDT`.
- `SHORT` entry: base asset may need borrowing. For `BTC-USDT`, check `BTC`.
- `SELL` / long exit: normally reduces exposure; do not block solely on borrow precheck.
- `CLOSE` / short close: normally repays/reduces exposure; do not block solely on borrow precheck.
- Risk/protection orders: do not use borrow precheck initially. Protection failure handling remains separate.

Skip reason:

```text
margin_borrow_precheck_insufficient_capacity asset=USDT shortfall=5.0 max_borrowable=4.0 borrow_limit=...
```

Precheck failures should produce `AutoExecutionStatus.SKIPPED`, not `FAILED`.

Precheck is advisory. It reduces avoidable failed orders but cannot replace post-error handling because max borrowable data may change between the check and order submission.

## Post-Error Handling

When a margin order returns `-3006`, classify it as a borrow-block result and apply `live_margin_borrow_block_policy`.

The handler must apply to all margin entry orders that can create borrowing:

- `BUY` routed through cross margin
- `SHORT` routed through cross margin

The current short-only behavior is a bug.

Do not apply borrow-unblock repayment to normal close paths by default. Close orders usually reduce exposure and should be handled through position reconciliation and exchange error reporting unless a real blocked-close case is proven.

Retry behavior:

- Retry the original order at most once.
- If retry succeeds, status is `SUBMITTED`.
- If retry returns `-3006`, status is `SKIPPED`.
- If retry fails for a non-borrow reason, status is `FAILED`.
- If protection placement fails after a successful retry, keep the existing fail-safe close behavior.

## Account-Level Repayment

`repay_all` should:

1. Query cross-margin account details.
2. Find all assets where `borrowed + interest > 0`.
3. For each asset, compute repayable amount as the minimum of liability, free balance, remaining total cap, and per-asset cap.
4. Skip assets below `live_margin_auto_repay_min_amount`.
5. Skip assets in `live_margin_auto_repay_excluded_assets`.
6. Execute repay calls.
7. Return a structured report for all assets considered, including skipped assets.
8. Retry the original order once if at least one repayment succeeded.

The repayment report must include:

- policy name
- trigger code and message
- original order market, operation type, requested notional, requested quantity
- account margin snapshot if available
- attempted assets
- repaid assets
- skipped assets with reasons
- total repaid estimate
- configured caps
- retry result

## Observability

Every precheck skip, borrow-block repayment, and retry should be visible in:

- `AutoExecutionOutcome.reason`
- `AutoExecutionOutcome.execution_events[*].metadata`
- structured `[auto_execution]` logs
- dashboard event payloads
- live smoke / operational verification reports where applicable

Recommended metadata shape:

```json
{
  "margin_borrow_control": {
    "stage": "precheck|post_error",
    "policy": "repay_all",
    "trigger": "binance_-3006",
    "asset": "USDT",
    "estimated_shortfall": 5.0,
    "max_borrowable": 4.0,
    "borrow_limit": 10000.0,
    "margin_level": "1.72",
    "collateral_margin_level": "1.48",
    "repay_results": []
  }
}
```

This is important because one symbol's signal may legitimately trigger repayment of unrelated assets in cross-margin mode.

## Implementation Tasks

Task 1: Preserve the immediate long-entry bug fix.

- Add a regression test proving a margin-routed `BUY` receiving `-3006` applies the borrow-block policy and can recover via repayment retry.
- Change `AutoExecutionRouter._submit_margin()` so the borrow-block handler applies to `OperateType.BUY` and `OperateType.SHORT`.
- Verify with `uv run python -m pytest tests/test_live_auto_execution.py::test_margin_borrow_block_repay_single_policy_handles_margin_long_orders -q`.

Task 2: Add max-borrow exchange driver support.

- Add `CcxtExchangeDriver.get_max_borrowable(asset: str, symbol: str | None = None)`.
- Use Binance margin endpoint methods when available, for example `sapiGetMarginMaxBorrowable` or the snake-case equivalent.
- Return a normalized dict with `asset`, `amount`, `borrowLimit`, and raw payload.
- Add tests in `tests/test_ccxt_exchange_driver.py`.

Task 3: Add optional precheck to `AutoExecutionRouter`.

- Add config parsing for `live_margin_borrow_precheck`.
- For margin `BUY`, estimate quote shortfall and query max borrowable for quote asset.
- For margin `SHORT`, estimate base shortfall and query max borrowable for base asset.
- Skip before order submission when max borrowable is below shortfall.
- Include structured reason and metadata.
- Add tests for long and short precheck skip paths.

Task 4: Add account-level repayment support.

- Add config fields for `repay_all` caps and exclusions.
- Add exchange driver helper for scanning all liabilities and repaying within caps.
- Add router branch for `repay_all`.
- Add tests covering full-account liability scan, cap enforcement, excluded assets, retry success, retry still blocked, and no repayable liability.

Task 5: Improve error classification.

- Keep current compatibility fallback that detects `-3006` from exchange payload text.
- Future work can move this classification into a structured gateway result if exchange adapters expose normalized error codes.

Task 6: Add operational reporting.

- Extend auto-execution audit payloads with margin-borrow-control metadata.
- Ensure dashboard event payloads retain repayment/precheck details.
- Extend live smoke report collection to show borrow blocker evidence and repayment reports.

Task 7: Run system-level live verification.

- Run a no-order/manual or dry path first to verify account snapshot and max-borrow queries.
- Run a small-live cross-margin task with a low notional and precheck enabled.
- Test controlled `skip_continue` behavior when max borrowable is insufficient.
- Test `repay_all` only with explicit repayment caps.
- Verify logs, dashboard payload, and report artifacts contain enough evidence for post-incident analysis.

## Test Plan

Unit tests:

```bash
uv run python -m pytest tests/test_live_auto_execution.py -q
uv run python -m pytest tests/test_ccxt_exchange_driver.py -q
```

Focused regression:

```bash
uv run python -m pytest tests/test_live_auto_execution.py::test_margin_borrow_block_repay_single_policy_handles_margin_long_orders -q
```

Expected additional tests:

- margin long precheck skips when quote max borrowable is below shortfall
- margin short precheck skips when base max borrowable is below shortfall
- precheck allows order submission when local balance covers the order
- precheck allows order submission when max borrowable covers the shortfall
- `repay_all` repays multiple liabilities within total cap
- excluded assets are reported but not repaid
- retry after account-level repayment succeeds
- retry after account-level repayment remains `-3006` and becomes `SKIPPED`

Live/system tests:

- Validate runtime context with the appropriate live profile before running.
- Use explicit small notional and repayment caps.
- Capture the full log/report artifact path in the final verification summary.
- Do not treat a live smoke result as a stable automated test; label it as external operational verification.

## Rollout

Phase 1:

- Ship the immediate bug fix so long margin entries use the existing borrow-block policy.

Phase 2:

- Add max-borrow precheck that returns `SKIPPED` for clearly insufficient capacity.

Phase 3:

- Add `repay_all` behind explicit config and repayment caps.

Phase 4:

- Add richer live smoke reporting and operational dashboards.

## Remaining Limitations

- `repay_all` uses native asset amounts for `max_total` and `max_per_asset`. This is a coarse safety cap, not a quote-currency valuation cap. Use conservative `max_per_asset` values and exclusions for live operation.
- Precheck depends on Binance's `maxBorrowable` response. It lowers avoidable order failures but cannot guarantee a later order will submit successfully.
- Close-path borrow blockers are not handled by repayment policy until a real blocked-close case is reproduced.

## Current Workspace State

Implemented in this change:

- Regression coverage for margin-routed long borrow-block retry.
- Router fix that applies borrow-block policy to `BUY` and `SHORT` margin entries.
- `get_max_borrowable` support in the CCXT exchange driver.
- Precheck skip for insufficient quote/base borrow capacity.
- `repay_all` support with structured account-level repayment reports.
- Short policy names: `skip_continue`, `repay_single`, `repay_all`, and `stop_task`.
