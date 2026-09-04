## Why

ChainerTrader currently mixes task configuration JSON, Python utility entry points, and operational shell scripts inside `scripts/`. This makes the repository harder to navigate, encourages future changes to land in the wrong place, and forces some tests to depend on script-layer modules rather than stable application modules.

The project already has strong runtime and testing discipline, but it lacks explicit repository-layout rules and automated guardrails. Without those, even a one-time cleanup would gradually regress as new agents and contributors continue to add files by convenience instead of by responsibility.

This change establishes a durable repository layout policy, migrates configuration assets into a dedicated `configs/` tree, and adds automated checks so future changes follow the intended structure.

## What Changes

- add repository layout documentation and explicit file-placement rules
- extend root and directory-level `AGENTS.md` guidance for future agents
- add an automated repository layout checker and wire it into linting
- migrate task and notice JSON assets from `scripts/` into `configs/`
- update docs, examples, and tests to reference the new configuration locations
- define structural repository refactors as worktree-only changes

## Capabilities

### New Capabilities
- `repository-layout-rules`: define durable directory responsibilities and placement rules
- `repository-layout-guardrails`: automatically reject new files in deprecated locations
- `task-config-asset-layout`: store task and notice configuration assets in dedicated directories

### Modified Capabilities
- `agent-repository-guidance`: teach agents where new files should be added
- `development-worktree-policy`: require isolated worktrees for structural refactors

## Impact

- `AGENTS.md`
- `CLAUDE.md`
- `docs/architecture/`
- `configs/`
- `scripts/`
- `tests/`
- `Makefile`
