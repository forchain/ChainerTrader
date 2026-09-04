---
skill_id: blackbox-acceptance-orchestrator
skill_run_root: docs/acceptance/blackbox-orchestrator/20260720-registration-toggle
workflow_id: 20260720-registration-toggle
source_contract: docs/acceptance/blackbox-orchestrator/20260720-registration-toggle/acceptance-contract.md
mode: existing implementation acceptance
system_under_test: ChainerTrader public user-registration toggle
---

# Acceptance Contract

## Goal

Validate the user-visible configuration that enables or disables public user registration. The default behavior must remain enabled; an operator must be able to disable registration through documented environment or CLI configuration without affecting existing-user login or administrator bootstrap.

## Scope

- `TRADER_REGISTRATION_ENABLED` environment configuration and documented CLI overrides.
- Public `/register` and `/login` HTML behavior when registration is enabled or disabled.
- Rejection of registration submissions while disabled.
- Preservation of existing-user login and administrator bootstrap semantics.

## Non-Goals

- Load, security penetration, accessibility, or visual-design testing.
- Real exchange connectivity or live trading.
- Database internals beyond externally observable user/account behavior.

## Roles

- User: approve this contract and any exception or final non-acceptance.
- Project Manager / Orchestrator: maintain artifacts, enforce gates, route testing, and issue the verdict.
- Development Agent: implementation already exists; allocate only for an acceptance failure requiring a product change.
- Testing Agent: independently execute only the approved public CLI, HTTP, documentation, and operator-visible output checks.

## Resources And Preconditions

- Environment: local ChainerTrader worktree with prepared `.venv`; no network required.
- Accounts / permissions: local test-only bootstrap admin and an existing normal user created through documented registration flow.
- Credentials / config: non-secret test credentials supplied only through process environment or form data; no production credentials.
- External systems: none.
- Data / DB access: only through the running application's documented login/registration behavior; no source or private state inspection.
- Safety limits: use isolated temporary database/process; create no external users, orders, or third-party resources.

## Acceptance Gates

| ID | Capability | Required Evidence | Human-Visible Proof | Status |
| --- | --- | --- | --- | --- |
| AC-001 | Default/enabled registration surface | CLI/config output and HTTP responses | `/register` form and login-page registration link are visible; valid registration redirects to login | pending |
| AC-002 | Disabled registration surface | CLI/config output and HTTP responses | `/register` shows the closure message, hides the form/link, and POST returns 403 without creating a user | pending |
| AC-003 | Existing-user and admin continuity | HTTP login/bootstrap responses | Existing user can still log in while registration is disabled; configured bootstrap admin remains usable | pending |
| AC-004 | Operator documentation consistency | README, example env, user manual, CLI help excerpts | Operator can identify the env variable and both CLI overrides, including default behavior | pending |

## Failure Classification

| Classification | Definition | Required Action |
| --- | --- | --- |
| actionable | A public check can be safely corrected through the approved local configuration or retry | Remediate once, record evidence, retry once |
| force_majeure | Required local resource or runtime cannot be recovered in this run | Mark only affected objective skipped, continue independent checks |
| hard_fail | Required user-visible capability fails after allowed remediation | Reopen affected gate and stop acceptance |

## Review

- Reviewed by User: approved in chat on 2026-07-20
- Approved version/date: v1 / 2026-07-20 Asia/Shanghai; degraded non-independent execution explicitly approved by User
- Change history: 2026-07-20 initial contract; 2026-07-20 user-approved degraded black-box exception after independent Testing Agent timeouts
