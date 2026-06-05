#!/usr/bin/env bash
# deploy-live.sh — ADMIN-ONLY: deploy reviewed+merged origin/main to the LIVE download tree
# and restart affected services. This is the human gate.
#
# Deliberately NOT in hermes-pod-ml's sudo allowlist (which permits only `podctl`), so the bot
# can draft + push but CANNOT deploy itself. An admin runs this after merging a reviewed PR:
#
#   sudo -u claude bash /home/claude/cyber-deck-and-weather-station/pod-ml/scripts/deploy-live.sh [gpm|era5|all|none]
#
# The live tree must be clean (the bot works in its own clone, never here). reset --hard makes
# the live tree exactly origin/main; a restart then makes the running download pick up new code.
set -euo pipefail

REPO="${PODML_REPO_ROOT:-/home/claude/cyber-deck-and-weather-station}"
SVC="${1:-none}"

git -C "$REPO" fetch origin --quiet

if ! git -C "$REPO" diff --quiet || ! git -C "$REPO" diff --cached --quiet; then
  echo "REFUSING: live tree has local changes — investigate before deploying:" >&2
  git -C "$REPO" status --short >&2
  exit 1
fi

echo "Deploying to live tree. origin/main is now:"
git -C "$REPO" --no-pager log --oneline -1 origin/main
git -C "$REPO" reset --hard origin/main

case "$SVC" in
  gpm|era5|all) "$REPO/pod-ml/scripts/podctl" restart "$SVC" ;;
  none)         echo "code updated; no service restart requested (restart when ready)" ;;
  *)            echo "unknown service '$SVC' (use: gpm|era5|all|none)"; exit 2 ;;
esac

# Always restart the dashboard server so the new HTML is served immediately.
# Dashboard must be owned by the same user running this script (claude) so future
# deploys can kill and restart it without needing interactive sudo.
pkill -u "$(whoami)" -f dashboard_server 2>/dev/null || true
sleep 1
setsid python3 "$REPO/pod-ml/scripts/dashboard_server.py" \
  </dev/null >>"$REPO/pod-ml/dashboard_server.log" 2>&1 &
echo "dashboard: restarted (pid $!)"
