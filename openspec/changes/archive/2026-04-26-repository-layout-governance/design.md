## Context

ChainerTrader's product code is already concentrated under `src/trader/`, but the repository edge is blurred:

- `scripts/*.json` holds task and notice configuration assets
- `scripts/*.py` mixes wrappers with reusable logic
- `scripts/*.sh` holds operational helpers
- some tests directly import script-layer modules

This layout works in the short term but provides weak guidance for future changes. Contributors and agents can keep adding assets to `scripts/`, because that is the current path of least resistance.

## Goals / Non-Goals

**Goals**
- define clear directory responsibilities for code, config, scripts, docs, and tests
- move configuration assets into a dedicated `configs/` tree
- add explicit repository-layout guidance for future agents
- add automated guardrails that reject newly introduced layout violations
- keep existing task-parsing behavior intact while config paths move

**Non-Goals**
- do not rewrite core trading or backtesting logic
- do not fully refactor every existing Python script in the first batch
- do not require a CI platform migration as part of this change
- do not eliminate shell scripts that still serve clear operational purposes

## Decisions

### Decision 1: Introduce a dedicated `configs/` tree

**Choice**: Store task JSON under `configs/tasks/...` and notice JSON under `configs/notices/...`.

**Rationale**: Configuration assets are not scripts. Giving them their own tree removes ambiguity and creates an obvious default location for future additions.

### Decision 2: Keep `scripts/` for operations and thin wrappers only

**Choice**: `scripts/` remains valid, but only for operational shell scripts and thin Python wrappers.

**Rationale**: The directory still has value for repo operations, but it should not remain the default home for new configuration assets or reusable logic.

### Decision 3: Use directory-level `AGENTS.md` files

**Choice**: Add local `AGENTS.md` files for `configs/`, `scripts/`, `tests/`, and `src/trader/`.

**Rationale**: Future agents are more likely to follow local rules they encounter at the point of modification than only a root-level global rule set.

### Decision 4: Add an automated repository layout checker

**Choice**: Create a lightweight checker that validates file-placement rules and run it from `make lint`.

**First-batch hard rules**
- new task or notice JSON must live under `configs/`
- new JSON files are not allowed under `scripts/`
- generated artifacts are not allowed under `tests/output/`

**Rationale**: Documentation alone will not prevent regression. The repository needs an automated barrier.

### Decision 5: Structural refactors must happen in git worktrees

**Choice**: Any multi-directory migration or repository-layout change must be executed in a dedicated git worktree.

**Rationale**: Layout refactors touch many paths at once and should not be mixed into the main workspace.

## Target Layout

```text
repo/
├── src/trader/
│   └── ...
├── configs/
│   ├── tasks/
│   │   ├── backtests/
│   │   ├── downloads/
│   │   ├── examples/
│   │   └── optimizations/
│   └── notices/
├── scripts/
│   ├── ops/
│   └── wrappers/
├── tests/
│   └── ...
└── docs/architecture/
```

## Migration Plan

### Phase 0: Governance Foundation
- add OpenSpec artifacts
- add repository-layout documentation
- update root and directory-level `AGENTS.md`
- add the repository layout checker

### Phase 1: Config Asset Migration
- create `configs/tasks/...` and `configs/notices/...`
- move existing JSON assets out of `scripts/`
- update docs, scripts, and tests to reference the new paths

### Phase 2: Script Logic Refactor
- move reusable script logic into `src/trader/tools` or `src/trader/cli`
- keep script entry points as thin wrappers where needed

### Phase 3: Test Boundary Cleanup
- reduce direct test dependencies on script-layer modules
- keep generated artifacts out of committed test paths

## Risks / Trade-offs

- documentation and helper scripts may lag if path updates are missed
- some legacy usage may still expect old paths, so migration must be deliberate
- a too-strict checker could block legitimate edge cases, so the first version should stay focused and explicit

## Rollback / Compatibility

- the first batch only changes config asset locations and governance rules
- behavior of `parse_task_config()` remains unchanged for direct file paths and inline JSON
- deeper Python script refactors are deferred to later batches to reduce risk
