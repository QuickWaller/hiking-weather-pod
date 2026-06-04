#!/usr/bin/env bash
# Hang detector for the dataset downloads (the watchdogs only catch DEATH, not a
# process stuck alive on a dead socket). Run from cron every 5 min.
#
# Progress = CPU time advanced OR log file grew. A download is "hung" only when
# NEITHER has moved for >= THRESHOLD seconds — this avoids false positives:
#   ERA5 goes quiet in its log between years but its CPU is busy downloading;
#   GPM's CPU can idle during a Harmony async wait but its log keeps growing.
# On hang: kill the process (releasing its flock) and kick the watchdog, which
# relaunches it. Every dataset is checkpointed, so the restart resumes, not redo.
#
# DRYRUN=1 logs "would kill" instead of killing (for testing).
set -euo pipefail

REPO="/home/claude/cyber-deck-and-weather-station/pod-ml"
HANGLOG="$REPO/hang_check.log"
THRESHOLD="${THRESHOLD:-1800}"   # 30 min of zero progress = hung
NOW="$(date +%s)"

ts() { date -Is; }

# check_dataset <name> <pgrep-pattern> <logfile> <watchdog-script>
check_dataset() {
  local name="$1" pat="$2" logfile="$3" watchdog="$4"
  local pid cpu logsize state

  pid="$(pgrep -f "$pat" | head -1 || true)"
  [ -z "$pid" ] && return 0          # not running -> the watchdog's job, not ours

  # CPU = utime+stime (clock ticks) summed over the whole process tree (workers).
  cpu="$(awk '{print $14+$15}' "/proc/$pid/stat" 2>/dev/null || echo 0)"
  for child in $(pgrep -P "$pid" 2>/dev/null || true); do
    cpu=$((cpu + $(awk '{print $14+$15}' "/proc/$child/stat" 2>/dev/null || echo 0)))
  done
  logsize="$(stat -c %s "$logfile" 2>/dev/null || echo 0)"
  state="/tmp/podml_hang_${name}.state"

  if [ -f "$state" ]; then
    read -r pcpu plog pts < "$state"
    if [ "$cpu" = "$pcpu" ] && [ "$logsize" = "$plog" ]; then
      local idle=$((NOW - pts))
      if [ "$idle" -ge "$THRESHOLD" ]; then
        if [ "${DRYRUN:-0}" = "1" ]; then
          echo "[hang $(ts)] $name PID $pid idle ${idle}s >= ${THRESHOLD}s -> WOULD kill (dryrun)" >> "$HANGLOG"
          return 0
        fi
        echo "[hang $(ts)] $name PID $pid idle ${idle}s -> killing for watchdog restart" >> "$HANGLOG"
        # Kill the whole process group so workers (e.g. GPM's 16) die too, not orphan.
        local pgid; pgid="$(ps -o pgid= -p "$pid" | tr -d ' ')"
        kill -TERM "-$pgid" 2>/dev/null || kill "$pid" 2>/dev/null || true
        sleep 5
        kill -9 "-$pgid" 2>/dev/null || true
        rm -f "$state"
        "$watchdog" || true            # immediate relaunch (else waits for */15)
        return 0
      fi
      # No progress, but still inside the grace window — keep original progress ts.
      echo "$cpu $logsize $pts" > "$state"
    else
      # Progress since last check — reset the clock.
      echo "$cpu $logsize $NOW" > "$state"
    fi
  else
    echo "$cpu $logsize $NOW" > "$state"
  fi
}

check_dataset era5 'podml.download_era5_grid' "$REPO/era5_pull.log" "$REPO/scripts/era5_watchdog.sh"
check_dataset gpm  'podml.download_gpm_harmony' "$REPO/gpm_pull.log"  "$REPO/scripts/gpm_watchdog.sh"
