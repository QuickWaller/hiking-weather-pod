#!/usr/bin/env bash
# install_cron.sh — Set up LINZ download + status cron jobs.
# Usage:  LINZ_KEY=<key> bash install_cron.sh
# Safe to re-run (idempotent).
set -euo pipefail

REPO="/home/claude/cyber-deck-and-weather-station/pod-ml"
VENV="$REPO/../.venv"
PYTHON="$VENV/bin/python3"
PULL="$REPO/scripts/linz/linz_pull.py"
STATUS="$REPO/scripts/linz/linz_status.py"
LOG_PULL="/data/linz/pull.log"
LOG_STATUS="/data/linz/status.log"

# 1) Store key in ~/.linz_key (readable by cron without exposing in ps output)
if [[ -n "${LINZ_KEY:-}" ]]; then
    echo "$LINZ_KEY" > "$HOME/.linz_key"
    chmod 600 "$HOME/.linz_key"
    echo "LINZ_KEY saved to $HOME/.linz_key"
elif [[ ! -f "$HOME/.linz_key" ]]; then
    echo "ERROR: set LINZ_KEY env var or create $HOME/.linz_key manually"
    exit 1
fi

# 2) /data/linz must exist and be writable
sudo mkdir -p /data/linz
sudo chown "$USER:$USER" /data/linz
echo "Created /data/linz"

# 3) Per-layer subdirs
for layer in contours tracks roads lakes rivers coastline peaks glaciers; do
    mkdir -p "/data/linz/$layer"
done
echo "Layer subdirs created"

# 4) Install cron entries (strip old linz lines first)
(crontab -l 2>/dev/null | grep -v 'linz_pull\|linz_status'; cat <<'CRON'

# LINZ vector layers — daily update check at 02:30 UTC
30 2 * * * flock -n /tmp/linz_pull.lock REPO_PY/linz_pull.py --all >> DATA_LOG/pull.log 2>&1

# LINZ status aggregator — every 5 minutes
*/5 * * * * REPO_PY/linz_status.py >> DATA_LOG/status.log 2>&1
CRON
) | sed \
    -e "s|REPO_PY|$PYTHON $REPO/scripts/linz|g" \
    -e "s|DATA_LOG|/data/linz|g" \
    | crontab -

echo ""
echo "Cron entries installed:"
crontab -l | grep -E 'linz_pull|linz_status'
echo ""
echo "Next step: run the initial download:"
echo "  $PYTHON $PULL --all --force"
