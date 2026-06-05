#!/usr/bin/env python3
"""Tiny dependency-free HTTP status dashboard for the pod-ml dataset downloads.

Scans cache dirs, process table, and log files; renders an auto-refreshing HTML page.
Runs on the VM; reachable from the LAN at http://<vm-ip>:8000. Read-only.

Launch (detached, survives SSH):
    setsid python3 scripts/status_server.py </dev/null >status_server.log 2>&1 &
"""
from __future__ import annotations

import glob
import json
import os
import re
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO = Path("/home/claude/cyber-deck-and-weather-station/pod-ml")
RAW = REPO / "data" / "raw"
PORT = 8000


# ---------------------------------------------------------------------------
# Process inspection
# ---------------------------------------------------------------------------

def _proc_cmdlines() -> list[str]:
    cmds = []
    for cl in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            cmds.append(Path(cl).read_bytes().replace(b"\0", b" ").decode("utf-8", "replace"))
        except OSError:
            pass
    return cmds


def _running(pattern: str) -> int:
    return sum(1 for c in _proc_cmdlines() if pattern in c and "status_server" not in c)


def _worker_count(pattern: str) -> int | None:
    for cmd in _proc_cmdlines():
        if pattern not in cmd or "status_server" in cmd:
            continue
        m = re.search(r"--workers\s+(\d+)", cmd)
        if m:
            return int(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Log parsing
# ---------------------------------------------------------------------------

def _tail(path: Path, n: int = 2000) -> list[str]:
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - n * 120))
            return f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []


def _parse_gpm_log(log_path: Path) -> dict:
    """Return {current, workers, failures: [(month, reason)], no_data: [month]}."""
    lines = [l for l in _tail(log_path) if re.match(r"\[\d{4}-\d{2}\]", l.strip())]
    failures: dict[str, str] = {}
    no_data: list[str] = []
    current: str | None = None
    workers: int | None = None

    for line in lines:
        line = line.strip()
        m = re.match(r"\[(\d{4}-\d{2})\] (.+)", line)
        if not m:
            continue
        month, msg = m.group(1), m.group(2)

        if "SKIPPED after" in msg:
            reason = msg.split(":", 1)[-1].strip() if ":" in msg else msg
            failures[month] = reason[:80]
        elif "INCOMPLETE" in msg:
            failures[month] = msg[:80]
        elif "no granules found" in msg:
            no_data.append(month)
            failures.pop(month, None)
        elif re.match(r"\d+ granules -> \d+ steps ->", msg):
            failures.pop(month, None)
        elif re.search(r"\d+ granules,\s+\d+ workers", msg):
            current = month
            wm = re.search(r"(\d+) workers", msg)
            if wm:
                workers = int(wm.group(1))
        elif "Harmony request" in msg:
            current = month

    return {
        "current": current,
        "workers": workers,
        "failures": list(failures.items()),
        "no_data": sorted(set(no_data)),
    }


def _parse_era5_log(log_path: Path) -> dict:
    """Return {current, workers, failures: [(month, reason)], cds_status}."""
    lines = _tail(log_path, n=1000)
    failures: dict[str, str] = {}
    workers: int | None = None
    cds_status: str | None = None

    for line in lines:
        line = line.strip()
        m = re.search(r"ERA5-Land CDS: \d+ months, (\d+) parallel", line)
        if m:
            workers = int(m.group(1))
        # [W00] prefix is optional — new worker-aware format; old logs lack it
        m = re.match(r"(?:\[W..\] )?\[(\d{4}-\d{2})\] FAILED: (.+)", line)
        if m:
            failures[m.group(1)] = m.group(2)[:80]
            continue
        m = re.match(r"(?:\[W..\] )?\[(\d{4}-\d{2})\] (cached|\d+s)", line)
        if m:
            failures.pop(m.group(1), None)
            continue
        m = re.search(r"status has been updated to (\w+)", line)
        if m:
            cds_status = m.group(1)

    # "in-flight" if the last CDS block has no following [YYYY-MM] completion
    in_flight = False
    for line in reversed(lines[-300:]):
        line = line.strip()
        if re.match(r"(?:\[W..\] )?\[(\d{4}-\d{2})\] (cached|\d+s|FAILED)", line):
            in_flight = False
            break
        if "status has been updated to accepted" in line or "status has been updated to running" in line:
            in_flight = True

    return {
        "current": "in-flight" if in_flight else None,
        "workers": workers,
        "failures": list(failures.items()),
        "cds_status": cds_status,
    }


def _parse_era5_workers(log_path: Path) -> list[dict]:
    """Parse [W..] [...] lines to reconstruct per-worker state.

    Returns list of {id, month, stage, elapsed_s, line_age_s}, newest first.
    Only returns workers seen in the last 10 minutes.
    """
    lines = _tail(log_path, n=600)
    now = time.time()
    # Walk backwards: each [W..] line is the *latest* stage for that worker+month combo
    seen: set[tuple[str, str]] = set()  # (worker_id, month)
    workers: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        m = re.match(r"\[(W..)\] \[(\d{4}-\d{2})\] (.+)", line)
        if not m:
            continue
        wid, month, rest = m.group(1), m.group(2), m.group(3)
        key = (wid, month)
        if key in seen:
            continue
        seen.add(key)

        # Extract stage
        if rest.startswith("started"):
            stage, extra = "started", ""
        elif rest.startswith("submitting"):
            stage, extra = "submitting", ""
        elif "rate-limited retry" in rest:
            stage = "rate-limited"
            rm = re.search(r"retry (\d+/\d+)", rest)
            extra = f" {rm.group(1)}" if rm else ""
        elif "cached" in rest:
            stage, extra = "cached", ""
            continue  # skip — already done, not actively working
        elif "FAILED:" in rest:
            stage, extra = "FAILED", ""
        elif "s" in rest and "MB" in rest:
            stage = "complete"
            m2 = re.match(r"(\d+)s (\d+)MB", rest)
            extra = f" {m2.group(1)}s {m2.group(2)}MB" if m2 else ""
            continue  # skip — completed, not actively working
        else:
            stage, extra = "working", ""

        # Estimate line age from position in tail (rough)
        line_age_s = (len(lines) - lines.index(line)) * 0.5  # ~500 chars/s estimate

        workers.append({
            "id": wid,
            "month": month,
            "stage": stage + extra,
            "elapsed_s": line_age_s,
        })

        # Only show recent workers (last 10 min from log tail)
        if len(workers) >= 8:
            break

    return [w for w in workers if w["elapsed_s"] < 600]


# ---------------------------------------------------------------------------
# Summary stats
# ---------------------------------------------------------------------------

def _stats(pattern: str, expected: int) -> dict:
    files = sorted(glob.glob(pattern), key=os.path.getmtime)
    now = time.time()
    last_hr = sum(1 for f in files if now - os.path.getmtime(f) < 3600)
    recent, recent_age = ("-", None)
    if files:
        recent = os.path.basename(files[-1])
        recent_age = (now - os.path.getmtime(files[-1])) / 60.0
    remaining = max(expected - len(files), 0)
    eta_h = (remaining / last_hr) if last_hr else None
    return {
        "n": len(files), "expected": expected,
        "pct": 100.0 * len(files) / expected if expected else 0.0,
        "last_hr": last_hr, "recent": recent, "recent_age": recent_age,
        "eta_h": eta_h, "files": files,
    }


# ---------------------------------------------------------------------------
# Month completion grid
# ---------------------------------------------------------------------------

def _month_grid(files: list[str], year_start: int, year_end: int,
                failures: list[tuple[str, str]], no_data: list[str]) -> str:
    done = set()
    for f in files:
        m = re.search(r"(\d{4})-(\d{2})", os.path.basename(f))
        if m:
            done.add(f"{m.group(1)}-{m.group(2)}")

    fail_map = dict(failures)
    no_data_set = set(no_data)
    now = time.localtime()
    this_ym = f"{now.tm_year}-{now.tm_mon:02d}"

    month_labels = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
    header = "<tr><th style='color:#8b949e;font-size:11px;padding:2px 4px'>yr</th>"
    header += "".join(f"<th style='color:#8b949e;font-size:11px;width:18px;padding:2px 2px'>{lbl}</th>"
                      for lbl in month_labels)
    header += "<th style='color:#8b949e;font-size:11px;padding:2px 8px'>✓</th></tr>"

    rows = header
    for yr in range(year_end, year_start - 1, -1):
        yr_done = sum(1 for mo in range(1, 13) if f"{yr}-{mo:02d}" in done)
        cells = f"<td style='color:#8b949e;font-size:11px;white-space:nowrap;padding:2px 4px'>{yr}</td>"
        for mo in range(1, 13):
            ym = f"{yr}-{mo:02d}"
            if ym in done:
                col, tip = "#3fb950", "downloaded"
            elif ym in fail_map:
                col, tip = "#f85149", fail_map[ym]
            elif ym in no_data_set:
                col, tip = "#e3b341", "no granules (future/pre-record)"
            elif ym > this_ym:
                col, tip = "#161b22", "future"
            else:
                col, tip = "#30363d", "missing"
            cells += (f"<td style='padding:1px'>"
                      f"<div title='{ym}: {tip}' "
                      f"style='width:14px;height:14px;border-radius:2px;background:{col}'></div></td>")
        cells += f"<td style='color:#8b949e;font-size:11px;padding:2px 8px'>{yr_done}</td>"
        rows += f"<tr>{cells}</tr>"

    return f"<table style='border-collapse:collapse;margin-top:4px'>{rows}</table>"


# ---------------------------------------------------------------------------
# HTML assembly
# ---------------------------------------------------------------------------


def _era5_workers_html(workers: list[dict]) -> str:
    """Render a live per-worker table for the dashboard."""
    if not workers:
        return "<p style='color:#484f58;font-size:12px;margin-top:8px'>No active workers in the last 10 min.</p>"
    stage_colors = {
        "started": "#58a6ff", "submitting": "#79c0ff", "rate-limited": "#e3b341",
        "FAILED": "#f85149", "complete": "#3fb950",
    }
    rows = ""
    for w in workers:
        stage = w["stage"]
        base = stage.split()[0] if " " in stage else stage
        color = stage_colors.get(base, "#8b949e")
        rows += (
            f"<tr>"
            f"<td style='font-family:monospace;font-size:12px;color:#c9d1d9;padding:3px 8px'>{w['id']}</td>"
            f"<td style='font-family:monospace;font-size:12px;color:#c9d1d9;padding:3px 8px'>{w['month']}</td>"
            f"<td style='font-size:12px;color:{color};padding:3px 8px'>{stage}</td>"
            f"<td style='font-size:11px;color:#8b949e;padding:3px 8px'>~{w['elapsed_s']:.0f}s</td>"
            f"</tr>"
        )
    return f"""<table style='border-collapse:collapse;margin-top:6px;width:100%;max-width:600px'>
    <tr style='border-bottom:1px solid #21262d'>
      <th style='color:#8b949e;font-size:11px;text-align:left;padding:4px 8px'>W</th>
      <th style='color:#8b949e;font-size:11px;text-align:left;padding:4px 8px'>month</th>
      <th style='color:#8b949e;font-size:11px;text-align:left;padding:4px 8px'>stage</th>
      <th style='color:#8b949e;font-size:11px;text-align:left;padding:4px 8px'>age</th>
    </tr>
    {rows}
</table>"""



def _failure_html(failures: list[tuple[str, str]], label: str) -> str:
    if not failures:
        return ""
    rows = "".join(
        f"<tr>"
        f"<td style='color:#f85149;font-family:monospace;font-size:12px;white-space:nowrap;padding:2px 8px 2px 0'>{mo}</td>"
        f"<td style='color:#8b949e;font-size:12px'>{reason}</td>"
        f"</tr>"
        for mo, reason in sorted(failures, reverse=True)
    )
    return (f"<details style='margin-top:10px'>"
            f"<summary style='color:#f85149;cursor:pointer;font-size:13px;user-select:none'>"
            f"⚠ {label} ({len(failures)})</summary>"
            f"<table style='margin-top:6px;border-collapse:collapse'>{rows}</table>"
            f"</details>")


def _status_badge(log_info: dict, running: int) -> str:
    if not running:
        return "<span style='color:#8b949e'>○ idle</span>"
    parts = ["<span style='color:#3fb950'>●</span>"]
    if log_info.get("workers"):
        parts.append(f"{log_info['workers']} workers")
    cur = log_info.get("current")
    if cur and cur != "in-flight":
        parts.append(f"→ <b>{cur}</b>")
    cds = log_info.get("cds_status")
    if cds and (not cur or cur == "in-flight"):
        parts.append(f"[CDS: {cds}]")
    return " ".join(parts)


def _summary_row(name: str, s: dict, running: int, log_info: dict, note: str = "") -> str:
    color = "#3fb950" if running else ("#58a6ff" if s["pct"] >= 100 else "#8b949e")
    age = f"{s['recent_age']:.0f} min ago" if s["recent_age"] is not None else "-"
    if s["eta_h"] is not None:
        eta = f"{s['eta_h']:.1f} h"
    elif s["pct"] >= 100:
        eta = "done"
    else:
        eta = "stalled"
    badge = _status_badge(log_info, running)
    bar_w = min(s["pct"] * 2.2, 220)
    return f"""
    <tr>
      <td><b>{name}</b><br><small style='color:#8b949e'>{note}</small></td>
      <td>{s['n']} / {s['expected']}<br><small style='color:#8b949e'>{s['pct']:.1f}%</small></td>
      <td><div style="background:#21262d;border-radius:4px;width:220px">
          <div style="background:{color};width:{bar_w:.0f}px;height:14px;border-radius:4px"></div></div></td>
      <td style='color:#8b949e'>{s['last_hr']}/hr</td>
      <td style='color:#8b949e'>{eta}</td>
      <td style='font-family:monospace;font-size:12px'>{s['recent']}<br>
          <small style='color:#8b949e'>{age}</small></td>
      <td>{badge}</td>
    </tr>"""


# ---------------------------------------------------------------------------
# State collection (shared by the HTML view and the /status.json API)
# ---------------------------------------------------------------------------

def _collect() -> dict:
    """Gather every download's stats + log-derived state once. Source of truth for both outputs."""
    era5_s = _stats(str(RAW / "era5_grid" / "era5land_nz_*.nc"), 180)
    gpm_s  = _stats(str(RAW / "gpm_grid"  / "gpm_*.nc"),          295)
    om_files = glob.glob(str(RAW / "openmeteo" / "*.csv"))
    dem_ok = (RAW / "dem_nz.nc").exists()

    gpm_log  = _parse_gpm_log(REPO / "gpm_pull.log")
    era5_log = _parse_era5_log(REPO / "era5_pull.log")

    gpm_run  = _running("download_gpm_harmony")
    era5_run = _running("download_era5_grid")

    if gpm_run and not gpm_log["workers"]:
        gpm_log["workers"] = _worker_count("download_gpm_harmony")
    if era5_run and not era5_log["workers"]:
        era5_log["workers"] = _worker_count("download_era5_grid")

    return {
        "era5_s": era5_s, "gpm_s": gpm_s, "om_files": om_files, "dem_ok": dem_ok,
        "gpm_log": gpm_log, "era5_log": era5_log,
        "gpm_run": gpm_run, "era5_run": era5_run,
    }


def _ds_json(s: dict, running: int, log_info: dict) -> dict:
    """Flatten one dataset's stats + log state into a stable JSON shape for the agent."""
    d = {
        "n": s["n"], "expected": s["expected"], "pct": round(s["pct"], 1),
        "running": bool(running), "workers": log_info.get("workers"),
        "current": log_info.get("current"),
        "files_last_hr": s["last_hr"],
        "recent": s["recent"],
        "recent_age_min": round(s["recent_age"], 1) if s["recent_age"] is not None else None,
        "eta_h": round(s["eta_h"], 1) if s["eta_h"] is not None else None,
        "failures": log_info.get("failures", []),
        "no_data": log_info.get("no_data", []),
    }
    if "cds_status" in log_info:
        d["cds_status"] = log_info.get("cds_status")
    return d


def status_json() -> dict:
    """Machine-readable status for the management agent (served at /status.json)."""
    st = _collect()
    stalled = lambda s, run: (not run) and s["pct"] < 100 and s["eta_h"] is None
    return {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "datasets": {
            "gpm":  {**_ds_json(st["gpm_s"],  st["gpm_run"],  st["gpm_log"]),
                     "stalled": stalled(st["gpm_s"], st["gpm_run"])},
            "era5": {**_ds_json(st["era5_s"], st["era5_run"], st["era5_log"]),
                     "stalled": stalled(st["era5_s"], st["era5_run"])},
            "dem":  {"n": int(st["dem_ok"]), "expected": 1,
                     "pct": 100.0 if st["dem_ok"] else 0.0, "running": False},
            "openmeteo": {"n": len(st["om_files"]), "running": False},
        },
    }


def render() -> str:
    st = _collect()
    era5_s, gpm_s = st["era5_s"], st["gpm_s"]
    om_files, dem_ok = st["om_files"], st["dem_ok"]
    gpm_log, era5_log = st["gpm_log"], st["era5_log"]
    gpm_run, era5_run = st["gpm_run"], st["era5_run"]
    era5_workers = _parse_era5_workers(REPO / "era5_pull.log")
    era5_workers_html = _era5_workers_html(era5_workers)

    _empty = {"n": 0, "expected": 1, "pct": 0.0, "last_hr": 0,
              "recent": "-", "recent_age": None, "eta_h": None, "files": []}
    dem_s = {**_empty, "n": int(dem_ok), "pct": 100.0 if dem_ok else 0.0,
             "expected": 1, "recent": "dem_nz.nc" if dem_ok else "-"}
    om_s  = {**_empty, "n": len(om_files), "expected": max(len(om_files), 5),
             "pct": 100.0 if om_files else 0.0, "recent": "points" if om_files else "-"}

    summary = (
        _summary_row("ERA5-Land (CDS, 0.1°)",      era5_s, era5_run, era5_log, "features: sp/t2m/d2m/tp")
      + _summary_row("GPM IMERG (direct, 0.1°)",   gpm_s,  gpm_run,  gpm_log,  "rain labels, 30-min")
      + _summary_row("DEM (ETOPO)",                 dem_s,  0,        {},        "elevation (one-time)")
      + _summary_row("Open-Meteo (validation)",     om_s,   0,        {},        "hourly cron, real-time")
    )

    failures_html = (
        _failure_html(gpm_log["failures"],  "GPM failures")
      + _failure_html(era5_log["failures"], "ERA5 failures")
    )

    legend = "".join(
        f"<span style='display:inline-flex;align-items:center;gap:4px;margin-right:14px'>"
        f"<span style='width:12px;height:12px;border-radius:2px;background:{c};display:inline-block'></span>"
        f"<span style='color:#8b949e;font-size:12px'>{lbl}</span></span>"
        for c, lbl in [("#3fb950","done"), ("#f85149","failed"), ("#e3b341","no data"), ("#30363d","missing")]
    )

    gpm_grid  = _month_grid(gpm_s["files"],  2000, 2026, gpm_log["failures"],  gpm_log["no_data"])
    era5_grid = _month_grid(era5_s["files"], 2010, 2026, era5_log["failures"], [])

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="30">
<title>pod-ml downloads</title>
<style>
 body{{background:#0d1117;color:#c9d1d9;font:14px system-ui,sans-serif;margin:24px}}
 h1{{font-size:18px}}
 h2{{font-size:13px;color:#8b949e;margin:20px 0 4px;text-transform:uppercase;letter-spacing:.05em}}
 table.s{{border-collapse:collapse;width:100%;max-width:1020px}}
 table.s td,table.s th{{padding:8px 12px;border-bottom:1px solid #21262d;text-align:left;vertical-align:top}}
 table.s th{{color:#8b949e;font-weight:600;font-size:12px;text-transform:uppercase}}
 details>summary{{list-style:none}} details>summary::-webkit-details-marker{{display:none}}
</style></head><body>
<h1>pod-ml dataset downloads
  <small style='color:#8b949e;font-weight:normal'>· auto-refresh 30s · {time.strftime('%Y-%m-%d %H:%M:%S')}</small>
</h1>

<table class="s">
  <tr>
    <th>dataset</th><th>progress</th><th></th>
    <th>rate</th><th>eta</th><th>latest file</th><th>status</th>
  </tr>
  {summary}
</table>

{failures_html}

<h2 style='margin-top:24px'>ERA5 active workers</h2>
{era5_workers_html}

<h2 style='margin-top:24px'>GPM completed months</h2>
<div style='margin-bottom:6px'>{legend}</div>
{gpm_grid}

<h2 style='margin-top:20px'>ERA5 completed months</h2>
{era5_grid}

<p style='margin-top:16px;color:#8b949e;font-size:12px'>
  ETA = remaining ÷ files/hr (last hour). Hover month cells for detail.
</p>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.rstrip("/") == "/status.json":
            body = json.dumps(status_json(), indent=2).encode("utf-8")
            ctype = "application/json; charset=utf-8"
        else:
            body = render().encode("utf-8")
            ctype = "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    import sys
    if "--json" in sys.argv:
        # One-shot machine-readable dump — lets podctl/agents read status without the HTTP server up.
        print(json.dumps(status_json(), indent=2))
    else:
        print(f"status dashboard on :{PORT}", flush=True)
        HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
