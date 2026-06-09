#!/usr/bin/env bash
# Watchdog: keep the ERA5-Land more_labels_1 download alive (snowfall + surface_runoff).
# Same pattern as era5_watchdog.sh. Safe to run repeatedly:
#   - exits if already done (sentinel present)
#   - exits if a download is already running
#   - otherwise relaunches it, detached, appending to era5_more_labels_1.log
set -euo pipefail

REPO="/home/claude/cyber-deck-and-weather-station/pod-ml"
cd "$REPO"

DONE="$REPO/era5_more_labels_1.done"
LOG="$REPO/era5_more_labels_1.log"
LOCK="/tmp/podml_era5_more_labels_1.lock"
START_YEAR=2000
END_YEAR=2024
WORKERS=3

[ -f "$DONE" ] && exit 0

if pgrep -f 'download_era5_grid.*more_labels_1' >/dev/null 2>&1; then
  exit 0
fi

echo "[watchdog $(date -Is)] relaunching ERA5 more_labels_1 ($START_YEAR-$END_YEAR)" >> "$LOG"
setsid bash -c '
  source "'"$REPO"'/.venv/bin/activate"
  cd "'"$REPO"'"
  if flock -n "'"$LOCK"'" python -m podml.download_era5_grid --group more_labels_1 --start-year '"$START_YEAR"' --end-year '"$END_YEAR"' --workers '"$WORKERS"'; then
    touch "'"$DONE"'"
    echo "[watchdog '"$(date -Is)"'] ERA5 more_labels_1 complete, sentinel set" >> "'"$LOG"'"
  fi
' < /dev/null >> "$LOG" 2>&1 &

exit 0
