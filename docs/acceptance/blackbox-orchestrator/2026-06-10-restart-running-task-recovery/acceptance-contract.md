---
skill_id: blackbox-acceptance-orchestrator
skill_run_root: docs/acceptance/blackbox-orchestrator/2026-06-10-restart-running-task-recovery
workflow_id: 2026-06-10-restart-running-task-recovery
source_contract: docs/acceptance/blackbox-orchestrator/2026-06-10-restart-running-task-recovery/acceptance-contract.md
status: approved
---

# Acceptance Contract

## Goal

Verify that a user-owned running task remains running after a server restart.

The accepted user-visible outcome is:

- A non-admin user creates a running task through the normal authenticated product surface.
- The server process is restarted through the normal operator workflow.
- After restart, the same task identity remains visible as running through the public product surface.
- Recovery must represent actual runtime recovery, not only a persisted state field change.

## Scope

The system under test is a real local ChainerTrader server started through the normal product entry point with session authentication enabled.

The acceptance run may use:

- the public login flow
- the public task creation API
- the public task listing and live-monitor APIs
- normal operator server restart commands

Database inspection is not part of the pass gate for this workflow because the acceptance claim is black-box and user-visible.

## Required Resources

- Working local server startup through `make serve`
- Valid bootstrap admin credentials from the configured environment
- One non-admin test account with login credentials
- One runnable task config that reaches `RUNNING`
- If the chosen task is a live `TRADER` task, the required user-owned Binance credential and service key must already be valid

## Safety Gate

This workflow must avoid placing unintended real orders.

Preferred acceptance mode:

- use a user-owned safe live task that can reach `RUNNING` without creating real exchange orders, or
- use the same existing `test` account/task path that the User used to report the bug, if that path is already approved and understood

If the only reproducible path can place real orders, stop and ask for explicit approval before executing it.

## Pass Gates

AC-1: The server starts and a non-admin user can authenticate through the public login flow.

AC-2: The selected user can create exactly one task that reaches `RUNNING` through the public task API.

AC-3: Before restart, the running task is externally observable through the public task surface with a concrete `task_id`.

AC-4: After a normal server restart, the server becomes available again without a recovery crash.

AC-5: After restart, the same `task_id` remains externally observable as running. It must not transition to `DONE` merely because of restart recovery.

AC-6: The observed post-restart running state must correspond to actual runtime recovery. Evidence must show the task remains on the running task surface after restart, not only in historical completed results.

## Non-Goals

- Proving strategy profitability
- Proving every task type
- Proving multi-user concurrency in this workflow
- Proving exchange-specific order semantics

## Failure Classification

- Product defect: the task becomes `DONE`, disappears from the running surface, receives a new identity without preserving the original observable task, or the server fails recovery on restart
- Acceptance harness gap: the harness cannot authenticate, create the task, restart the server, or observe task state through public surfaces
- External dependency gap: exchange/network/credential state prevents a reproducible running task from being created

## Roles

- Project Manager: this orchestrator
- Development Agent: already completed implementation on the current branch
- Testing Agent: black-box execution against the running product surface

## Approval Status

Approved by the User for black-box execution.
