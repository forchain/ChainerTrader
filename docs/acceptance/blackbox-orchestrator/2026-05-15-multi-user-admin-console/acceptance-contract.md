---
skill_id: blackbox-acceptance-orchestrator
skill_run_root: docs/acceptance/blackbox-orchestrator/2026-05-15-multi-user-admin-console
workflow_id: 2026-05-15-multi-user-admin-console
source_contract: docs/acceptance/blackbox-orchestrator/2026-05-15-multi-user-admin-console/acceptance-contract.md
mode: existing implementation acceptance
system_under_test: ChainerTrader multi-user admin console first phase
---

# Acceptance Contract

## Goal
Validate the first-phase multi-user admin console from externally observable behavior: session login/registration, administrator password reset, account API-key gating, user task isolation, live-monitor isolation, and removal of Basic Auth runtime behavior.

## Scope
- Web login, logout, registration, password change, and forced password-change flow.
- Administrator user management and reset-password flow.
- Normal user account page and exchange API credential behavior.
- HTTP/API task ownership behavior for normal users versus administrators.
- Live-monitor visibility isolation by task owner.
- Operational configuration behavior for `TRADER_SECRET_KEY`, session cookies, and bootstrap admin credentials.
- Documentation and example consistency for the new session-login model.

## Non-Goals
- Real exchange order placement.
- Real Binance API connectivity.
- Visual polish beyond externally visible route/form availability.
- Full browser accessibility audit.
- Performance/load testing.

## Roles
- Project Manager / Orchestrator: maintain this document set, coordinate execution, classify defects, and update the execution report.
- Testing Agent: execute only black-box checks using public HTTP routes, CLI/help output, documentation, generated artifacts, and operator-visible logs/output. The Testing Agent must not inspect source code, diffs, private implementation notes, or internal design details.
- Development Agent: not allocated initially because implementation already exists. Allocate only if acceptance fails due to a product defect.

## Environment Assumptions
- Repository worktree is available locally.
- Python environment is already prepared through the project worktree setup.
- Network is not required for acceptance checks except GitHub PR update if additional commits are produced.
- Tests may use in-process HTTP clients to call the FastAPI app as a black-box product surface.
- The database may be in-memory SQLite if it is exercised only through the product's documented routes and repositories exposed through the running app state.

## Pass / Fail Gates
Required acceptance passes only if all required checklist items pass, or if any skipped item is explicitly marked `skipped_force_majeure` with evidence. Non-force-majeure failure blocks acceptance.

## Failure Classifications
- `hard_fail`: externally visible product behavior violates this contract.
- `acceptance_harness_gap`: the test cannot observe behavior well enough without implying product failure.
- `production_reliability_gap`: the run can continue, but the same condition could break real operation.
- `external_dependency_gap`: missing third-party permission, service, account, or network resource.
- `skipped_force_majeure`: not recoverable in this run, independent checks may continue.

## Required Evidence
Each passed item must record command, timestamp, externally visible path/API, expected result, observed result, and final status in the execution report.
