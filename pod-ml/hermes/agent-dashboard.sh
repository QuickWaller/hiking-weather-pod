#!/usr/bin/env bash
# agent-dashboard.sh — commit a dashboard change directly to main and deploy it live.
#
# Unlike agent-propose.sh (which creates a PR branch for review), dashboard edits skip
# the review gate and deploy immediately. This is deliberate — dashboard_server.py is
# display-only code; a bad edit doesn't touch data or downloads. The commit is still
# tracked in git so every change is visible and reversible.
#
# Workflow:
#   cd ~/agent-work
#   git fetch origin && git checkout main && git reset --hard origin/main  # sync first
#   # ... edit pod-ml/scripts/dashboard_server.py ...
#   pod-ml/hermes/agent-dashboard.sh <short-slug> <<'NOTE'
#   What changed and why.
#   NOTE
#
# ONLY edits to dashboard_server.py go through this script. Everything else still
# uses agent-propose.sh + PR. If you accidentally staged other files, this will
# error rather than silently commit them.

set -euo pipefail

SLUG="${1:?Usage: agent-dashboard.sh <short-slug>   (reads commit message from stdin)}"
MSG="$(cat)"

AGENTWORK="$(git rev-parse --show-toplevel 2>/dev/null)" \
  || { echo "agent-dashboard: not inside a git repo" >&2; exit 2; }
PODCTL="$AGENTWORK/pod-ml/scripts/podctl"
DASHBOARD_FILE="pod-ml/scripts/dashboard_server.py"

# Must be on main — never commit to a feature branch with this script
branch="$(git rev-parse --abbrev-ref HEAD)"
[ "$branch" = main ] || {
  echo "agent-dashboard: currently on branch '$branch', not main." >&2
  echo "  Run: git checkout main && git reset --hard origin/main  then re-apply your edits." >&2
  exit 2
}

# Stage only the dashboard file
git add "$DASHBOARD_FILE"

# Refuse if nothing changed
if git diff --cached --quiet; then
  echo "agent-dashboard: no staged changes to $DASHBOARD_FILE" >&2
  exit 1
fi

# Guard: abort if anything OTHER than the dashboard file is staged
extra="$(git diff --cached --name-only | grep -v "^$DASHBOARD_FILE$" || true)"
if [ -n "$extra" ]; then
  echo "agent-dashboard: unexpected staged files (use agent-propose.sh for non-dashboard changes):" >&2
  echo "$extra" >&2
  exit 2
fi

git commit -m "dashboard: ${SLUG}

${MSG}

[agent-dashboard — direct to main, no PR]"

# Push straight to main — skips PR review (dashboard-only privilege)
git push origin main

echo "Pushed to main. Deploying to live tree..."
"$PODCTL" dashboard deploy

echo ""
echo "Done. Dashboard is live with: dashboard: ${SLUG}"
