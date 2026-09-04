#!/usr/bin/env bash
# setup_worktree.sh — Restore development environment in a git worktree.
#
# Creates symlinks into the main repo: .env, configs/notices/notice.json (if present
# there), data/trader.db, plus shared dirs reports / .cache / tmp — so worktrees share
# credentials, notices, the SQLite DB, and artifacts without re-installing anything.
#
# Usage: bash scripts/setup_worktree.sh [--profile <name>] [--require-env KEY ...]
# Safe to run multiple times (idempotent).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

PROFILE="base"
EXTRA_REQUIRE_ENVS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)
            PROFILE="${2:-}"
            shift 2
            ;;
        --require-env)
            EXTRA_REQUIRE_ENVS+=("${2:-}")
            shift 2
            ;;
        *)
            echo "✗  Unknown argument: $1"
            echo "   Usage: bash scripts/setup_worktree.sh [--profile <name>] [--require-env KEY ...]"
            exit 1
            ;;
    esac
done

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

# ── 3. Symlink .env ───────────────────────────────────────────────────────────
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
    fi
fi

# ── 4. Symlink shared notice config and SQLite DB (main repo) ───────────────
NOTICE_TARGET="$MAIN_REPO/configs/notices/notice.json"
NOTICE_LINK="$REPO_ROOT/configs/notices/notice.json"
mkdir -p "$MAIN_REPO/configs/notices"
mkdir -p "$(dirname "$NOTICE_LINK")"

if [ ! -f "$NOTICE_TARGET" ]; then
    echo "⚠  Main repo has no configs/notices/notice.json — skipping notice symlink."
    echo "   Copy configs/notices/notice.sample.json to $NOTICE_TARGET if needed."
else
    if [ -L "$NOTICE_LINK" ] && [ -f "$NOTICE_LINK" ] && [ "$(readlink "$NOTICE_LINK")" = "$NOTICE_TARGET" ]; then
        echo "✓  notice.json symlink already set up — skipping."
    else
        { [ -e "$NOTICE_LINK" ] || [ -L "$NOTICE_LINK" ]; } && rm -f "$NOTICE_LINK"
        ln -sfn "$NOTICE_TARGET" "$NOTICE_LINK"
        echo "✓  Created configs/notices/notice.json → $NOTICE_TARGET"
    fi
fi

DB_TARGET="$MAIN_REPO/data/trader.db"
DB_LINK="$REPO_ROOT/data/trader.db"
mkdir -p "$MAIN_REPO/data"
mkdir -p "$REPO_ROOT/data"

if [ -L "$DB_LINK" ] && [ "$(readlink "$DB_LINK")" = "$DB_TARGET" ]; then
    echo "✓  data/trader.db symlink already set up — skipping."
else
    if [ -f "$DB_LINK" ] && [ ! -L "$DB_LINK" ]; then
        echo "⚠  Worktree has its own data/trader.db file. Moving to data/trader.db.worktree-backup."
        mv "$DB_LINK" "${DB_LINK}.worktree-backup"
    elif [ -e "$DB_LINK" ] || [ -L "$DB_LINK" ]; then
        rm -rf "$DB_LINK"
    fi
    ln -sfn "$DB_TARGET" "$DB_LINK"
    echo "✓  Created data/trader.db → $DB_TARGET"
fi

# ── 5. Symlink Shared Directories (reports, .cache, tmp) ──────────────────────
SHARED_DIRS=("reports" ".cache" "tmp")
for dir in "${SHARED_DIRS[@]}"; do
    TARGET="$MAIN_REPO/$dir"
    LINK="$REPO_ROOT/$dir"

    [ ! -d "$TARGET" ] && mkdir -p "$TARGET"

    if [ -L "$LINK" ] && [ -d "$LINK" ]; then
        if [ "$(readlink "$LINK")" = "$TARGET" ]; then
            echo "✓  $dir symlink already set up — skipping."
            continue
        fi
    fi

    if [ -d "$LINK" ] && [ ! -L "$LINK" ]; then
        echo "⚠  Worktree has its own '$dir' directory. Moving to '${dir}_backup' to create symlink."
        mv "$LINK" "${LINK}_backup"
    elif [ -e "$LINK" ] || [ -L "$LINK" ]; then
        rm -rf "$LINK"
    fi

    ln -sfn "$TARGET" "$LINK"
    echo "✓  Created $dir  → $TARGET"
done

# ── 6. Verify ─────────────────────────────────────────────────────────────────
echo ""

ensure_local_venv() {
    local venv_dir="$REPO_ROOT/.venv"

    if [ -L "$venv_dir" ]; then
        echo "⚠  Found shared .venv symlink in worktree. Removing it to avoid conflicts."
        rm -rf "$venv_dir"
    fi

    if [ ! -d "$venv_dir" ]; then
        echo "ℹ  Creating worktree-local virtual environment via 'make install'..."
        if ! command -v make >/dev/null 2>&1; then
            echo "✗  'make' not found. Cannot run 'make install' to create .venv."
            exit 1
        fi
        make install
    fi
}

ensure_local_venv

PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
if [ -x "$PYTHON_BIN" ]; then
    PYTHON_VER=$("$PYTHON_BIN" --version 2>&1)
    echo "✓  Python available: $PYTHON_VER"
    echo ""
    CHECK_CMD=("$PYTHON_BIN" "$REPO_ROOT/scripts/check_runtime_context.py" --profile "$PROFILE" --env-file "$REPO_ROOT/.env")
    for key in "${EXTRA_REQUIRE_ENVS[@]}"; do
        CHECK_CMD+=(--require-env "$key")
    done

    echo "Validating runtime context..."
    "${CHECK_CMD[@]}"
    echo ""
    echo "Environment ready. You can now run: uv run python -m trader -h"
else
    echo "✗  '$PYTHON_BIN' is not executable."
    echo "   Your worktree .venv exists but looks incomplete or corrupted."
    exit 1
fi
