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
