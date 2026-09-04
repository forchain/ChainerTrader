# Testing Checklist: Live Margin Borrow Repay Policy Verification

## Skill Binding Metadata
- skill_id: blackbox-acceptance-orchestrator
- workflow_id: 2026-05-14-margin-borrow-repay-live-acceptance
- skill_run_root: docs/acceptance/blackbox-orchestrator/2026-05-14-margin-borrow-repay-live-acceptance/
- source_contract: docs/acceptance/blackbox-orchestrator/2026-05-14-margin-borrow-repay-live-acceptance/acceptance-contract.md

## Rules
- Black-box only: use CLI output, API return payload, and externally verifiable account/order snapshots.
- Every status must carry timestamped evidence.
- Status values: `pending`, `in_progress`, `passed`, `failed`, `blocked`, `reopened`, `skipped_force_majeure`.

| ID | Linked Acceptance Gate | Purpose | Setup | Black-Box Steps | Expected Observable Result | Evidence To Capture | Failure Handling | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TEST-MB-001 | AC-MB-001 | Determine initial branch condition | load env, init cross-margin client | read liabilities/open orders/maxBorrowable | structured precheck snapshot generated | `/tmp/margin_borrow_repay_live_acceptance.json` | blocked if auth/env missing | passed |
| TEST-MB-002 | AC-MB-002 | If liabilities exist, run cleanup branch | TEST-MB-001 indicates liabilities>0 | execute repay/cancel cleanup once, then resnapshot | liability decreases or clear status returned | before/after liabilities and cleanup payload | actionable retry once | passed |
| TEST-MB-003 | AC-MB-003 | If liabilities absent, induce borrow then repay | TEST-MB-001 liabilities=0 | create tiny borrow, run repay, resnapshot | borrow and repay both observable | borrow payload + repay payload + final snapshot | blocked if borrow endpoint unavailable | blocked |
| TEST-MB-004 | AC-MB-004 | Validate `repay_single` behavior | cross-margin + symbol BTC-USDT | call `auto_repay_for_borrow_block("BTC-USDT")` | returns policy payload with per-asset result rows | raw policy payload | if not supported => failed | passed |
| TEST-MB-005 | AC-MB-005 | Validate `repay_all` behavior | cross-margin + caps configured | call `auto_repay_all_liabilities_for_borrow_block(...)` | returns policy=repay_all and account-wide rows | raw policy payload including total_repaid | if capped/no free funds => record skipped reasons | passed |
| TEST-MB-006 | AC-MB-006 | Ensure report observability completeness | all prior tests complete | audit report fields | report includes IDs/time/verification paths/exceptions | completed report sections | missing fields => reopened | passed |

## Execution Constraints
- Allowed commands/interfaces: local `uv run python`, project exchange adapters, Binance API.
- Disallowed observations: source internals as pass criteria.
- External side-effect limits: tiny amounts, single symbol, one retry per actionable blocker.
- Retry/remediation limits: cleanup and repay retries at most once per failed step.

## Result Summary
| Test ID | Start Time | End Time | Result | Evidence Location | Notes |
| --- | --- | --- | --- | --- | --- |
| TEST-MB-001 | 2026-05-14 22:46:39 | 2026-05-14 22:46:48 | passed | `/tmp/margin_borrow_repay_live_acceptance.json` | existing liabilities branch selected |
| TEST-MB-002 | 2026-05-14 22:46:48 | 2026-05-14 22:46:56 | passed | `/tmp/margin_borrow_repay_live_acceptance.json` | open order canceled + partial liability reduction |
| TEST-MB-003 | 2026-05-14 22:46:56 | 2026-05-14 22:46:56 | blocked | `/tmp/margin_borrow_repay_live_acceptance.json` | branch precondition not met in this run |
| TEST-MB-004 | 2026-05-14 22:46:49 | 2026-05-14 22:46:50 | passed | `/tmp/margin_borrow_repay_live_acceptance.json` | repay_single USDT repay success (`tranId=371681649312`) |
| TEST-MB-005 | 2026-05-14 22:46:50 | 2026-05-14 22:46:56 | passed | `/tmp/margin_borrow_repay_live_acceptance.json` | repay_all executed account-wide scan and repayment attempts |
| TEST-MB-006 | 2026-05-14 22:49:10 | 2026-05-14 22:51:00 | passed | this report + checklist | evidence fields complete |
