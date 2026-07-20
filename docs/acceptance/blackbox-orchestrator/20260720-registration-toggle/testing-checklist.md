---
skill_id: blackbox-acceptance-orchestrator
workflow_id: 20260720-registration-toggle
skill_run_root: docs/acceptance/blackbox-orchestrator/20260720-registration-toggle
source_contract: docs/acceptance/blackbox-orchestrator/20260720-registration-toggle/acceptance-contract.md
---

# Testing Checklist

This contract is governed by blackbox-acceptance-orchestrator.

## Rules

- Testing Agent uses only this checklist, public setup instructions, documented UI/CLI/HTTP interfaces, and operator-visible output.
- Testing Agent must not inspect source, diffs, private implementation state, test mocks, or Development Agent reasoning.
- Each result must include externally verifiable evidence and an exact human verification path.

| ID | Linked Acceptance Gate | Purpose | Setup | Black-Box Steps | Expected Observable Result | Evidence To Capture | Failure Handling | Status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| TEST-001 | AC-001 | Prove default/enabled registration behavior | Start isolated app with no registration override and temporary DB | Request `/login` and `/register`; submit a valid unique username/password | Both pages return 200 HTML; login page links to `/register`; registration redirects to `/login` | Timestamp/timezone, process config, URLs/statuses, redirect location, unique test username, response excerpts | Classify; remediate configuration once and retry once | passed |
| TEST-002 | AC-002 | Prove disabled registration is enforced at UI and POST boundary | Start isolated app with `TRADER_REGISTRATION_ENABLED=false` and temporary DB | Request `/login` and `/register`; POST valid registration; retry login with the attempted new account | Register page shows closure message and no form; login hides register link; POST returns 403; attempted account cannot log in | Timestamp/timezone, env/CLI invocation, URLs/statuses, closure text, absence/presence checks, attempted username | Read failure-remediation guidance; stop if public registration remains possible | passed |
| TEST-003 | AC-003 | Prove existing users and bootstrap admin are unaffected | Start isolated app with bootstrap admin and pre-create one normal user through enabled flow, then restart disabled | Login as normal user and admin while disabled; request authenticated landing page | Both existing accounts authenticate successfully; no registration requirement blocks them | Timestamp/timezone, account scope (test-only), login statuses, redirect targets, authenticated page status | Classify as hard failure if existing login is blocked; no production retry | passed |
| TEST-004 | AC-004 | Prove operator-facing configuration documentation is discoverable | Current worktree and documented CLI | Read README, `example.env`, `docs/user-manual.md`; run `python -m trader --help` | All docs name `TRADER_REGISTRATION_ENABLED`, default-on behavior, and both CLI overrides; help lists flags | Timestamp/timezone, exact paths/lines or command excerpts, observed strings | Classify documentation mismatch as actionable and retry once after approved remediation | passed |

## Execution Constraints

- Allowed commands/interfaces: documented `python -m trader` CLI/help, local HTTP routes `/login`, `/register`, authenticated pages, and reading user-facing docs.
- Disallowed observations: source code, git diff, private app state, mocks, internal database tables, implementation notes, or test-only hooks.
- External side-effect limits: isolated temporary process/database only; no network, exchange, email, orders, or permanent accounts.
- Retry/remediation limits: one local configuration/setup remediation and one retry per failed item; no code changes during this acceptance run.
- Prerequisite dependencies: TEST-001 must pass before TEST-002; TEST-002 must pass before TEST-003; TEST-004 is independent.

## Result Summary

| Test ID | Start Time | End Time | Result | Evidence Location | Notes |
| --- | --- | --- | --- | --- | --- |
| TEST-001 | 2026-07-20 16:14 +0800 | 2026-07-20 16:16 +0800 | passed | execution-report.md | User-approved degraded direct public CLI/HTTP execution. |
| TEST-002 | 2026-07-20 16:16 +0800 | 2026-07-20 16:16 +0800 | passed | execution-report.md | User-approved degraded direct public CLI/HTTP execution. |
| TEST-003 | 2026-07-20 16:16 +0800 | 2026-07-20 16:16 +0800 | passed | execution-report.md | User-approved degraded direct public CLI/HTTP execution. |
| TEST-004 | 2026-07-20 16:17 +0800 | 2026-07-20 16:17 +0800 | passed | execution-report.md | User-approved degraded direct public CLI/docs execution. |
