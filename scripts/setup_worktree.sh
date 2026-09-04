#!/usr/bin/env bash
# setup_worktree.sh — Restore development environment in a git worktree.
#
# Creates symlinks for .venv and .env pointing to the main repo, so that
# uv run and python-dotenv work transparently without re-installing anything.
#
# Usage: bash scripts/setup_worktree.sh
# Safe to run multiple times (idempotent).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── 1. Detect worktree ────────────────────────────────────────────────────────
GIT_PATH="$REPO_ROOT/.git"
if [ ! -f "$GIT_PATH" ]; then
    echo "ℹ  Not in a git worktree ($(basename "$REPO_ROOT") has a .git directory, not a file)."
    echo "   Nothing to do."
    exit 0
fi

# ── 2. Resolve main repo path ─────────────────────────────────────────────────
# .git file content: "gitdir: /abs/path/.git/worktrees/<name>"
GITDIR=$(sed 's/^gitdir: //' "$GIT_PATH")
MAIN_REPO=$(echo "$GITDIR" | sed 's|/\.git/worktrees/.*||')

if [ ! -d "$MAIN_REPO" ]; then
    echo "✗  Could not resolve main repo from '$GITDIR'."
    echo "   Parsed path '$MAIN_REPO' does not exist."
    exit 1
fi

echo "Worktree : $REPO_ROOT"
echo "Main repo: $MAIN_REPO"
echo ""

# ── 3. Symlink .venv ──────────────────────────────────────────────────────────
VENV_TARGET="$MAIN_REPO/.venv"
VENV_LINK="$REPO_ROOT/.venv"

if [ ! -d "$VENV_TARGET" ]; then
    echo "✗  Main repo has no .venv at '$VENV_TARGET'."
    echo "   Run 'make install' in the main repo first, then re-run this script."
    exit 1
fi

if [ -L "$VENV_LINK" ] && [ -d "$VENV_LINK" ]; then
    echo "✓  .venv symlink already set up — skipping."
else
    # Remove broken symlink or stale file if present
    [ -e "$VENV_LINK" ] || [ -L "$VENV_LINK" ] && rm -rf "$VENV_LINK"
    ln -sfn "$VENV_TARGET" "$VENV_LINK"
    echo "✓  Created .venv → $VENV_TARGET"
fi

# ── 4. Symlink .env ───────────────────────────────────────────────────────────
ENV_TARGET="$MAIN_REPO/.env"
ENV_LINK="$REPO_ROOT/.env"

if [ ! -f "$ENV_TARGET" ]; then
    echo "⚠  Main repo has no .env — skipping .env symlink."
    echo "   Copy example.env to $MAIN_REPO/.env and fill in credentials if needed."
else
    if [ -L "$ENV_LINK" ] && [ -f "$ENV_LINK" ]; then
        echo "✓  .env symlink already set up — skipping."
    else
        [ -e "$ENV_LINK" ] || [ -L "$ENV_LINK" ] && rm -f "$ENV_LINK"
        ln -sfn "$ENV_TARGET" "$ENV_LINK"
        echo "✓  Created .env  → $ENV_TARGET"
    fi
fi

# ── 5. Verify ─────────────────────────────────────────────────────────────────
echo ""
PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
if [ -x "$PYTHON_BIN" ]; then
    PYTHON_VER=$("$PYTHON_BIN" --version 2>&1)
    echo "✓  Python available: $PYTHON_VER"
    echo ""
    echo "Environment ready. You can now run: uv run python -m trader -h"
else
    echo "✗  .venv/bin/python not executable via symlink."
    echo "   The symlink was created but the venv may be corrupted."
    exit 1
fi
