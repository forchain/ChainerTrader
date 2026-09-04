# Acceptance Contract: Live Leverage Ratio Verification

## Skill Binding Metadata
- skill_id: blackbox-acceptance-orchestrator
- skill_version: local
- workflow_id: 2026-06-30-leverage-ratio-live-acceptance
- skill_run_root: docs/acceptance/2026-06-30-leverage-ratio-live-acceptance/
- source_contract: docs/acceptance/2026-06-30-leverage-ratio-live-acceptance/acceptance-contract.md
- governed_rules:
  - document_approval_gate
  - blackbox_boundary
  - exception_force_majeure_policy
  - agent_isolation_and_lifecycle

## Mode
- Existing implementation acceptance.

## Goal
- User-visible outcome: verify that `TRADER_LEVERAGE_RATIO` is loaded from environment and correctly governs leveraged live exposure in the shared cross-margin execution path used by both long and short orders.
- Why this matters: the new feature exists to allow short-capable live execution while preventing oversized borrowing beyond the configured exposure ceiling, without changing the intended order notional when the requested amount is already within the allowed limit.
- Required completion context: live operator acceptance on 2026-06-30 (Asia/Shanghai).

## Scope
- In scope:
  - global env config `TRADER_LEVERAGE_RATIO` loaded by the real runtime
  - cross-margin long order notional matches the strategy-configured amount when the request is within available capital
  - cross-margin short borrow-side notional matches the strategy-configured amount when the request is within available capital
  - cross-margin short live path is capped by `available_capital * leverage_ratio` when the request exceeds the allowed limit
  - capped `auto_trade.live_trade_max_notional` remains an independent hard cap
  - operator can verify success from Chainer output plus Binance web history
- Out of scope:
  - futures exchange integration
  - profitability or strategy quality
  - liquidation or maintenance-margin modeling
  - long-duration soak testing

## Non-Goals
- Revalidating all existing spot/margin protection behavior.
- Proving exchange fee exactness to the cent.
- Testing CLI/env parsing for every unrelated config field.

## Roles
- User: acceptance owner and final decision maker
- Project Manager / Orchestrator: document coordination and acceptance control
- Development Agent: not required unless acceptance finds a product defect
- Testing Agent: to be isolated in sub-agent after approval; black-box evidence only

## Resources And Preconditions
- Environment: current worktree `feat/leverage-ratio-config`
- Credentials / config:
  - Binance credentials available in local environment
  - `TRADER_DB` configured
  - `TRADER_EXCHANGE=BINANCE` or equivalent runtime exchange config available
- External systems:
  - Binance cross-margin account with short-capable permissions
- Runtime assumptions:
  - live task can be started with existing CLI/runtime path
  - operator can access Binance Web order history during verification
- Resource note discovered during preflight:
  - current account snapshot shows `CROSS_MARGIN USDT=100.0`
  - this run should treat cross-margin as the canonical account surface for both long and short verification
- Safety limits:
  - use capped `auto_trade`
  - use minimal notional above exchange min-notional
  - one symbol only, default `BTC-USDT`
  - no run should intentionally create exposure beyond a small capped smoke amount

## Acceptance Strategy
- Use three black-box runs:
  1. cross-margin long run: prove long order notional equals the configured strategy amount when within the allowed limit
  2. cross-margin short run: prove short order notional equals the configured strategy amount when within the allowed limit
  3. cross-margin short cap run: prove leveraged short is reduced when requested notional exceeds the 1:1 ceiling

The third run must intentionally request more than the allowed leveraged ceiling. Without an over-limit request, the acceptance can show that leveraged orders work, but it cannot prove that the cap is actually enforced.

## Acceptance Gates
| ID | Capability | Required Evidence | Human-Visible Proof | Status |
| --- | --- | --- | --- | --- |
| AC-LR-001 | Runtime loads `TRADER_LEVERAGE_RATIO=1.0` in live context | startup env snapshot + task run config evidence | operator can confirm env value used for run | passed |
| AC-LR-002 | Cross-margin long entry preserves configured order notional | Chainer outcome with requested/effective notional equality + Binance margin order history | long order notional stays at task-requested size | passed |
| AC-LR-003 | Cross-margin short entry preserves configured order notional when within the limit | Chainer outcome with requested/effective notional equality + Binance margin order history | short borrow-side notional stays at task-requested size | passed |
| AC-LR-004 | Cross-margin short entry is capped at 1:1 exposure when the request exceeds the limit | Chainer outcome with `requested_notional > effective_notional` + Binance margin order history sized near effective notional | margin short notional does not exceed owned quote capital | passed |
| AC-LR-005 | capped `auto_trade` remains independent from leverage ratio | Chainer outcome with ratio raised but `effective_notional` still equal to task cap | order size does not grow just because ratio increased | passed |
| AC-LR-006 | Observability is sufficient for operator sign-off | execution report with timestamps, task config, order IDs, requested/effective notionals, manual verification path | operator can independently cross-check in Binance Web | passed |

## Failure Classification
| Classification | Definition | Required Action |
| --- | --- | --- |
| actionable | Recoverable by canceling stale orders, switching task mode, or rerunning with corrected task config | remediate once and retry |
| force_majeure | Exchange outage, missing margin permission, account restriction, missing external balance | mark skipped/block and continue independent checks |
| hard_fail | Cap behavior contradicts accepted semantics or evidence is insufficient to decide | stop and reopen development demand |

## Review
- Reviewed by User: pending
- Approved version/date: pending
- Change history:
  - v1 created on 2026-06-30 for leverage-ratio live acceptance planning
  - v2 updated after live preflight discovered no usable spot quote balance in the current account
  - v3 updated after user clarified that both long and short verification must use the same cross-margin account surface
