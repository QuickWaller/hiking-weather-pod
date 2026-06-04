#!/usr/bin/env bash
# agent-propose.sh — the bot's one-shot "draft a change for review" flow.
#
# Run from the bot's workspace clone (~/agent-work). It:
#   1. syncs to the latest origin/main,
#   2. creates/updates branch agent/<slug>,
#   3. commits whatever the bot edited (or an empty commit for a diagnosis-only handoff),
#      with the handoff note as the commit message,
#   4. pushes the branch and prints the PR-compare URL + the note to relay to the human.
#
# The bot NEVER pushes to main — only agent/* branches. A human (with Opus) reviews and merges;
# deploy to the live tree is a separate admin step (deploy-live.sh).
#
# Usage (handoff note on stdin):
#   ~/agent-work/pod-ml/hermes/agent-propose.sh era5-400-fix <<'NOTE'
#   ERA5 2010-09/10/12 fail with HTTP 400. Logs show <evidence>. Proposed fix: <what>.
#   NOTE
set -euo pipefail

SLUG="${1:?usage: agent-propose.sh <slug>   (handoff note on stdin)}"
[[ "$SLUG" =~ ^[a-z0-9][a-z0-9-]*$ ]] || { echo "slug must be lowercase-kebab" >&2; exit 2; }
BR="agent/${SLUG}"

# repo root = two levels up from pod-ml/hermes/
ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)"
cd "$ROOT"

NOTE="$(cat)"
[ -n "$NOTE" ] || { echo "refusing: empty handoff note (pipe a description on stdin)" >&2; exit 2; }

git fetch origin --quiet
git checkout -B "$BR" origin/main --quiet
git add -A
git commit --no-verify --allow-empty -q -m "agent: ${SLUG}" -m "$NOTE"
git push -u origin "$BR" --quiet

URL="$(git remote get-url origin)"; URL="${URL%.git}"; URL="${URL/git@github.com:/https://github.com/}"
echo "PUSHED: $BR"
echo "REVIEW (open PR): ${URL}/compare/main...${BR}?expand=1"
echo "---- relay this to the user on Telegram: ----"
echo "Drafted ${BR}. ${NOTE}"
