#!/usr/bin/env bash
# install_cron.sh — Set up LINZ download + status cron jobs.
# Usage:  LINZ_KEY=<key> bash install_cron.sh
# Safe to re-run (idempotent).  Override data dir with LINZ_BASE_DIR.
set -euo pipefail

REPO="/home/claude/cyber-deck-and-weather-station/pod-ml"
VENV="$REPO/../.venv"
PYTHON="$VENV/bin/python3"
BASE_DIR="${LINZ_BASE_DIR:-$HOME/linz-data}"

# 1) Store key in ~/.linz_key (readable by cron, not visible in ps)
if [[ -n "${LINZ_KEY:-}" ]]; then
    echo "$LINZ_KEY" > "$HOME/.linz_key"
    chmod 600 "$HOME/.linz_key"
    echo "LINZ_KEY saved to $HOME/.linz_key"
elif [[ ! -f "$HOME/.linz_key" ]]; then
    echo "ERROR: set LINZ_KEY env var or create $HOME/.linz_key manually"
    exit 1
fi

# 2) Create per-layer data directories
for layer in contours tracks roads lakes rivers coastline peaks glaciers; do
    mkdir -p "$BASE_DIR/$layer"
done
echo "Data dirs created under $BASE_DIR"

# 3) Install cron entries (idempotent — strip old linz lines first)
PULL_LOG="$BASE_DIR/pull.log"
STATUS_LOG="$BASE_DIR/status.log"

(crontab -l 2>/dev/null | grep -v 'linz_pull\|linz_status'; cat <<CRON

# LINZ vector layers — daily update check at 02:30 UTC
30 2 * * * LINZ_BASE_DIR=$BASE_DIR flock -n /tmp/linz_pull.lock $PYTHON $REPO/scripts/linz/linz_pull.py --all >> $PULL_LOG 2>&1

# LINZ status aggregator — every 5 minutes
*/5 * * * * LINZ_BASE_DIR=$BASE_DIR $PYTHON $REPO/scripts/linz/linz_status.py >> $STATUS_LOG 2>&1
CRON
) | crontab -

echo ""
echo "Cron entries installed:"
crontab -l | grep -E 'linz_pull|linz_status'
echo ""
echo "Next: kick off the initial download:"
echo "  LINZ_BASE_DIR=$BASE_DIR $PYTHON $REPO/scripts/linz/linz_pull.py --all --force"
