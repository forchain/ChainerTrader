# AGENTS.md

Repository-wide instructions for coding agents working in this project.

## Worktree Environment Recovery

If you are operating inside a git worktree, restore the shared development environment before running other repository commands that depend on Python or `.env` values.

Trigger this recovery when both conditions are true:

```bash
[ -f .git ] && [ ! -d .venv ]
```

When the trigger matches, run:

```bash
bash scripts/setup_worktree.sh
```

Rules:
- Only do this in a git worktree. In the main repo, the script safely exits without changes.
- Run the recovery before other repository operations that expect Python, `uv`, or `.env` variables to work.
- The script is idempotent, so it is safe to re-run if the environment still looks broken.
- If the script fails, stop and surface the error before continuing with Python-dependent work.

This script creates `.venv` and `.env` symlinks back to the main repository so worktree sessions can use the shared environment without re-installing dependencies.

The script also supports runtime-context validation profiles:

```bash
bash scripts/setup_worktree.sh --profile base
bash scripts/setup_worktree.sh --profile db-backtest
bash scripts/setup_worktree.sh --profile optimization
```

## Context Completeness Gate

Before running tests, backtests, optimization jobs, or data-preparation flows, verify that the runtime context is complete for the task at hand.

Rules:
- Do not assume that `.env` being present means the required configuration is complete.
- Do not silently skip configuration-dependent paths and continue with a weaker fallback if that would invalidate the user's requested workflow.
- If required config, data coverage, or external connectivity is missing, stop and surface the exact missing prerequisite before continuing.

Minimum checks:
- For any Python-based task: confirm the worktree environment recovery step has already succeeded.
- For DB-backed or auto-download backtests: run `bash scripts/setup_worktree.sh --profile db-backtest` and verify the effective environment actually provides the required DB / exchange settings, not just a symlinked `.env`.
- For CSV-backed backtests: verify the required symbols, intervals, and time ranges are actually covered by local files before launching the run.
- For optimization / batch backtests: run `bash scripts/setup_worktree.sh --profile optimization` and verify the requested sample matrix is executable end-to-end before starting the full run.

When context is incomplete:
- Explain what is missing in concrete terms, for example missing `TRADER_DB`, missing `TRADER_EXCHANGE`, missing Binance credentials, or missing CSV coverage for specific symbols / intervals / date ranges.
- Prefer using `scripts/check_runtime_context.py` / `scripts/setup_worktree.sh --profile ...` to validate `.env` via `python-dotenv` before assuming values are missing.
- Prefer checking whether the shared main-repo environment is incomplete before assuming the worktree recovery failed.
- Ask the user to补充配置 or explicitly approve an alternative execution plan if the original workflow cannot be honored.
- Do not proceed with partial execution that would make the reported optimization / test result misleading.

## Framework-First Fix Policy

When debugging or implementing behavior changes, prefer fixing the shared framework layer before patching individual strategies.

Rules:
- First ask whether the issue originates from a shared contract, lifecycle, routing rule, state machine, or execution path that applies to multiple strategies.
- If the behavior belongs to the framework, for example signal routing, mode handling, trade lifecycle orchestration, confirmation flow, or shared metadata propagation, fix it in the framework layer.
- Only fix the strategy layer when the behavior is truly strategy-specific or when the framework cannot reasonably express the required behavior without creating a worse abstraction.
- Do not choose a strategy-local workaround merely because it makes the current failing case pass if the underlying defect is reusable across strategies.
- When a strategy-layer fix is chosen, explicitly explain why a framework-layer fix is not appropriate or not feasible.

## Testing Policy

Testing expectations are repository-wide rules for all implementation work, not just a per-conversation preference.

Rules:
- Treat test strategy as part of the implementation workflow from proposal through verification, not as a final optional step.
- Default to test-driven development for code changes whenever the behavior can be exercised automatically.
- Prefer automated tests over manual testing unless blocked by a concrete external limitation.
- If a proposed or implemented change cannot be covered by reliable automated tests, explicitly say so and explain why.
- Do not claim a fix, feature, or refactor is complete without stating what was verified and how.

Required disclosure:
- State which automated tests were added or run.
- State when a check is only an external smoke test, manual validation, or a one-off investigation rather than a stable automated test.
- State when a third-party dependency, missing credential, unavailable environment, UI interaction, or tool-access limitation prevents full automation.
- State any residual gap between the intended behavior and what the existing tests actually prove.

Practical guidance:
- For pure logic, state machines, scheduling, parsing, reporting, and database-adapter behavior, assume automated tests are expected.
- For external API semantics, network behavior, permissions, or unstable third-party integrations, keep the core logic under automated tests and separately label any non-deterministic verification.
- If manual participation from the user is required, ask only for the specific missing step and explain why automation is not sufficient or not possible in the current environment.
