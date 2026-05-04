#!/usr/bin/env bash
# tests/test_setup_worktree.sh - Automated test for setup_worktree.sh

set -euo pipefail

MAIN_DIR=$(mktemp -d -t test_setup_worktree_main.XXXXXX)
MAIN_DIR=$(cd "$MAIN_DIR" && pwd -P)
WORKTREE_DIR=$(mktemp -d -t test_setup_worktree_wt.XXXXXX)
SCRIPT_SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/scripts/setup_worktree.sh"

cleanup() {
    rm -rf "$MAIN_DIR" "$WORKTREE_DIR"
}
trap cleanup EXIT

echo "=> Setting up mock main repository at $MAIN_DIR"
cd "$MAIN_DIR"
git init >/dev/null

# Mock essential files
mkdir -p scripts
cp "$SCRIPT_SRC" scripts/setup_worktree.sh
chmod +x scripts/setup_worktree.sh

# Create the main dependencies
mkdir -p .venv/bin
touch .venv/bin/python
chmod +x .venv/bin/python

# Create check_runtime_context.py skeleton to avoid syntax errors
cat << 'EOF' > scripts/check_runtime_context.py
#!/usr/bin/env python
import sys
sys.exit(0)
EOF

cat << 'EOF' > Makefile
install:
	mkdir -p .venv/bin
	printf '%s\n' '#!/usr/bin/env bash' 'if [ "$${1:-}" = "--version" ]; then echo "Python 3.test"; exit 0; fi' 'exit 0' > .venv/bin/python
	chmod +x .venv/bin/python
EOF

touch .env
git add Makefile scripts/ .env
git commit -m "Initial commit" >/dev/null

echo "=> Creating test worktree at $WORKTREE_DIR"
git worktree add "$WORKTREE_DIR" >/dev/null

echo "=> Running setup_worktree.sh inside the worktree"
cd "$WORKTREE_DIR"
bash scripts/setup_worktree.sh

echo "=> Verifying outputs"
if [ ! -L .cache ]; then
    echo "FAIL: .cache is not a symlink"
    exit 1
fi

if [ ! -L reports ]; then
    echo "FAIL: reports is not a symlink"
    exit 1
fi

if [ ! -L tmp ]; then
    echo "FAIL: tmp is not a symlink"
    exit 1
fi

CACHE_TARGET=$(readlink .cache)
REPORTS_TARGET=$(readlink reports)
TMP_TARGET=$(readlink tmp)

if [ "$CACHE_TARGET" != "$MAIN_DIR/.cache" ]; then
    echo "FAIL: .cache symlink points to $CACHE_TARGET, expected $MAIN_DIR/.cache"
    exit 1
fi

if [ "$REPORTS_TARGET" != "$MAIN_DIR/reports" ]; then
    echo "FAIL: reports symlink points to $REPORTS_TARGET, expected $MAIN_DIR/reports"
    exit 1
fi

if [ "$TMP_TARGET" != "$MAIN_DIR/tmp" ]; then
    echo "FAIL: tmp symlink points to $TMP_TARGET, expected $MAIN_DIR/tmp"
    exit 1
fi

echo "=> Test passed: Shared directories symlinked correctly."
exit 0
