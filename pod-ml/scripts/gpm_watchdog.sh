#!/usr/bin/env bash
# Watchdog: keep the GPM Harmony backfill alive across crashes/reboots.
#
# Installed in cron (*/15 + @reboot). Safe to run repeatedly:
#   - exits if the backfill already completed (sentinel present)
#   - exits if a download is already running (pgrep, and flock as a hard guard)
#   - otherwise relaunches it, detached, appending to gpm_pull.log
#
# flock(/tmp/podml_gpm.lock) guarantees only ONE GPM download exists at a time, so
# the weekly top-up can never collide with a backfill in progress. The download
# checkpoints one NetCDF per month, so relaunching only re-skips stored months and
# fetches newly-released ones — never corrupts or re-downloads.
set -euo pipefail

REPO="/home/claude/cyber-deck-and-weather-station/pod-ml"
cd "$REPO"

DONE="$REPO/gpm_pull.done"
LOG="$REPO/gpm_pull.log"
LOCK="/tmp/podml_gpm.lock"
START="2000-06"
END="$(date +%Y-%m)"           # forward-looking: fetch through the current month

# 1. Already finished a clean full pass — nothing to do.
[ -f "$DONE" ] && exit 0

# 2. Already running — leave it alone.
if pgrep -f 'podml.download_gpm_harmony' >/dev/null 2>&1; then
  exit 0
fi

# 3. Dead and unfinished — relaunch, detached, under the dataset lock. The sentinel
#    is dropped only on a clean exit (rc 0 = iterated every month without crashing).
echo "[watchdog $(date -Is)] relaunching GPM backfill ($START..$END)" >> "$LOG"
setsid bash -c '
  source "'"$REPO"'/.venv/bin/activate"
  cd "'"$REPO"'"
  if flock -n "'"$LOCK"'" python -m podml.download_gpm_harmony --start '"$START"' --end '"$END"' --workers 16; then
    touch "'"$DONE"'"
    echo "[watchdog '"$(date -Is)"'] GPM backfill completed cleanly, sentinel set" >> "'"$LOG"'"
  fi
' < /dev/null >> "$LOG" 2>&1 &

exit 0
