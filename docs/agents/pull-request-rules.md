# Pull Request Rules

Repository-wide rules for opening pull requests. These apply to humans and to every
agent working in this repository.

## Branch naming is mandatory

A pull request's head branch MUST be named `<type>/<kebab-slug>`:

| Type | Use for |
| --- | --- |
| `feat/<slug>` | new behaviour |
| `fix/<slug>` | bug fixes |
| `refactor/<slug>` | structural changes with no behaviour change |
| `chore/<slug>` | tooling, dependencies, housekeeping |
| `docs/<slug>` | documentation only |
| `test/<slug>` | test-only changes |

The slug is a short kebab-case description of the change, for example
`fix/hexagonal-test-docs-sync` or `feat/spot-order-semantics`.

## Hard rules

- **Never open a pull request from a temporary or environment-specific branch name**:
  no `butterflyray`, `langostino`, `ticket/01-foundation`, `merge/94-...`, `main`, or
  `dev`. Those are worktree or scratch names, not deliverable names.
- **Rename the branch before creating the PR**, and push the renamed branch. The PR head
  name must be the final name - renaming afterwards is the wrong order.
- **On GitHub, renaming a branch that an open PR points at deletes the old ref and
  closes that PR**, and the API refuses to reopen it
  (`state cannot be changed. The <branch> branch has been deleted`). Rename first, then
  open the PR.
- The base branch is `main`.
- The PR body follows the `pr` skill template: `Summary` / `Evidence` / `Merge Danger`.
- The PR body must contain one `Closes #<n>` line for every issue it resolves, so
  GitHub closes them on merge. **Never close an issue by hand** - the PR is the thing
  that closes it.

## Check before opening

```bash
git branch --show-current                    # must match <type>/<kebab-slug>
gh pr list --state open --json headRefName   # head branch must already be the final name
```

## Related

- `docs/agents/issue-tracker.md` - the issue tracker and `gh` conventions.
- `docs/agents/triage-labels.md` - triage label vocabulary.
- `docs/agents/test-retirement-log.md` - the 60-second per-test budget and retirement ledger.
