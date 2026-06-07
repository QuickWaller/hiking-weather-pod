#!/usr/bin/env python3
"""pod-ml live dashboard — richer than the stock one. Polls /proc + logs + filesystem."""

import glob, json, os, re, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO = Path("/home/claude/cyber-deck-and-weather-station/pod-ml")
RAW = REPO / "data" / "raw"
PORT = 8000
STARTED = time.time()

def _tail(path, n=2000):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2); size = f.tell()
            f.seek(max(0, size - n * 120))
            return f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []

def _proc_cmdlines():
    cmds = []
    for cl in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            cmds.append(Path(cl).read_bytes().replace(b"\0", b" ").decode("utf-8", "replace"))
        except OSError:
            pass
    return cmds

def _running(pattern):
    return sum(1 for c in _proc_cmdlines() if pattern in c and "status_server" not in c and "dashboard" not in c)

def _stats(pattern, expected):
    files = sorted(glob.glob(pattern), key=os.path.getmtime)
    now = time.time()
    last_hr = sum(1 for f in files if now - os.path.getmtime(f) < 3600)
    recent, recent_age = ("-", None)
    if files:
        recent = os.path.basename(files[-1])
        recent_age = (now - os.path.getmtime(files[-1])) / 60.0
    remaining = max(expected - len(files), 0)
    eta_h = (remaining / last_hr) if last_hr else None
    return {"n": len(files), "expected": expected, "pct": 100.0 * len(files) / expected if expected else 0,
            "last_hr": last_hr, "recent": recent, "recent_age": recent_age, "eta_h": eta_h,
            "files": files}

def _parse_gpm():
    lines = [l for l in _tail(REPO / "gpm_pull.log") if re.match(r"\[\d{4}-\d{2}\]", l.strip())]
    failures, no_data, current, workers = {}, [], None, None
    for line in lines:
        line = line.strip()
        m = re.match(r"\[(\d{4}-\d{2})\] (.+)", line)
        if not m: continue
        month, msg = m.group(1), m.group(2)
        if "SKIPPED after" in msg or "INCOMPLETE" in msg:
            failures[month] = msg.split(":", 1)[-1].strip() if ":" in msg else msg[:80]
        elif "no granules found" in msg:
            no_data.append(month); failures.pop(month, None)
        elif re.match(r"\d+ granules -> \d+ steps ->", msg):
            failures.pop(month, None)
        elif re.search(r"\d+ granules,\s+\d+ workers", msg):
            current = month
            wm = re.search(r"(\d+) workers", msg)
            if wm: workers = int(wm.group(1))
        elif "Harmony request" in msg:
            current = month
    return {"current": current, "workers": workers, "failures": list(failures.items()), "no_data": sorted(set(no_data))}

def _parse_gpm_workers(log_path=None):
    """Parse [YYYY-MM] lines in gpm_pull.log to show active worker state.

    Walks backwards through the last ~200 lines. Each month gets a sequence:
    Harmony request → (attempt N failed) → granules -> steps -> completion.
    Active = has a recent request/failed line but no completion yet.
    Returns [{month, stage, attempt}], newest first.
    """
    if log_path is None:
        log_path = REPO / "gpm_pull.log"
    lines = _tail(log_path, n=200)
    seen: set[str] = set()
    workers: list[dict] = []

    for line in reversed(lines):
        line = line.strip()
        m = re.match(r"\[(\d{4}-\d{2})\] (.+)", line)
        if not m:
            continue
        month, msg = m.group(1), m.group(2)
        if month in seen:
            continue

        # Terminal states — month is done, don't show as active
        if "granules ->" in msg and "steps ->" in msg:
            seen.add(month)
            continue
        if "no granules available" in msg or "already stored" in msg:
            seen.add(month)
            continue

        am = re.search(r"attempt (\d+)/(\d+)", msg)
        attempt = int(am.group(1)) if am else 1

        if "Harmony request" in msg:
            workers.append({"month": month, "stage": "requested", "attempt": attempt})
            seen.add(month)
        elif "attempt" in msg and "failed" in msg:
            workers.append({"month": month, "stage": "failed", "attempt": attempt})
            seen.add(month)

        if len(workers) >= 16:
            break

    return workers

def _parse_era5(log_path=None):
    if log_path is None:
        log_path = REPO / "era5_pull.log"
    lines = _tail(log_path, n=1000)
    failures, workers, cds_status = {}, None, None
    for line in lines:
        line = line.strip()
        m = re.search(r"ERA5-Land CDS: .+, (\d+) parallel", line)
        if m: workers = int(m.group(1))
        m = re.match(r"(?:\[W..\] )?\[(\d{4}-\d{2})\] FAILED: (.+)", line)
        if m:
            failures[m.group(1)] = m.group(2)[:80]; continue
        m = re.match(r"(?:\[W..\] )?\[(\d{4}-\d{2})\] (cached|\d+s|SKIPPED)", line)
        if m:
            failures.pop(m.group(1), None); continue
        m = re.search(r"status has been updated to (\w+)", line)
        if m: cds_status = m.group(1)
    in_flight = False
    for line in reversed(lines[-300:]):
        line = line.strip()
        if re.match(r"(?:\[W..\] )?\[(\d{4}-\d{2})\] (cached|\d+s|FAILED|SKIPPED)", line):
            in_flight = False; break
        if "status has been updated to accepted" in line or "status has been updated to running" in line:
            in_flight = True
    return {"current": "in-flight" if in_flight else None, "workers": workers,
            "failures": list(failures.items()), "cds_status": cds_status}


def _parse_era5_workers(log_path=None):
    """Parse [W..] [...] lines to reconstruct per-worker state."""
    if log_path is None:
        log_path = REPO / "era5_pull.log"
    lines = _tail(log_path, n=600)
    # Walk backwards: each [W..] line is the *latest* stage for that worker
    seen: set[str] = set()  # worker IDs we've already captured their latest state
    workers: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        # Match both old [W00] [YYYY-MM] and new [W00] YYYY-[MM+MM+MM] formats
        m = re.match(r"\[(W..)\] (\S+) (.+)", line)
        if not m: continue
        wid, month, rest = m.group(1), m.group(2), m.group(3)
        # Skip non-worker lines caught by the broad regex (e.g. startup banners)
        if not re.match(r"\[?\d{4}", month): continue
        if wid in seen:
            continue  # already captured this worker's latest state
        # Skip FAILED/completed — they're done, not active
        # Must add to seen so earlier 'submitting' lines for the same worker are also skipped
        if "FAILED:" in rest:
            seen.add(wid); continue
        if "cached" in rest:
            seen.add(wid); continue
        if "s" in rest and "MB" in rest:
            seen.add(wid); continue
        seen.add(wid)
        if rest.startswith("started"):
            stage, extra = "started", ""
        elif rest.startswith("submitting"):
            stage, extra = "submitting", ""
        elif "rate-limited retry" in rest:
            stage = "rate-limited"
            rm = re.search(r"retry (\d+/\d+)", rest)
            extra = f" {rm.group(1)}" if rm else ""
        elif re.search(r"error \d+/\d+:", rest):
            stage = "error"
            em = re.search(r"error (\d+/\d+):", rest)
            extra = f" {em.group(1)}" if em else ""
        elif "cached" in rest:
            continue
        elif "FAILED:" in rest:
            stage, extra = "FAILED", ""
        elif "s" in rest and "MB" in rest:
            m2 = re.match(r"(\d+)s (\d+)MB", rest)
            extra = f" {m2.group(1)}s {m2.group(2)}MB" if m2 else ""
            continue
        else:
            stage, extra = "working", ""
        line_age_s = (len(lines) - lines.index(line)) * 0.5
        workers.append({"id": wid, "month": month, "stage": stage + extra, "elapsed_s": line_age_s})
        if len(workers) >= 8: break
    return [w for w in workers if w["elapsed_s"] < 600]

def _activity():
    """Recent download activity feed from all logs."""
    gpm_lines = _tail(REPO / "gpm_pull.log", n=500)
    era5_lines = _tail(REPO / "era5_pull.log", n=500)
    era5_ml1_lines = _tail(REPO / "era5_more_labels_1.log", n=500)
    entries = []
    for line in gpm_lines[-30:]:
        line = line.strip()
        m = re.match(r"\[(\d{4}-\d{2})\] (\d+) granules -> \d+ steps -> (.+\.nc)", line)
        if m:
            entries.append({"ds": "gpm", "month": m.group(1), "msg": f"Completed {m.group(2)} granules → {m.group(3)}"})
        elif "Harmony request" in line:
            m2 = re.search(r"\[(\d{4}-\d{2})\]", line)
            if m2:
                entries.append({"ds": "gpm", "month": m2.group(1), "msg": "Harmony request submitted"})
    for line in era5_lines[-20:]:
        line = line.strip()
        m = re.match(r"(?:\[W..\] )?\[(\d{4}-\d{2})\] (\d+)s (\d+)MB(?: \(try \d+\))?", line)
        if m:
            entries.append({"ds": "era5_core", "month": m.group(1), "msg": f"Downloaded {m.group(3)}MB in {m.group(2)}s"})
        m = re.match(r"(?:\[W..\] )?\[(\d{4}-\d{2})\] cached", line)
        if m:
            entries.append({"ds": "era5_core", "month": m.group(1), "msg": "Already cached"})
        m = re.match(r"\[(W..)\] (\S+) rate-limited retry (\d+/\d+)", line)
        if m:
            entries.append({"ds": "era5_core", "month": m.group(2), "msg": f"W{m.group(1)} rate-limited, retry {m.group(3)}"})
    for line in era5_ml1_lines[-20:]:
        line = line.strip()
        m = re.match(r"(?:\[W..\] )?\[(\d{4}-\d{2})\] (\d+)s (\d+)MB(?: \(try \d+\))?", line)
        if m:
            entries.append({"ds": "era5_ml1", "month": m.group(1), "msg": f"Downloaded {m.group(3)}MB in {m.group(2)}s"})
        m = re.match(r"(?:\[W..\] )?\[(\d{4}-\d{2})\] cached", line)
        if m:
            entries.append({"ds": "era5_ml1", "month": m.group(1), "msg": "Already cached"})
        m = re.match(r"\[(W..)\] (\S+) rate-limited retry (\d+/\d+)", line)
        if m:
            entries.append({"ds": "era5_ml1", "month": m.group(2), "msg": f"W{m.group(1)} rate-limited, retry {m.group(3)}"})
    return entries[-15:]

def _month_grid(files, year_start, year_end, failures, no_data):
    """Build grid data for the frontend: list of {year, months: [{mo, color, tip}]}."""
    done = set()
    for f in files:
        m = re.search(r"(\d{4})-(\d{2})", os.path.basename(f))
        if m: done.add(f"{m.group(1)}-{m.group(2)}")
    fail_map = dict(failures)
    no_data_set = set(no_data)
    now = time.localtime()
    this_ym = f"{now.tm_year}-{now.tm_mon:02d}"
    month_labels = ["J","F","M","A","M","J","J","A","S","O","N","D"]
    rows = []
    for yr in range(year_end, year_start - 1, -1):
        yr_done = 0
        cells = []
        for mo in range(1, 13):
            ym = f"{yr}-{mo:02d}"
            if ym in done:
                color, tip = "#3fb950", "done"
                yr_done += 1
            elif ym in fail_map:
                color, tip = "#f85149", fail_map[ym][:40]
            elif ym in no_data_set:
                color, tip = "#e3b341", "no data"
            elif ym > this_ym:
                color, tip = "#161b22", "future"
            else:
                color, tip = "#30363d", "missing"
            cells.append({"mo": month_labels[mo-1], "ym": ym, "color": color, "tip": tip})
        rows.append({"year": yr, "done": yr_done, "cells": cells})
    return rows

def _hourly_rate(files, hours=48):
    """Count files completed per hour bucket over the last `hours` hours.

    Uses file mtime as the completion timestamp — accurate because files are
    written atomically (temp + rename) so mtime = the moment the month landed.
    Returns list of {ts, count} dicts newest-last, covering every hour in the
    window even if count is 0 (so the chart has a full x-axis).
    """
    now = time.time()
    cutoff = now - hours * 3600
    # floor each file's mtime to the start of its hour
    buckets: dict[int, int] = {}
    for f in files:
        mt = os.path.getmtime(f)
        if mt >= cutoff:
            bucket = int(mt // 3600) * 3600
            buckets[bucket] = buckets.get(bucket, 0) + 1
    # fill every hour in the window so the chart x-axis is continuous
    start_bucket = int(cutoff // 3600) * 3600
    current_bucket = int(now // 3600) * 3600
    result = []
    b = start_bucket
    while b <= current_bucket:
        result.append({"ts": b, "count": buckets.get(b, 0)})
        b += 3600
    return result


def api_data():
    era5_core_s = _stats(str(RAW / "era5_grid" / "core" / "era5land_nz_*.nc"), 180)
    era5_ml1_s  = _stats(str(RAW / "era5_grid" / "more_labels_1" / "era5land_nz_*.nc"), 180)
    gpm_s = _stats(str(RAW / "gpm_grid" / "gpm_*.nc"), 295)
    gpm_log = _parse_gpm()
    era5_core_log = _parse_era5(REPO / "era5_pull.log")
    era5_ml1_log  = _parse_era5(REPO / "era5_more_labels_1.log")
    gpm_run = _running("download_gpm_harmony")
    era5_total_run = _running("download_era5_grid")
    era5_ml1_run = _running("more_labels_1")
    era5_core_run = max(0, era5_total_run - era5_ml1_run)
    if gpm_run and not gpm_log["workers"]:
        for cmd in _proc_cmdlines():
            if "download_gpm_harmony" in cmd:
                wm = re.search(r"--workers\s+(\d+)", cmd)
                if wm: gpm_log["workers"] = int(wm.group(1)); break
    if era5_core_run and not era5_core_log["workers"]:
        for cmd in _proc_cmdlines():
            if "download_era5_grid" in cmd and "more_labels_1" not in cmd:
                wm = re.search(r"--workers\s+(\d+)", cmd)
                if wm: era5_core_log["workers"] = int(wm.group(1)); break
    if era5_ml1_run and not era5_ml1_log["workers"]:
        for cmd in _proc_cmdlines():
            if "more_labels_1" in cmd:
                wm = re.search(r"--workers\s+(\d+)", cmd)
                if wm: era5_ml1_log["workers"] = int(wm.group(1)); break
    def _ds_json(s, running, log_info):
        d = {"n": s["n"], "expected": s["expected"], "pct": round(s["pct"], 1),
             "running": bool(running), "workers": log_info.get("workers"),
             "current": log_info.get("current"), "files_last_hr": s["last_hr"],
             "recent": s["recent"],
             "recent_age_min": round(s["recent_age"], 1) if s["recent_age"] else None,
             "eta_h": round(s["eta_h"], 1) if s["eta_h"] else None,
             "failures": log_info.get("failures", []),
             "no_data": log_info.get("no_data", [])}
        if "cds_status" in log_info:
            d["cds_status"] = log_info["cds_status"]
        return d
    return {
        "ts": int(time.time()),
        "uptime": int(time.time() - STARTED),
        "datasets": {
            "gpm": _ds_json(gpm_s, gpm_run, gpm_log),
            "era5_core": _ds_json(era5_core_s, era5_core_run, era5_core_log),
            "era5_more_labels_1": _ds_json(era5_ml1_s, era5_ml1_run, era5_ml1_log),
        },
        "activity": _activity(),
        "era5_workers": _parse_era5_workers(REPO / "era5_pull.log"),
        "era5_ml1_workers": _parse_era5_workers(REPO / "era5_more_labels_1.log"),
        "gpm_workers": _parse_gpm_workers(REPO / "gpm_pull.log"),
        "grids": {
            "gpm": _month_grid(gpm_s["files"], 2000, 2026, gpm_log["failures"], gpm_log["no_data"]),
            "era5_core": _month_grid(era5_core_s["files"], 2010, 2024, era5_core_log["failures"], []),
            "era5_more_labels_1": _month_grid(era5_ml1_s["files"], 2010, 2024, era5_ml1_log["failures"], []),
        },
        "disk": os.statvfs(str(RAW)),
        "hourly": {
            "gpm": _hourly_rate(gpm_s["files"]),
            "era5_core": _hourly_rate(era5_core_s["files"]),
            "era5_more_labels_1": _hourly_rate(era5_ml1_s["files"]),
        },
    }

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/api"):
            body = json.dumps(api_data()).encode()
            ctype = "application/json"
        else:
            body = HTML.encode()
            ctype = "text/html"
        self.send_response(200)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *_): pass

HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>pod-ml ops</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
:root {
  --bg: #0b0b0d;
  --surface: #111115;
  --surface2: #17171c;
  --border: #222228;
  --border2: #2a2a32;
  --text: #d8d8e0;
  --muted: #606070;
  --dim: #3a3a48;
  --green: #00e676;
  --green-dim: rgba(0,230,118,.08);
  --amber: #ffab00;
  --amber-dim: rgba(255,171,0,.08);
  --red: #ff3d3d;
  --red-dim: rgba(255,61,61,.08);
  --blue: #40c4ff;
  --blue-dim: rgba(64,196,255,.08);
  --purple: #b388ff;
  --purple-dim: rgba(179,136,255,.08);
  --mono: 'IBM Plex Mono', monospace;
  --display: 'IBM Plex Mono', monospace;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { font-size: 13px; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: var(--mono);
  min-height: 100vh;
  padding: 0;
}

/* ── top bar ── */
#topbar {
  display: flex;
  align-items: center;
  gap: 24px;
  padding: 14px 28px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  position: sticky;
  top: 0;
  z-index: 10;
}
#topbar .title {
  font-size: 12px;
  font-weight: 600;
  letter-spacing: .2em;
  text-transform: uppercase;
  color: #fff;
  display: flex;
  align-items: center;
  gap: 10px;
}
#topbar .title .pulse {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--green);
  box-shadow: 0 0 10px var(--green);
  animation: blink 2.4s ease-in-out infinite;
}
@keyframes blink { 0%,100%{opacity:1} 50%{opacity:.2} }
.topstat {
  display: flex; flex-direction: column;
  padding: 0 16px;
  border-left: 1px solid var(--border);
}
.topstat .ts-val { font-size: 13px; font-weight: 600; color: var(--text); }
.topstat .ts-lbl { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; margin-top: 1px; }
#topbar .clock { margin-left: auto; font-size: 12px; color: var(--muted); }

/* ── layout ── */
#main { padding: 20px 28px; max-width: 1280px; margin: 0 auto; }
.row { display: grid; gap: 14px; margin-bottom: 14px; }
.row.two { grid-template-columns: 1fr 1fr; }
.row.three { grid-template-columns: 1fr 1fr 1fr; }
.row.one { grid-template-columns: 1fr; }
@media(max-width:900px){ .row.two { grid-template-columns: 1fr; } .row.three { grid-template-columns: 1fr; } }

/* ── panel ── */
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
}
.panel-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}
.panel-head .ph-label {
  font-size: 10px;
  font-weight: 500;
  letter-spacing: .14em;
  text-transform: uppercase;
  color: var(--muted);
}
.panel-head .ph-title {
  font-size: 13px;
  font-weight: 400;
  color: var(--text);
  letter-spacing: .02em;
}
.panel-head .ph-badge {
  margin-left: auto;
  font-size: 11px;
  font-weight: 500;
  padding: 3px 9px;
  border: 1px solid;
}
.ph-badge.running { color: var(--green); border-color: var(--green); background: var(--green-dim); }
.ph-badge.idle    { color: var(--muted); border-color: var(--dim); background: transparent; }
.ph-badge.error   { color: var(--red);   border-color: var(--red);   background: var(--red-dim); }
.ph-badge.warn    { color: var(--amber); border-color: var(--amber); background: var(--amber-dim); }
.panel-body { padding: 16px; }

/* ── progress ── */
.prog-row {
  display: flex; align-items: baseline; gap: 10px;
  margin-bottom: 8px;
}
.prog-pct {
  font-size: 36px; font-weight: 300; line-height: 1;
  letter-spacing: -.02em;
}
.prog-pct.green { color: var(--green); }
.prog-pct.blue  { color: var(--blue); }
.prog-pct.amber { color: var(--amber); }
.prog-pct.red   { color: var(--red); }
.prog-frac {
  font-size: 12px; color: var(--muted);
  display: flex; flex-direction: column; gap: 1px;
}
.prog-track {
  height: 3px; background: var(--border2);
  position: relative; overflow: hidden;
  margin-bottom: 14px;
}
.prog-fill {
  position: absolute; top: 0; left: 0; height: 100%;
  transition: width .8s cubic-bezier(.4,0,.2,1);
}
.prog-fill.green  { background: var(--green); }
.prog-fill.blue   { background: var(--blue); }
.prog-fill.amber  { background: var(--amber); }
.prog-fill.red    { background: var(--red); }
.prog-fill::after {
  content: '';
  position: absolute; inset: 0;
  background: linear-gradient(90deg,transparent,rgba(255,255,255,.35),transparent);
  animation: sweep 2.5s linear infinite;
}
@keyframes sweep { from{transform:translateX(-100%)} to{transform:translateX(300%)} }

/* ── stat grid ── */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  background: var(--border);
  border: 1px solid var(--border);
  margin-bottom: 14px;
}
.stat-cell {
  background: var(--surface);
  padding: 10px 12px;
  display: flex; flex-direction: column; gap: 2px;
}
.sc-val { font-size: 17px; font-weight: 500; color: var(--text); }
.sc-val.accent { color: var(--green); }
.sc-val.warn   { color: var(--amber); }
.sc-val.err    { color: var(--red); }
.sc-lbl { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: .06em; }

/* ── failures ── */
.fail-list { margin-top: 4px; }
.fail-item {
  display: flex; gap: 10px; align-items: flex-start;
  padding: 5px 0; border-top: 1px solid var(--border);
  font-size: 11px;
}
.fail-mo { color: var(--red); font-weight: 600; white-space: nowrap; min-width: 60px; }
.fail-reason { color: var(--muted); word-break: break-all; }

/* ── workers table ── */
.workers-table { width: 100%; border-collapse: collapse; }
.workers-table th {
  text-align: left; padding: 6px 10px;
  font-size: 10px; font-weight: 500; letter-spacing: .08em; text-transform: uppercase;
  color: var(--muted); border-bottom: 1px solid var(--border);
}
.workers-table td {
  padding: 8px 10px; font-size: 12px;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}
.workers-table tr:last-child td { border-bottom: none; }
.workers-table tr:hover td { background: var(--surface2); }
.wid { color: var(--blue); font-weight: 600; }
.wmonth { color: var(--text); }
.wstage { display: inline-flex; align-items: center; gap: 6px; }
.wstage-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.wstage.submitting .wstage-dot { background: var(--blue); animation: blink 1s infinite; }
.wstage.started    .wstage-dot { background: var(--blue); }
.wstage.rate       .wstage-dot { background: var(--amber); animation: blink 2s infinite; }
.wstage.maint      .wstage-dot { background: var(--amber); }
.wstage.error      .wstage-dot { background: var(--red); animation: blink .8s infinite; }
.wstage.working    .wstage-dot { background: var(--green); animation: blink 1.5s infinite; }
.wstage.text { font-size: 12px; }
.wstage.submitting .wstage-text { color: var(--blue); }
.wstage.rate       .wstage-text { color: var(--amber); }
.wstage.maint      .wstage-text { color: var(--amber); }
.wstage.error      .wstage-text { color: var(--red); }
.wstage.working    .wstage-text { color: var(--green); }
.welapsed { color: var(--muted); text-align: right; font-size: 11px; }

/* ── month grid ── */
.mgrid-wrap { overflow-x: auto; padding-bottom: 4px; }
.mgrid {
  border-collapse: collapse;
  width: 100%;
  table-layout: fixed;
}
.mgrid th, .mgrid td { padding: 2px 3px; text-align: center; }
.mgrid th { font-size: 10px; color: var(--dim); font-weight: 400; letter-spacing: .04em; }
.mgrid .mg-yr {
  font-size: 11px; color: var(--muted); font-weight: 500;
  text-align: right; padding-right: 8px; white-space: nowrap; width: 44px;
}
.mgrid .mg-cnt {
  font-size: 11px; color: var(--muted);
  text-align: left; padding-left: 6px; width: 28px;
}
.mgrid .mg-cell {
  width: 20px; height: 20px;
  display: inline-block;
  cursor: default;
  position: relative;
  transition: opacity .15s;
}
.mgrid .mg-cell:hover { opacity: .7; }
.mgrid-legend {
  display: flex; gap: 16px; padding: 8px 0 4px;
  flex-wrap: wrap;
}
.ml-item {
  display: flex; align-items: center; gap: 5px;
  font-size: 10px; color: var(--muted);
}
.ml-swatch { width: 12px; height: 12px; }

/* ── activity ── */
.act-list { display: flex; flex-direction: column; }
.act-item {
  display: grid;
  grid-template-columns: 44px 68px 1fr;
  gap: 8px;
  align-items: center;
  padding: 6px 0;
  border-bottom: 1px solid var(--border);
  font-size: 12px;
}
.act-item:last-child { border-bottom: none; }
.act-ds {
  font-size: 10px; font-weight: 600; letter-spacing: .06em;
  padding: 2px 5px; text-align: center;
}
.act-ds.gpm  { color: var(--purple); background: var(--purple-dim); }
.act-ds.era5_core { color: var(--green);  background: var(--green-dim); }
.act-ds.era5_ml1  { color: var(--blue);   background: var(--blue-dim); }
.act-month { color: var(--text); font-weight: 500; }
.act-msg { color: var(--muted); }
</style>
</head>
<body>

<div id="topbar">
  <div class="title">
    <span class="pulse"></span>
    POD-ML OPS
  </div>
  <div class="topstat">
    <span class="ts-val" id="tb-total">—</span>
    <span class="ts-lbl">months total</span>
  </div>
  <div class="topstat">
    <span class="ts-val" id="tb-disk">—</span>
    <span class="ts-lbl">disk free</span>
  </div>
  <div class="topstat">
    <span class="ts-val" id="tb-diskpct">—</span>
    <span class="ts-lbl">disk used</span>
  </div>
  <div class="topstat">
    <span class="ts-val" id="tb-uptime">—</span>
    <span class="ts-lbl">uptime</span>
  </div>
  <span class="clock" id="clock">—</span>
</div>

<div id="main">
  <div class="row three" id="ds-row">
    <!-- ERA5 core card -->
    <div class="panel" id="era5-panel">
      <div class="panel-head">
        <div>
          <div class="ph-label">ERA5-Land / CDS</div>
          <div class="ph-title">Core features · 2010–2024</div>
        </div>
        <span class="ph-badge idle" id="era5-badge">idle</span>
      </div>
      <div class="panel-body">
        <div class="prog-row">
          <div class="prog-pct green" id="era5-pct">—%</div>
          <div class="prog-frac">
            <span id="era5-frac">—/—</span>
            <span style="color:var(--muted)">months</span>
          </div>
        </div>
        <div class="prog-track"><div class="prog-fill green" id="era5-bar" style="width:0"></div></div>
        <div class="stat-grid" id="era5-stats">
          <div class="stat-cell"><div class="sc-val" id="e-workers">—</div><div class="sc-lbl">workers</div></div>
          <div class="stat-cell"><div class="sc-val" id="e-rate">—</div><div class="sc-lbl">files/hr</div></div>
          <div class="stat-cell"><div class="sc-val" id="e-last">—</div><div class="sc-lbl">last file</div></div>
          <div class="stat-cell"><div class="sc-val" id="e-eta">—</div><div class="sc-lbl">ETA</div></div>
        </div>
        <div id="era5-current" style="font-size:11px;color:var(--muted);margin-bottom:10px;display:none">→ <span id="era5-cur-text"></span></div>
        <div id="era5-fails" class="fail-list"></div>
      </div>
    </div>

    <!-- ERA5 more_labels_1 card -->
    <div class="panel" id="era5-ml1-panel">
      <div class="panel-head">
        <div>
          <div class="ph-label">ERA5-Land / CDS</div>
          <div class="ph-title">More labels 1 · 2010–2024</div>
        </div>
        <span class="ph-badge idle" id="era5-ml1-badge">idle</span>
      </div>
      <div class="panel-body">
        <div class="prog-row">
          <div class="prog-pct blue" id="era5-ml1-pct">—%</div>
          <div class="prog-frac">
            <span id="era5-ml1-frac">—/—</span>
            <span style="color:var(--muted)">months</span>
          </div>
        </div>
        <div class="prog-track"><div class="prog-fill blue" id="era5-ml1-bar" style="width:0"></div></div>
        <div class="stat-grid" id="era5-ml1-stats">
          <div class="stat-cell"><div class="sc-val" id="ml-workers">—</div><div class="sc-lbl">workers</div></div>
          <div class="stat-cell"><div class="sc-val" id="ml-rate">—</div><div class="sc-lbl">files/hr</div></div>
          <div class="stat-cell"><div class="sc-val" id="ml-last">—</div><div class="sc-lbl">last file</div></div>
          <div class="stat-cell"><div class="sc-val" id="ml-eta">—</div><div class="sc-lbl">ETA</div></div>
        </div>
        <div id="era5-ml1-current" style="font-size:11px;color:var(--muted);margin-bottom:10px;display:none">→ <span id="era5-ml1-cur-text"></span></div>
        <div id="era5-ml1-fails" class="fail-list"></div>
      </div>
    </div>

    <!-- GPM card -->
    <div class="panel" id="gpm-panel">
      <div class="panel-head">
        <div>
          <div class="ph-label">GPM IMERG / Harmony</div>
          <div class="ph-title">Rain labels · 2000–2026</div>
        </div>
        <span class="ph-badge idle" id="gpm-badge">idle</span>
      </div>
      <div class="panel-body">
        <div class="prog-row">
          <div class="prog-pct blue" id="gpm-pct">—%</div>
          <div class="prog-frac">
            <span id="gpm-frac">—/—</span>
            <span style="color:var(--muted)">months</span>
          </div>
        </div>
        <div class="prog-track"><div class="prog-fill blue" id="gpm-bar" style="width:0"></div></div>
        <div class="stat-grid" id="gpm-stats">
          <div class="stat-cell"><div class="sc-val" id="g-workers">—</div><div class="sc-lbl">workers</div></div>
          <div class="stat-cell"><div class="sc-val" id="g-rate">—</div><div class="sc-lbl">files/hr</div></div>
          <div class="stat-cell"><div class="sc-val" id="g-last">—</div><div class="sc-lbl">last file</div></div>
          <div class="stat-cell"><div class="sc-val" id="g-eta">—</div><div class="sc-lbl">ETA</div></div>
        </div>
        <div id="gpm-current" style="font-size:11px;color:var(--muted);margin-bottom:10px;display:none">→ <span id="gpm-cur-text"></span></div>
        <div id="gpm-fails" class="fail-list"></div>
      </div>
    </div>
  </div>

  <!-- ERA5 workers -->
  <div class="row three" id="workers-row">
    <div class="panel">
      <div class="panel-head">
        <div class="ph-title">ERA5 Core Workers</div>
        <span style="font-size:11px;color:var(--muted);margin-left:auto" id="w-count">0 active</span>
      </div>
      <div class="panel-body" style="padding:0">
        <table class="workers-table">
          <thead><tr>
            <th style="width:52px">ID</th>
            <th>Batch</th>
            <th>Stage</th>
            <th>Elapsed</th>
          </tr></thead>
          <tbody id="era5-workers-body">
            <tr><td colspan="4" style="color:var(--muted);text-align:center;padding:16px">no active workers</td></tr>
          </tbody>
        </table>
      </div>
    </div>
    <div class="panel">
      <div class="panel-head">
        <div class="ph-title">ERA5 More Labels 1 Workers</div>
        <span style="font-size:11px;color:var(--muted);margin-left:auto" id="ml1-w-count">0 active</span>
      </div>
      <div class="panel-body" style="padding:0">
        <table class="workers-table">
          <thead><tr>
            <th style="width:52px">ID</th>
            <th>Batch</th>
            <th>Stage</th>
            <th>Elapsed</th>
          </tr></thead>
          <tbody id="era5-ml1-workers-body">
            <tr><td colspan="4" style="color:var(--muted);text-align:center;padding:16px">no active workers</td></tr>
          </tbody>
        </table>
      </div>
    </div>
    <div class="panel" id="gpm-workers-panel">
      <div class="panel-head">
        <div class="ph-title">GPM Workers</div>
        <span style="font-size:11px;color:var(--muted);margin-left:auto" id="gpm-w-count">0 active</span>
      </div>
      <div class="panel-body" style="padding:0">
        <table class="workers-table">
          <thead><tr>
            <th>Month</th>
            <th>Stage</th>
            <th>Attempt</th>
          </tr></thead>
          <tbody id="gpm-workers-body">
            <tr><td colspan="3" style="color:var(--muted);text-align:center;padding:16px">no active workers</td></tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- Throughput chart -->
  <div class="row one">
    <div class="panel">
      <div class="panel-head">
        <div class="ph-title">Throughput — months downloaded per hour (48h)</div>
        <div style="display:flex;gap:16px;margin-left:auto;align-items:center;font-size:11px">
          <span style="display:flex;align-items:center;gap:5px;color:var(--blue)">
            <span style="width:10px;height:3px;background:var(--blue);display:inline-block"></span>GPM
          </span>
          <span style="display:flex;align-items:center;gap:5px;color:var(--green)">
            <span style="width:10px;height:3px;background:var(--green);display:inline-block"></span>ERA5 core
          </span>
          <span style="display:flex;align-items:center;gap:5px;color:var(--amber)">
            <span style="width:10px;height:3px;background:var(--amber);display:inline-block"></span>ERA5 ml1
          </span>
        </div>
      </div>
      <div class="panel-body" style="padding:16px">
        <canvas id="throughput-chart" height="120" style="width:100%;display:block"></canvas>
      </div>
    </div>
  </div>

  <!-- Month grids -->
  <div class="row two" id="grids-row"></div>

  <!-- Activity -->
  <div class="row one">
    <div class="panel">
      <div class="panel-head">
        <div class="ph-title">Recent Activity</div>
      </div>
      <div class="panel-body" style="padding:0 16px">
        <div class="act-list" id="act-list">
          <div style="color:var(--muted);padding:12px 0;font-size:12px">waiting…</div>
        </div>
      </div>
    </div>
  </div>
</div>

<script>
const $ = s => document.querySelector(s);
const $$ = s => document.querySelectorAll(s);

async function poll() {
  try { const r = await fetch('/api'); return await r.json(); } catch { return null; }
}

function fmtAge(m) {
  if (m == null) return '—';
  if (m < 2) return 'now';
  if (m < 60) return Math.round(m) + 'm ago';
  return (m/60).toFixed(1) + 'h ago';
}
function fmtEta(h) {
  if (h == null) return '—';
  if (h < 1) return '<1h';
  if (h < 48) return h.toFixed(1) + 'h';
  return (h/24).toFixed(1) + 'd';
}
function fmtDisk(statvfs) {
  if (!statvfs) return {free:'—',pct:'—'};
  let total, free;
  if (Array.isArray(statvfs)) {
    // os.statvfs() serializes as list: [f_bsize, f_frsize, f_blocks, f_bfree, f_bavail, ...]
    total = statvfs[2] * statvfs[0];  // f_blocks * f_bsize
    free  = statvfs[4] * statvfs[0];  // f_bavail * f_bsize
  } else {
    total = statvfs.f_blocks * statvfs.f_bsize;
    free  = statvfs.f_bavail * statvfs.f_bsize;
  }
  const used  = total - free;
  const pct   = (used/total*100).toFixed(0) + '%';
  const gb    = (free/1e9).toFixed(0) + 'G free';
  return {free: gb, pct};
}
function fmtUptime(s) {
  if (!s) return '—';
  const h = Math.floor(s/3600), m = Math.floor((s%3600)/60);
  return h + 'h ' + m + 'm';
}

function stageClass(stage) {
  const s = stage.toLowerCase();
  if (s.includes('submitting')) return 'submitting';
  if (s.includes('rate-limited') || s.includes('maintenance')) return s.includes('maintenance') ? 'maint' : 'rate';
  if (s.includes('error') || s.includes('failed') || s.includes('licence')) return 'error';
  if (s.includes('started') || s.includes('working')) return 'working';
  return 'working';
}

function updateDataset(id, ds, accentCls) {
  const pct = ds.pct || 0;
  const run = ds.running;
  const fails = (ds.failures || []).length;
  const stalled = !run && pct < 100 && ds.recent_age_min > 60;

  $('#' + id + '-pct').textContent = pct.toFixed(1) + '%';
  $('#' + id + '-frac').textContent = ds.n + '/' + ds.expected;
  $('#' + id + '-bar').style.width = Math.min(pct, 100) + '%';

  const badge = $('#' + id + '-badge');
  if (pct >= 100) {
    badge.textContent = 'complete'; badge.className = 'ph-badge running';
  } else if (!run && fails > 0) {
    badge.textContent = fails + ' failed'; badge.className = 'ph-badge error';
  } else if (stalled) {
    badge.textContent = 'stalled'; badge.className = 'ph-badge warn';
  } else if (run) {
    badge.textContent = 'running'; badge.className = 'ph-badge running';
  } else {
    badge.textContent = 'idle'; badge.className = 'ph-badge idle';
  }

  const pre = id === 'era5' ? 'e' : id === 'era5-ml1' ? 'ml' : 'g';
  const eta = fmtEta(ds.eta_h);
  const etaEl = $('#' + pre + '-eta');
  etaEl.textContent = eta;
  etaEl.className = 'sc-val' + (eta === '—' && pct < 100 ? ' warn' : '');

  const lastEl = $('#' + pre + '-last');
  const ageStr = fmtAge(ds.recent_age_min);
  lastEl.textContent = ageStr;
  lastEl.className = 'sc-val' + (ds.recent_age_min > 90 ? ' warn' : '');

  const rateEl = $('#' + pre + '-rate');
  rateEl.textContent = ds.files_last_hr || '0';
  rateEl.className = 'sc-val' + (run && !ds.files_last_hr ? ' warn' : run ? ' accent' : '');

  $('#' + pre + '-workers').textContent = ds.workers || 0;

  const curEl = $('#' + id + '-current');
  if (ds.current) {
    curEl.style.display = 'block';
    $('#' + id + '-cur-text').textContent = ds.current === 'in-flight' ? 'submitting to CDS…' : ds.current;
  } else {
    curEl.style.display = 'none';
  }

  const failEl = $('#' + id + '-fails');
  if (fails) {
    failEl.innerHTML = ds.failures.slice(0, 8).map(([mo, r]) =>
      `<div class="fail-item"><span class="fail-mo">${mo}</span><span class="fail-reason">${r.slice(0, 80)}</span></div>`
    ).join('');
  } else {
    failEl.innerHTML = '';
  }
}

function updateWorkers(workers, tbodyId, countId) {
  const tbody = $('#' + tbodyId);
  $('#' + countId).textContent = workers.length + ' active';
  if (!workers.length) {
    tbody.innerHTML = '<tr><td colspan="4" style="color:var(--muted);text-align:center;padding:16px;font-size:12px">no active workers</td></tr>';
    return;
  }
  tbody.innerHTML = workers.map(w => {
    const sc = stageClass(w.stage);
    const elapsed = w.elapsed_s < 60 ? Math.round(w.elapsed_s) + 's' :
                    (w.elapsed_s/60).toFixed(1) + 'm';
    return `<tr>
      <td class="wid">${w.id}</td>
      <td class="wmonth">${w.month}</td>
      <td><span class="wstage ${sc}"><span class="wstage-dot"></span><span class="wstage-text">${w.stage}</span></span></td>
      <td class="welapsed">${elapsed}</td>
    </tr>`;
  }).join('');
}

function updateGpmWorkers(workers) {
  const tbody = $('#gpm-workers-body');
  $('#gpm-w-count').textContent = workers.length + ' active';
  if (!workers.length) {
    tbody.innerHTML = '<tr><td colspan="3" style="color:var(--muted);text-align:center;padding:16px;font-size:12px">no active workers</td></tr>';
    return;
  }
  tbody.innerHTML = workers.map(w => {
    const sc = stageClass(w.stage);
    return `<tr>
      <td class="wmonth">${w.month}</td>
      <td><span class="wstage ${sc}"><span class="wstage-dot"></span><span class="wstage-text">${w.stage}</span></span></td>
      <td style="color:var(--muted);font-size:12px;text-align:center">${w.attempt}</td>
    </tr>`;
  }).join('');
}

function gridHTML(ds, title, cells) {
  if (!cells || !cells.length) return '';
  const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const MSHORT = ['J','F','M','A','M','J','J','A','S','O','N','D'];
  const legend = [['var(--green)','done'],['var(--red)','failed'],['var(--amber)','no data'],['var(--border2)','missing']]
    .map(([c,l]) => `<div class="ml-item"><div class="ml-swatch" style="background:${c}"></div>${l}</div>`).join('');
  const head = '<th class="mg-yr"></th>' + MSHORT.map(m=>`<th>${m}</th>`).join('') + '<th class="mg-cnt"></th>';
  const rows = cells.map(r => {
    const tds = r.cells.map(c => {
      const clr = c.color === '#3fb950' ? 'var(--green)' :
                  c.color === '#f85149' ? 'var(--red)' :
                  c.color === '#e3b341' ? 'var(--amber)' :
                  c.color === '#161b22' ? 'var(--bg)' : 'var(--border2)';
      return `<td><div class="mg-cell" title="${c.ym}: ${c.tip}" style="background:${clr}"></div></td>`;
    }).join('');
    const doneStyle = r.done === 12 ? 'color:var(--green);font-weight:600' : '';
    return `<tr><td class="mg-yr">${r.year}</td>${tds}<td class="mg-cnt" style="${doneStyle}">${r.done}</td></tr>`;
  }).join('');
  return `<div class="panel">
    <div class="panel-head"><div class="ph-title">${title}</div></div>
    <div class="panel-body">
      <div class="mgrid-legend">${legend}</div>
      <div class="mgrid-wrap"><table class="mgrid"><thead><tr>${head}</tr></thead><tbody>${rows}</tbody></table></div>
    </div>
  </div>`;
}

function updateActivity(activity) {
  const el = $('#act-list');
  if (!activity || !activity.length) {
    el.innerHTML = '<div style="color:var(--muted);padding:12px 0;font-size:12px">waiting for activity…</div>';
    return;
  }
  el.innerHTML = activity.slice().reverse().map(a =>
    `<div class="act-item">
      <span class="act-ds ${a.ds}">${a.ds.toUpperCase()}</span>
      <span class="act-month">${a.month}</span>
      <span class="act-msg">${a.msg}</span>
    </div>`
  ).join('');
}

function drawChart(hourly) {
  const canvas = $('#throughput-chart');
  if (!canvas) return;
  canvas.width = canvas.offsetWidth * devicePixelRatio;
  canvas.height = 120 * devicePixelRatio;
  canvas.style.height = '120px';
  const ctx = canvas.getContext('2d');
  ctx.scale(devicePixelRatio, devicePixelRatio);
  const W = canvas.offsetWidth, H = 120;

  const gpm  = (hourly && hourly.gpm)  || [];
  const era5_core = (hourly && hourly.era5_core) || [];
  const era5_ml1  = (hourly && hourly.era5_more_labels_1) || [];
  if (!gpm.length) return;

  // merge x-axis from all series
  const tsSet = new Set([...gpm.map(d=>d.ts), ...era5_core.map(d=>d.ts), ...era5_ml1.map(d=>d.ts)]);
  const ticks = [...tsSet].sort((a,b)=>a-b);
  const gpmMap  = Object.fromEntries(gpm.map(d=>[d.ts, d.count]));
  const era5CoreMap = Object.fromEntries(era5_core.map(d=>[d.ts, d.count]));
  const era5Ml1Map  = Object.fromEntries(era5_ml1.map(d=>[d.ts, d.count]));

  const maxCount = Math.max(1, ...ticks.map(t => Math.max(gpmMap[t]||0, era5CoreMap[t]||0, era5Ml1Map[t]||0)));
  const n = ticks.length;
  const pad = { top: 8, bottom: 28, left: 28, right: 8 };
  const chartW = W - pad.left - pad.right;
  const chartH = H - pad.top - pad.bottom;
  const barW = Math.max(1, chartW / n - 1);

  // background
  ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue('--surface').trim();
  ctx.fillRect(0, 0, W, H);

  // grid lines
  const gridSteps = 3;
  ctx.strokeStyle = 'rgba(255,255,255,.06)';
  ctx.lineWidth = 1;
  for (let i = 0; i <= gridSteps; i++) {
    const y = pad.top + chartH - (i / gridSteps) * chartH;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(pad.left + chartW, y); ctx.stroke();
    if (i > 0) {
      ctx.fillStyle = 'rgba(255,255,255,.25)';
      ctx.font = `${9 * devicePixelRatio / devicePixelRatio}px IBM Plex Mono, monospace`;
      ctx.textAlign = 'right';
      ctx.fillText(Math.round(maxCount * i / gridSteps), pad.left - 4, y + 3);
    }
  }

  // bars — GPM (blue), ERA5 core (green), ERA5 ml1 (amber), side by side
  const slotW = chartW / n;
  const bw = Math.max(1, slotW * 0.28);
  ticks.forEach((ts, i) => {
    const x = pad.left + i * slotW;

    const gc = gpmMap[ts] || 0;
    if (gc > 0) {
      const bh = (gc / maxCount) * chartH;
      ctx.fillStyle = 'rgba(64,196,255,.7)';
      ctx.fillRect(x + 1, pad.top + chartH - bh, bw, bh);
    }

    const ecc = era5CoreMap[ts] || 0;
    if (ecc > 0) {
      const bh = (ecc / maxCount) * chartH;
      ctx.fillStyle = 'rgba(0,230,118,.7)';
      ctx.fillRect(x + bw + 1, pad.top + chartH - bh, bw, bh);
    }

    const emc = era5Ml1Map[ts] || 0;
    if (emc > 0) {
      const bh = (emc / maxCount) * chartH;
      ctx.fillStyle = 'rgba(255,171,0,.7)';
      ctx.fillRect(x + bw * 2 + 2, pad.top + chartH - bh, bw, bh);
    }
  });

  // x-axis hour labels — every 6h
  ctx.fillStyle = 'rgba(255,255,255,.3)';
  ctx.font = `9px IBM Plex Mono, monospace`;
  ctx.textAlign = 'center';
  ticks.forEach((ts, i) => {
    const d = new Date(ts * 1000);
    if (d.getHours() % 6 === 0) {
      const x = pad.left + (i + 0.5) * slotW;
      ctx.fillText(d.getHours() + 'h', x, H - 8);
    }
  });

  // x-axis baseline
  ctx.strokeStyle = 'rgba(255,255,255,.12)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(pad.left, pad.top + chartH);
  ctx.lineTo(pad.left + chartW, pad.top + chartH);
  ctx.stroke();
}

function render(data) {
  if (!data) return;
  const d = data.datasets;

  // topbar
  const total = (d.era5_core.n || 0) + (d.era5_more_labels_1.n || 0) + (d.gpm.n || 0);
  const totalExp = (d.era5_core.expected || 0) + (d.era5_more_labels_1.expected || 0) + (d.gpm.expected || 0);
  $('#tb-total').textContent = total + '/' + totalExp;
  const dk = fmtDisk(data.disk);
  $('#tb-disk').textContent = dk.free;
  const diskPctEl = $('#tb-diskpct');
  diskPctEl.textContent = dk.pct;
  $('#tb-uptime').textContent = fmtUptime(data.uptime);

  updateDataset('era5', d.era5_core, 'green');
  updateDataset('era5-ml1', d.era5_more_labels_1, 'blue');
  updateDataset('gpm',  d.gpm,  'blue');
  updateWorkers(data.era5_workers || [], 'era5-workers-body', 'w-count');
  updateWorkers(data.era5_ml1_workers || [], 'era5-ml1-workers-body', 'ml1-w-count');
  updateGpmWorkers(data.gpm_workers || []);

  const gridsEl = $('#grids-row');
  gridsEl.innerHTML =
    gridHTML('era5_core', 'ERA5 Core · months downloaded', data.grids && data.grids.era5_core) +
    gridHTML('era5_more_labels_1', 'ERA5 More Labels 1 · months downloaded', data.grids && data.grids.era5_more_labels_1) +
    gridHTML('gpm',  'GPM · months downloaded',  data.grids && data.grids.gpm);

  updateActivity(data.activity);
  _lastHourly = data.hourly;
  drawChart(data.hourly);

  const now = new Date();
  $('#clock').textContent = now.toLocaleTimeString('en-NZ', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
}

let _lastHourly = null;
window.addEventListener('resize', () => { if (_lastHourly) drawChart(_lastHourly); });

(async function loop() {
  render(await poll());
  setTimeout(loop, 5000);
})();
</script>
</body>
</html>"""

if __name__ == "__main__":
    import sys
    if "--json" in sys.argv:
        print(json.dumps(api_data(), indent=2))
    else:
        print(f"dashboard on :{PORT}", flush=True)
        HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
