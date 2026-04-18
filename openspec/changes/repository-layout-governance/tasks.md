## 1. Governance Foundation

- [ ] 1.1 Add OpenSpec artifacts for `repository-layout-governance`
- [ ] 1.2 Add `docs/architecture/repository-layout.md`
- [ ] 1.3 Update root `AGENTS.md` with repository layout rules and worktree refactor policy
- [ ] 1.4 Add directory-level `AGENTS.md` files for `configs/`, `scripts/`, `tests/`, and `src/trader/`

## 2. Automated Guardrails

- [ ] 2.1 Add a repository layout checker
- [ ] 2.2 Add automated tests for allowed and rejected paths
- [ ] 2.3 Integrate the checker into `make lint`

## 3. Config Asset Migration

- [ ] 3.1 Create `configs/tasks/...` and `configs/notices/...`
- [ ] 3.2 Move task and notice JSON assets from `scripts/` into `configs/`
- [ ] 3.3 Update docs, shell helpers, and tests to use the new config paths
- [ ] 3.4 Preserve direct file-path parsing behavior for migrated configs

## 4. Verification

- [ ] 4.1 Verify the checker rejects new `scripts/*.json` files
- [ ] 4.2 Verify migrated config files still parse and expand correctly
- [ ] 4.3 Verify lint and focused regression tests pass in the worktree
- [ ] 4.4 Document any remaining compatibility gaps for later script-refactor work
