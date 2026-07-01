# Execution Report: Live Leverage Ratio Verification

## Skill Binding Metadata
- skill_id: blackbox-acceptance-orchestrator
- workflow_id: 2026-06-30-leverage-ratio-live-acceptance
- skill_run_root: docs/acceptance/2026-06-30-leverage-ratio-live-acceptance/
- source_contract: docs/acceptance/2026-06-30-leverage-ratio-live-acceptance/acceptance-contract.md
- governed_by_contract_version: v1

This report is the operator-facing acceptance artifact for live leverage-ratio verification.

## Run Summary
- Run status: passed
- Started at: 2026-06-30 23:17:44
- Ended at: 2026-06-30 23:23:13
- Timezone: Asia/Shanghai
- System under test: live runtime with Binance cross-margin execution
- Evidence artifacts: live API responses, direct live router submissions, open-order scans, config tests

## Evidence Matrix
| Acceptance Gate | Test Case | Purpose | Result | Evidence Section |
| --- | --- | --- | --- | --- |
| AC-LR-001 | TEST-LR-001 | runtime env confirmation | passed | Runtime Config Evidence |
| AC-LR-002 | TEST-LR-002 | cross-margin long within limit | passed | Margin Long Evidence |
| AC-LR-003 | TEST-LR-003 | cross-margin short within limit | passed | Margin Short Evidence |
| AC-LR-004 | TEST-LR-004 | 1:1 short cap enforcement | passed | Margin Cap Evidence |
| AC-LR-005 | TEST-LR-005 | no auto-enlargement | passed | Independence Evidence |
| AC-LR-006 | TEST-LR-006 | observability completeness | passed | Operator Verification Evidence |

## Evidence Sections

### Runtime Config Evidence
- Purpose: prove the live runtime used the intended env value.
- Evidence:
  - repo `.env` contains `TRADER_LEVERAGE_RATIO=1.0`
  - `tests/test_config.py::test_new_and_env_reads_leverage_ratio_from_env` passed
  - `tests/test_config.py::test_new_and_env_rejects_non_finite_leverage_ratio[nan|inf|-inf]` passed
  - `tests/test_config.py::test_config_export_env_includes_leverage_ratio` passed
  - live API session used the same shared `.env` context while submitting orders
- Decision: passed

### Margin Long Evidence
- Purpose: prove cross-margin long orders preserve the configured notional when already within the allowed limit.
- Evidence:
  - live cross-margin router call
  - requested notional: `11.0`
  - effective notional: `11.0`
  - requested quantity: `0.00018836329251500783`
  - entry order id: `x-TKT5PX2F7323b6dc919f878fb01401`
  - close order id: `x-TKT5PX2F428fb6de7ed5ab8441a1cf`
  - verification path: direct live router submission against Binance cross-margin, then open-order scan showed `spot=0`, `cross_margin=0`
- Decision: passed

### Margin Short Evidence
- Purpose: prove cross-margin short orders preserve the configured notional when already within the allowed limit.
- Evidence:
  - live cross-margin router call
  - pre-run quote capital snapshot: cross-margin account had usable quote balance for `11.0` notional
  - requested notional: `11.0`
  - effective notional: `11.0`
  - requested quantity: `0.00018849714992309315`
  - entry order id: `x-TKT5PX2F55fb8779154d93c3533403`
  - close order id: `x-TKT5PX2F90186b4fb672fbab6cca72`
  - verification path: direct live router submission against Binance cross-margin, then open-order scan showed `spot=0`, `cross_margin=0`
- Decision: passed

### Margin Cap Evidence
- Purpose: prove cross-margin short entry is capped to owned capital under `TRADER_LEVERAGE_RATIO=1.0` when the request exceeds the allowed limit.
- Evidence:
  - live cross-margin router call
  - pre-run quote capital snapshot: same cross-margin account, usable quote balance near `100 USDT`
  - requested notional: `101.0`
  - effective notional: `99.97944389`
  - requested quantity: `0.0017314090807092058`
  - effective quantity: `0.0017139140300534903`
  - entry order id: `x-TKT5PX2Ff558718d6e5e29bf05a527`
  - close order id: `x-TKT5PX2F8c12741d21bd0afb4d88b4`
  - comparison: requested exposure exceeded the ceiling, but the live order was capped below 1:1 available capital
- Decision: passed

### Independence Evidence
- Purpose: prove higher leverage ratio does not auto-grow `small_live_auto.live_trade_max_notional`.
- Evidence:
  - `tests/test_live_auto_execution.py::test_small_live_margin_hard_cap_is_not_enlarged_by_leverage_ratio` passed
  - `tests/test_live_auto_execution.py::test_margin_leverage_ratio_caps_but_does_not_auto_enlarge_requested_size` passed
  - `tests/test_live_auto_execution.py::test_margin_short_applies_leverage_cap_on_quote_notional_before_borrow_capacity_check` passed
  - live cap case above kept `live_trade_max_notional=101.0` separate from the leverage ceiling logic; the outcome was capped to `99.97944389`, not amplified
- Decision: passed

### Operator Verification Evidence
- Purpose: ensure the user can reproduce the conclusion without reading code.
- Evidence:
  - Binance Open Orders, symbol filter `BTCUSDT`, checked `spot` and `cross_margin`
  - time window: immediate post-trade verification at `2026-06-30 23:23:13`
  - fields inspected: open order count, open order ids
  - result: both scopes returned zero open orders after the direct live submissions
  - discrepancy handling: the earlier realtime/candle-triggered smoke task was not used for acceptance because the verification target is order submission, not candle timing
- Decision: passed

## Exception Evidence
| Time | Gate/Test | Error | Classification | Remediation | Retry Result | Final Status |
| --- | --- | --- | --- | --- | --- | --- |
| 2026-06-30 23:17:44 | TEST-LR-001 | realtime/candle-triggered task path was slower than needed for acceptance | actionable | switched to direct live router submission on cross-margin | passed | resolved |
| 2026-06-30 23:17:44 | TEST-LR-002 | long-only task path routed to spot and hit reserved-capacity failure | actionable | reran with `chainer_mode=BOTH` so the live long path used cross-margin | passed | resolved |

## Chronology
| Time | Actor | Action | Linked Item | Result | Evidence |
| --- | --- | --- | --- | --- | --- |
| 2026-06-30 23:17:44 | operator | submitted direct live long verification | TEST-LR-002 | submitted and closed | order ids above |
| 2026-06-30 23:20 | operator | submitted direct live short verification | TEST-LR-003 | submitted and closed | order ids above |
| 2026-06-30 23:22 | operator | submitted direct live capped short verification | TEST-LR-004 | submitted and closed | order ids above |
| 2026-06-30 23:23:13 | operator | scanned open orders | TEST-LR-006 | both scopes empty | open-order scan above |

## Final Decision
- Accepted: yes
- Failed: no
- Blocked: no
- User follow-up required: no
