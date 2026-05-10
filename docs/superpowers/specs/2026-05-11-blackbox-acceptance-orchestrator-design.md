# Design: Black-Box Acceptance Orchestrator Skill

## Overview
Create a reusable Codex skill that orchestrates a small AI-assisted delivery team:

- User: final owner and acceptance gate
- Project manager: coordinator, escalator, and closure owner
- Development agent: implements the requested change
- Testing agent: performs black-box verification and testability review

The skill must work in two modes:

1. New development: generate a development plan and an independent test plan, then delegate work.
2. Existing implementation acceptance: infer the target from context, generate a black-box test plan, then verify readiness and acceptance.

This skill is intended to be reusable across projects. Project-specific test assets and operational knowledge must live outside the skill.

## Goals
- Enforce a real separation between development and testing responsibilities.
- Prefer real sub-agents when the host supports them.
- Keep testing strictly black-box.
- Surface missing test resources early, using low-risk request paths.
- Capture reusable lessons after final user acceptance.

## Non-Goals
- Code review by the testing agent.
- Single-agent role simulation when real sub-agents are available.
- Project-specific knowledge baked into the skill body.
- Unbounded autonomous self-modification of the skill during a run.

## Roles

### User
Final acceptance authority. Reviews the team output and can loop the process if issues remain.

### Main Agent
Owns coordination, escalation, and closure:
- Determine whether the task is new development or existing implementation acceptance.
- Probe for sub-agent support.
- Create and dispatch work to development and testing agents.
- Collect results and present a consolidated status to the user.
- Reopen stalled work when testing or implementation reveals a defect.
- Escalate unresolved questions to the user only when the team cannot resolve them.

### Project Manager
This skill models the main agent as a project manager:
- Split work into actionable tasks.
- Keep the workflow moving without the user acting as a dispatcher.
- Push unresolved issues back into the team when they can be solved internally.
- Escalate only the cases that require user input or project-specific authority.
- Own the final coordination loop until the user accepts the result.

### Development Agent
Owns implementation only:
- Execute the development plan.
- Report completion, blockers, and relevant implementation notes.
- Do not self-validate through a testing role.

### Testing Agent
Owns black-box verification only:
- Build a test plan from observable behavior and task context.
- Run tests as an external tester would.
- Review logs, CLI output, API responses, runtime behavior, and documented interfaces.
- Request missing test resources through low-risk channels.
- Suggest testability improvements such as admin commands, dedicated test APIs, or log cleanup.
- Never perform source-code review.

## Execution Modes

### Mode A: New Development
1. Read prompt and context.
2. Generate a development plan.
3. Generate a separate black-box test plan.
4. Probe for real sub-agent support.
5. If supported, spawn separate development and testing agents.
6. If unsupported, enter degraded single-context mode and label it clearly.
7. After development finishes, hand off to testing.
8. After testing finishes, present results to the user for final acceptance.
9. If accepted, record reusable lessons.

### Mode B: Existing Implementation Acceptance
1. Read context and identify the likely target behavior.
2. Generate a black-box test plan from observable behavior.
3. Probe for real sub-agent support.
4. Spawn or emulate the testing role based on capability.
5. If resources are missing, request them before continuing.
6. Run tests and summarize pass/fail status.
7. Present the result to the user for final acceptance.
8. If accepted, record reusable lessons.

## Sub-Agent Capability Gate
The skill must treat true sub-agent support as a runtime prerequisite, not a preference.

### Required check
The main agent must determine whether the host can actually create independent sub-agents with isolated context.

### If supported
- Use distinct development and testing sub-agents.
- Do not share a single execution context for both roles.
- Keep the main agent in a coordination-only role.

### If unsupported
- Enter degraded mode.
- Preserve the role boundaries as process labels only.
- Explicitly state that context isolation is not guaranteed.
- Do not claim full team-style separation.

## Black-Box Testing Rules
The testing agent must behave like a tester, operator, or product-oriented verifier.

### Allowed inputs
- Logs
- CLI output
- HTTP/API responses
- README and user-facing docs
- Runtime behavior
- Test harness output
- Observed side effects

### Forbidden inputs
- Source-code review
- Implementation reasoning from internal code structure
- Verifying behavior by reading the exact fix and then asserting it

### Required outputs
- Test plan
- Observed results
- Risk or failure summary
- Missing resources or missing testability notes

## Resource Gap Handling
When the testing agent cannot complete black-box verification, it must first emit a concrete gap report.

### Low-risk first
Prefer resource requests that can be satisfied through repository-managed configuration rather than chat-based sensitive value exchange.

Examples:
- API keys placed in `.env` or an existing secret/config path
- Database credentials via existing environment variables
- Environment flags to enable test mode
- Admin commands already exposed by the app
- Dedicated test endpoints or read-only verification APIs
- Log-level or log-format changes that reduce noise

### Request format
Each request must include:
- Missing resource
- Where it should be configured
- Expected format or contract
- Why it matters for test completion
- The next command or action after the resource is provided

### Principle
Do not keep testing with missing prerequisites if the result would be misleading.

## Testability Review
The testing agent is also responsible for assessing whether the project is test-friendly enough.

It may request improvements such as:
- Lower-noise logs
- Less frequent logs
- Admin commands for long-running workflows
- Dedicated test APIs
- Better observability for state transitions
- Deterministic hooks for setup/teardown

These requests are part of testing, not code review.

## Self-Improvement and Memory Boundary
The skill must separate reusable process knowledge from project-specific knowledge.

### Skill-level evolution
Record only reusable workflow improvements:
- Better role separation
- Better capability probing
- Better black-box testing steps
- Better degraded-mode handling
- Better resource request structure

### Project-level accumulation
Store project-specific knowledge outside the skill:
- Required API keys or environment variables
- Database or exchange access assumptions
- Special verification commands
- Project-specific admin commands
- Test helper endpoints
- Logging improvements that were discovered for this project

### Default trigger
After final user acceptance, perform a reflection pass and split findings into:
- Generic reusable workflow updates
- Project-specific test assets

## Acceptance Loop
The user is the final arbiter.

If the user reports a problem after the team has concluded the work:
1. Reopen the task.
2. Re-evaluate from the black-box perspective.
3. Update the development plan or test plan as needed.
4. Repeat until the user accepts the result.

## Escalation Rules
The project manager must escalate only when the team cannot safely continue.

### Escalate to the user when:
- Requirements are ambiguous and cannot be inferred from context.
- Required resources are missing and cannot be satisfied through low-risk configuration.
- Project-specific constraints or domain knowledge are missing.
- Final acceptance still has unresolved disagreement after internal retries.

### Resolve internally when:
- Task splitting is needed.
- Developer and tester need another round.
- Testability improvements can be requested without user input.
- Missing information can be inferred from visible context or existing docs.

## Success Criteria
- The skill can coordinate either new development or existing implementation acceptance.
- The testing agent remains black-box only.
- Missing resources are surfaced as actionable, low-risk requests.
- Real sub-agent support is used when available.
- Degraded mode is explicit when sub-agents are not available.
- Reusable lessons are separated from project-specific assets.
