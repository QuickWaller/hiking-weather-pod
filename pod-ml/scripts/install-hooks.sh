#!/usr/bin/env bash
# Install pod-ml's git hooks into the shared repo's .git/hooks.
# Hooks live in .git (not version-controlled), so re-run this after a fresh clone.
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
src="$ROOT/pod-ml/scripts/pre-commit"
dst="$ROOT/.git/hooks/pre-commit"
cp "$src" "$dst"
chmod +x "$dst"
echo "Installed pre-commit hook -> $dst"
