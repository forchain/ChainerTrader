# Acceptance Contract: Live Margin Borrow Repay Policy Verification

## Skill Binding Metadata
- skill_id: blackbox-acceptance-orchestrator
- skill_version: local
- workflow_id: 2026-05-14-margin-borrow-repay-live-acceptance
- skill_run_root: docs/acceptance/blackbox-orchestrator/2026-05-14-margin-borrow-repay-live-acceptance/
- source_contract: docs/acceptance/blackbox-orchestrator/2026-05-14-margin-borrow-repay-live-acceptance/acceptance-contract.md
- governed_rules:
  - document_approval_gate
  - blackbox_boundary
  - exception_force_majeure_policy
  - agent_isolation_and_lifecycle

## Goal
- User-visible outcome: verify live repay policies `repay_single` and `repay_all` are operable in cross-margin account conditions.
- Why this matters: production borrow-block recovery should be controllable and observable without strategy-level patches.
- Required completion date/context: same-day live acceptance on 2026-05-14 (Asia/Shanghai).

## Scope
- In scope:
  - startup account-state branching:
    - if liabilities exist: perform cleanup path first
    - if liabilities do not exist: create a small borrow first, then repay
  - verify `repay_single` behavior (symbol-asset scope)
  - verify `repay_all` behavior (account-wide liability scope)
  - evidence capture for operator/agent postmortem
- Out of scope:
  - pnl/profitability
  - long-duration stability
  - non-Binance exchanges
- Non-goals:
  - changing strategy code for this acceptance run

## Roles
- User: acceptance owner and final decision maker
- Project Manager / Orchestrator: this run's document and execution coordination
- Development Agent: not required unless failure indicates product defect
- Testing Agent: degraded mode in same context; black-box evidence only

## Resources And Preconditions
- Environment: local worktree `margin-borrow-risk-controls`
- Accounts / permissions: Binance account with cross-margin enabled
- Credentials / config: `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `TRADER_DB` available
- External systems: Binance spot/margin APIs
- Data / DB access: not required for repay API validation itself
- Safety limits:
  - tiny borrow/repay amounts only
  - one symbol (`BTC-USDT`) for reproducibility
  - no leverage expansion beyond test prerequisite

## Acceptance Gates
| ID | Capability | Required Evidence | Human-Visible Proof | Status |
| --- | --- | --- | --- | --- |
| AC-MB-001 | Startup precheck identifies liabilities/open-order state | account snapshot + open-order snapshot + timestamp | Binance cross margin account and open orders page can match state | passed |
| AC-MB-002 | Existing liability branch executes cleanup | cleanup command output and post-clean snapshot | liability decreases or reaches 0 per asset snapshots | passed |
| AC-MB-003 | No-liability branch can induce borrow then repay | borrow tx evidence + repay evidence + final snapshot | borrow/repay records visible in Binance borrow/repay history | blocked |
| AC-MB-004 | `repay_single` executes symbol-asset scoped repayment flow | policy result payload with per-asset rows | Binance history shows repay for symbol-related asset when repayable | passed |
| AC-MB-005 | `repay_all` executes account-wide repayment flow | policy payload (`total_repaid`, per-asset statuses) | Binance history shows multi-asset repay attempts/results | passed |
| AC-MB-006 | Observability is sufficient for operations and agent post-analysis | execution report includes IDs/timestamps/paths/failure classes | operator can follow exact Binance verification path | passed |

## Failure Classification
| Classification | Definition | Required Action |
| --- | --- | --- |
| actionable | Recoverable via approved API/operator actions | remediate once, capture evidence, retry once |
| force_majeure | Third-party/account restriction not solvable in run | mark blocked/skipped with exact blocker |
| hard_fail | Required capability fails with no acceptable evidence | stop and reopen dev demand |

## Review
- Reviewed by User: pre-authorized by latest instruction to proceed without further confirmation
- Approved version/date: v1, 2026-05-14
- Change history:
  - v1 created for live repay policy acceptance
