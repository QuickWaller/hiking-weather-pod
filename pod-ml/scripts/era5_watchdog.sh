#!/usr/bin/env bash
# Watchdog: keep the NZ ERA5 grid download alive across crashes/reboots.
#
# Installed in cron (*/15 + @reboot). Safe to run repeatedly:
#   - exits if every year already downloaded (sentinel present)
#   - exits if a download is already running (pgrep, and flock as a hard guard)
#   - otherwise relaunches it, detached, appending to era5_pull.log
#
# flock(/tmp/podml_era5.lock) guarantees only ONE ERA5 download exists at a time,
# so the weekly top-up can never collide with a backfill in progress. The download
# caches one NetCDF per year, so relaunching only re-pulls missing years.
set -euo pipefail

REPO="/home/claude/cyber-deck-and-weather-station/pod-ml"
cd "$REPO"

DONE="$REPO/era5_pull.done"
LOG="$REPO/era5_pull.log"
LOCK="/tmp/podml_era5.lock"
START_YEAR=2000
END_YEAR=2024                   # training span (2000-2022 train, 2024 test); fixed so
                               # we don't spin on months CDS hasn't published yet
WORKERS=3                       # CDS allows ~2 concurrent active jobs per account for ERA5-Land.
                               # Each worker now requests 3 months per CDS job (BATCH_SIZE=3),
                               # so 2 active slots × 3 months = 6 months per processing cycle
                               # vs the old 2 months/cycle. 3 workers ensures a slot is always
                               # ready to fill when one completes, without spamming the queue.

# 1. Already finished a clean full pass — nothing to do.
[ -f "$DONE" ] && exit 0

# 2. Already running — leave it alone.
if pgrep -f 'download_era5_grid.*--group core' >/dev/null 2>&1; then
  exit 0
fi

# 3. Dead and unfinished — relaunch, detached, under the dataset lock. The sentinel
#    is dropped only on a clean exit (rc 0 = every year cached).
echo "[watchdog $(date -Is)] relaunching ERA5 grid download ($START_YEAR-$END_YEAR)" >> "$LOG"
setsid bash -c '
  source "'"$REPO"'/.venv/bin/activate"
  cd "'"$REPO"'"
  if flock -n "'"$LOCK"'" python -m podml.download_era5_grid --group core --start-year '"$START_YEAR"' --end-year '"$END_YEAR"' --workers '"$WORKERS"'; then
    touch "'"$DONE"'"
    echo "[watchdog '"$(date -Is)"'] ERA5 download complete, sentinel set" >> "'"$LOG"'"
  fi
' < /dev/null >> "$LOG" 2>&1 &

exit 0
