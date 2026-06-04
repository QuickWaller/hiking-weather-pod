#!/usr/bin/env python3
"""Tiny dependency-free HTTP status dashboard for the pod-ml dataset downloads.

Scans the cache dirs + the process table and renders an auto-refreshing HTML page.
Runs on the VM; reachable from the LAN at http://<vm-ip>:8000. Read-only — never
touches the downloads.

Launch (detached, survives SSH):
    setsid python3 scripts/status_server.py </dev/null >status_server.log 2>&1 &
"""
from __future__ import annotations

import glob
import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO = Path("/home/claude/cyber-deck-and-weather-station/pod-ml")
RAW = REPO / "data" / "raw"
PORT = 8000


def _running(pattern: str) -> int:
    """Count live processes whose cmdline contains `pattern` (excludes this server)."""
    n = 0
    for cl in glob.glob("/proc/[0-9]*/cmdline"):
        try:
            cmd = Path(cl).read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if pattern in cmd and "status_server" not in cmd:
            n += 1
    return n


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
        "last_hr": last_hr, "recent": recent, "recent_age": recent_age, "eta_h": eta_h,
    }


def _row(name: str, s: dict, running: int, note: str = "") -> str:
    bar = int(s["pct"] / 2)  # 50-char bar
    color = "#3fb950" if running else ("#58a6ff" if s["pct"] >= 100 else "#8b949e")
    age = f"{s['recent_age']:.0f} min ago" if s["recent_age"] is not None else "-"
    eta = f"{s['eta_h']:.1f} h" if s["eta_h"] is not None else ("done" if s["pct"] >= 100 else "stalled")
    run = f"<span style='color:#3fb950'>● {running} running</span>" if running else "<span style='color:#8b949e'>○ idle</span>"
    return f"""
    <tr>
      <td><b>{name}</b><br><small>{note}</small></td>
      <td>{s['n']} / {s['expected']}<br><small>{s['pct']:.1f}%</small></td>
      <td><div style="background:#21262d;border-radius:4px;width:220px">
          <div style="background:{color};width:{s['pct']*2.2:.0f}px;height:14px;border-radius:4px"></div></div></td>
      <td>{s['last_hr']}/hr</td>
      <td>{eta}</td>
      <td>{s['recent']}<br><small>{age}</small></td>
      <td>{run}</td>
    </tr>"""


def render() -> str:
    era5 = _stats(str(RAW / "era5_grid" / "era5land_nz_*.nc"), 180)   # 2010-2024 x 12
    gpm = _stats(str(RAW / "gpm_grid" / "gpm_*.nc"), 295)             # 2000-06..2024-12
    om_files = glob.glob(str(RAW / "openmeteo" / "*.csv"))
    dem_ok = (RAW / "dem_nz.nc").exists()

    rows = _row("ERA5-Land (CDS, 0.1°)", era5, _running("download_era5_grid"), "features: sp/t2m/d2m + tp")
    rows += _row("GPM IMERG (Harmony, 0.1°)", gpm, _running("download_gpm_harmony"), "rain labels, 30-min")
    dem_pct = 100.0 if dem_ok else 0.0
    rows += _row("DEM (ETOPO)", {"n": int(dem_ok), "expected": 1, "pct": dem_pct,
                                 "last_hr": 0, "recent": "dem_nz.nc" if dem_ok else "-",
                                 "recent_age": None, "eta_h": None}, 0, "elevation (one-time)")
    rows += _row("Open-Meteo (validation)", {"n": len(om_files), "expected": max(len(om_files), 5),
                                             "pct": 100.0 if om_files else 0.0, "last_hr": 0,
                                             "recent": "points" if om_files else "-",
                                             "recent_age": None, "eta_h": None}, 0, "hourly cron, real-time")

    return f"""<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="refresh" content="30">
<title>pod-ml downloads</title>
<style>
 body{{background:#0d1117;color:#c9d1d9;font:14px system-ui,sans-serif;margin:24px}}
 h1{{font-size:18px}} table{{border-collapse:collapse;width:100%;max-width:980px}}
 td,th{{padding:8px 12px;border-bottom:1px solid #21262d;text-align:left;vertical-align:top}}
 th{{color:#8b949e;font-weight:600;font-size:12px;text-transform:uppercase}}
 small{{color:#8b949e}}
</style></head><body>
<h1>pod-ml dataset downloads <small>· auto-refresh 30s · {time.strftime('%Y-%m-%d %H:%M:%S')}</small></h1>
<table>
 <tr><th>dataset</th><th>progress</th><th></th><th>rate</th><th>eta</th><th>latest</th><th>worker</th></tr>
 {rows}
</table>
<p><small>ETA = remaining ÷ (files completed in last hour). "stalled" = nothing finished in the last hour.</small></p>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = render().encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):  # quiet
        pass


if __name__ == "__main__":
    print(f"status dashboard on :{PORT}", flush=True)
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
