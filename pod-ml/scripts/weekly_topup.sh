#!/usr/bin/env bash
# Weekly top-up: nudge each dataset's watchdog to fetch newly-published data.
#
# Installed in cron (weekly). It deliberately does NOT download anything itself —
# it only clears the per-dataset completion sentinel (and, for ERA5, the stale
# recent-year cache files), so the existing watchdogs re-fetch on their next tick.
# All actual downloading stays inside the watchdogs, serialised by their flock, so
# this job can never collide with a backfill or partial download in progress.
#
# Why per dataset:
#   GPM   — IMERG finalises new months over time; clearing the sentinel lets the
#           watchdog pick up months that have become available since last week.
#   ERA5  — reanalysis for completed years is immutable, so only the current and
#           previous (still-settling) years are deleted and re-pulled.
#   Open-Meteo — already hourly + deduped; nothing to do.
set -euo pipefail

REPO="/home/claude/cyber-deck-and-weather-station/pod-ml"
LOG="$REPO/weekly_topup.log"
ts() { date -Is; }

echo "[weekly $(ts)] start" >> "$LOG"

# --- GPM: clear sentinel only (never touches data files -> always safe) ---
rm -f "$REPO/gpm_pull.done"
echo "[weekly $(ts)] GPM sentinel cleared (watchdog will fetch new months)" >> "$LOG"

# --- ERA5: drop current+previous year cache + sentinel so the watchdog re-pulls
#     them (reanalysis for older years is immutable). Guarded twice: a pgrep check
#     (catches any running download, incl. ones predating the lock) and the flock
#     itself (catches the steady-state race) — so we never delete a file a download
#     is actively writing. If either says busy, skip; the data is fresh anyway. ---
YEAR="$(date +%Y)"; PREV="$((YEAR - 1))"
if pgrep -f 'podml.download_era5_grid' >/dev/null 2>&1; then
  echo "[weekly $(ts)] ERA5 download active (pgrep); skipped refresh this week" >> "$LOG"
elif flock -n /tmp/podml_era5.lock bash -c '
      rm -f "'"$REPO"'"/data/raw/era5_grid/era5_nz_'"$YEAR"'_'"$YEAR"'_*.nc
      rm -f "'"$REPO"'"/data/raw/era5_grid/era5_nz_'"$PREV"'_'"$PREV"'_*.nc
      rm -f "'"$REPO"'/era5_pull.done"
    '; then
  echo "[weekly $(ts)] ERA5 ${PREV}+${YEAR} cache+sentinel cleared (watchdog will re-pull)" >> "$LOG"
else
  echo "[weekly $(ts)] ERA5 lock busy; skipped refresh this week" >> "$LOG"
fi

echo "[weekly $(ts)] done" >> "$LOG"
