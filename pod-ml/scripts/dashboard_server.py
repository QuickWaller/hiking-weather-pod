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

def _parse_era5():
    lines = _tail(REPO / "era5_pull.log", n=1000)
    failures, workers, cds_status = {}, None, None
    for line in lines:
        line = line.strip()
        m = re.search(r"ERA5-Land CDS: \d+ months, (\d+) parallel", line)
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


def _parse_era5_workers():
    """Parse [W..] [...] lines to reconstruct per-worker state."""
    lines = _tail(REPO / "era5_pull.log", n=600)
    seen: set[tuple[str, str]] = set()
    workers: list[dict] = []
    for line in reversed(lines):
        line = line.strip()
        m = re.match(r"\[(W..)\] \[(\d{4}-\d{2})\] (.+)", line)
        if not m: continue
        wid, month, rest = m.group(1), m.group(2), m.group(3)
        key = (wid, month)
        if key in seen: continue
        seen.add(key)
        if rest.startswith("started"):
            stage, extra = "started", ""
        elif rest.startswith("submitting"):
            stage, extra = "submitting", ""
        elif "rate-limited retry" in rest:
            stage = "rate-limited"
            rm = re.search(r"retry (\d+/\d+)", rest)
            extra = f" {rm.group(1)}" if rm else ""
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
    """Recent download activity feed."""
    gpm_lines = _tail(REPO / "gpm_pull.log", n=500)
    era5_lines = _tail(REPO / "era5_pull.log", n=500)
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
            entries.append({"ds": "era5", "month": m.group(1), "msg": f"Downloaded {m.group(3)}MB in {m.group(2)}s"})
        m = re.match(r"(?:\[W..\] )?\[(\d{4}-\d{2})\] cached", line)
        if m:
            entries.append({"ds": "era5", "month": m.group(1), "msg": "Already cached"})
        m = re.match(r"\[(W..)\] \[(\d{4}-\d{2})\] rate-limited retry (\d+/\d+)", line)
        if m:
            entries.append({"ds": "era5", "month": m.group(2), "msg": f"W{m.group(1)} rate-limited, retry {m.group(3)}"})
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

def api_data():
    era5_s = _stats(str(RAW / "era5_grid" / "era5land_nz_*.nc"), 180)
    gpm_s = _stats(str(RAW / "gpm_grid" / "gpm_*.nc"), 295)
    gpm_log = _parse_gpm()
    era5_log = _parse_era5()
    gpm_run = _running("download_gpm_harmony")
    era5_run = _running("download_era5_grid")
    if gpm_run and not gpm_log["workers"]:
        for cmd in _proc_cmdlines():
            if "download_gpm_harmony" in cmd:
                wm = re.search(r"--workers\s+(\d+)", cmd)
                if wm: gpm_log["workers"] = int(wm.group(1)); break
    if era5_run and not era5_log["workers"]:
        for cmd in _proc_cmdlines():
            if "download_era5_grid" in cmd:
                wm = re.search(r"--workers\s+(\d+)", cmd)
                if wm: era5_log["workers"] = int(wm.group(1)); break
    return {
        "ts": int(time.time()),
        "uptime": int(time.time() - STARTED),
        "datasets": {
            "gpm":  {"n": gpm_s["n"], "expected": gpm_s["expected"], "pct": round(gpm_s["pct"], 1),
                     "running": bool(gpm_run), "workers": gpm_log["workers"],
                     "current": gpm_log["current"], "files_last_hr": gpm_s["last_hr"],
                     "recent": gpm_s["recent"], "recent_age_min": round(gpm_s["recent_age"], 1) if gpm_s["recent_age"] else None,
                     "eta_h": round(gpm_s["eta_h"], 1) if gpm_s["eta_h"] else None,
                     "failures": gpm_log["failures"], "no_data": gpm_log["no_data"]},
            "era5": {"n": era5_s["n"], "expected": era5_s["expected"], "pct": round(era5_s["pct"], 1),
                     "running": bool(era5_run), "workers": era5_log["workers"],
                     "current": era5_log["current"], "files_last_hr": era5_s["last_hr"],
                     "recent": era5_s["recent"], "recent_age_min": round(era5_s["recent_age"], 1) if era5_s["recent_age"] else None,
                     "eta_h": round(era5_s["eta_h"], 1) if era5_s["eta_h"] else None,
                     "failures": era5_log["failures"], "cds_status": era5_log["cds_status"]},
        },
        "activity": _activity(),
        "era5_workers": _parse_era5_workers(),
        "grids": {
            "gpm":  _month_grid(gpm_s["files"],  2000, 2026, gpm_log["failures"],  gpm_log["no_data"]),
            "era5": _month_grid(era5_s["files"], 2010, 2026, era5_log["failures"], []),
        },
        "disk": os.statvfs(str(RAW)),
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

HTML = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>pod-ml · live</title>
<style>
:root{--bg:#090c10;--card:#0d1117;--border:#21262d;--text:#c9d1d9;--muted:#8b949e;--green:#3fb950;--red:#f85149;--amber:#e3b341;--blue:#58a6ff}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font:14px/1.5 system-ui,-apple-system,sans-serif;padding:24px;max-width:1100px;margin:0 auto}
h1{font-size:20px;font-weight:600;margin-bottom:20px;display:flex;align-items:center;gap:12px}
h1 .dot{width:8px;height:8px;border-radius:50%;background:var(--green);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.3}}
h1 small{font-weight:400;color:var(--muted);font-size:13px;margin-left:auto}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}
.card{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:20px}
.card h2{font-size:15px;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.card h2 .status{width:10px;height:10px;border-radius:50%}
.card h2 .status.on{background:var(--green);box-shadow:0 0 8px var(--green)}
.card h2 .status.off{background:var(--muted)}
.progress{margin:8px 0 4px}
.progress-bar{height:8px;background:var(--border);border-radius:4px;overflow:hidden;position:relative}
.progress-fill{height:100%;border-radius:4px;transition:width .6s ease;position:relative}
.progress-fill.green{background:linear-gradient(90deg,#238636,var(--green))}
.progress-fill.blue{background:linear-gradient(90deg,#1f6feb,var(--blue))}
.progress-fill.red{background:linear-gradient(90deg,#da3633,var(--red))}
.progress-fill::after{content:'';position:absolute;top:0;left:0;right:0;bottom:0;background:linear-gradient(90deg,transparent 0%,rgba(255,255,255,.1) 50%,transparent 100%);animation:shimmer 2s infinite}
@keyframes shimmer{0%{transform:translateX(-100%)}100%{transform:translateX(200%)}}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:12px}
.stat{text-align:center;padding:8px;background:rgba(255,255,255,.03);border-radius:6px}
.stat .val{font-size:18px;font-weight:600;font-family:monospace}
.stat .lbl{font-size:11px;color:var(--muted);margin-top:2px;text-transform:uppercase}
.badge{display:inline-flex;align-items:center;gap:4px;padding:3px 8px;border-radius:12px;font-size:12px;font-weight:500}
.badge.ok{background:rgba(63,185,80,.15);color:var(--green)}
.badge.warn{background:rgba(227,179,65,.15);color:var(--amber)}
.badge.err{background:rgba(248,81,73,.15);color:var(--red)}
.badge.neutral{background:rgba(139,148,158,.15);color:var(--muted)}
.activity{background:var(--card);border:1px solid var(--border);border-radius:8px;padding:20px;margin-bottom:16px}
.activity h2{font-size:15px;margin-bottom:12px}
.activity-list{max-height:300px;overflow-y:auto}
.activity-item{display:flex;align-items:center;gap:8px;padding:6px 0;border-bottom:1px solid rgba(255,255,255,.04);font-size:13px}
.activity-item .ds{font-family:monospace;font-size:11px;padding:2px 6px;border-radius:4px;font-weight:600}
.activity-item .ds.gpm{background:rgba(88,166,255,.2);color:var(--blue)}
.activity-item .ds.era5{background:rgba(63,185,80,.2);color:var(--green)}
.activity-item .month{font-family:monospace;font-size:12px;color:var(--text)}
.activity-item .msg{color:var(--muted);flex:1}
.footer{text-align:center;color:var(--muted);font-size:11px;padding:16px 0}
.full{grid-column:1/-1}
.failures{margin-top:8px}
.failure-row{display:flex;align-items:center;gap:8px;padding:4px 0;font-size:12px;font-family:monospace}
.failure-row .mo{color:var(--red);font-weight:600}
.failure-row .reason{color:var(--muted)}
.month-grid{border-collapse:collapse;margin-top:4px;width:100%}
.month-grid td,.month-grid th{padding:1px 2px;font-size:11px;text-align:center}
.month-grid th{color:var(--muted);font-weight:400}
.month-grid .yr{color:var(--muted);font-size:11px;white-space:nowrap;padding:2px 6px;text-align:left}
.month-grid .cnt{color:var(--muted);font-size:11px;padding:2px 8px}
.month-grid .cell{width:14px;height:14px;border-radius:2px;display:inline-block;cursor:pointer}
.month-grid .cell:hover{outline:1px solid rgba(255,255,255,.4)}
@media(max-width:700px){.grid{grid-template-columns:1fr}}
</style></head><body>
<h1><span class="dot"></span>pod-ml · live downloads<small id="clock">—</small></h1>
<div class="grid" id="cards"></div>
<div class="grid" id="grids"></div>
<div class="activity" id="activity"><h2>📡 Recent Activity</h2><div class="activity-list" id="feed"></div></div>
<div class="activity" id="workers-box"><h2>🔧 ERA5 Active Workers</h2><div class="activity-list" id="era5-workers"></div></div>
<div class="footer">auto-refresh 5s · dashboard by pod-ops agent</div>
<script>
const $=s=>document.querySelector(s);
const $$=s=>document.querySelectorAll(s);
async function poll(){try{const r=await fetch('/api');return await r.json()}catch(e){return null}}
function fmtAge(m){if(m===null||m===undefined)return'—';if(m<1)return'just now';if(m<60)return Math.round(m)+'m ago';return Math.round(m/60)+'h ago'}
function fmtEta(h){if(h===null||h===undefined)return'—';if(h<1)return'<1h';if(h<24)return h.toFixed(1)+'h';return(h/24).toFixed(1)+'d'}
function fmtPct(v){return v.toFixed(1)+'%'}
function cardHTML(id,name,note,ds){
  const pct=ds.pct, run=ds.running, w=ds.workers||0;
  const age=fmtAge(ds.recent_age_min), eta=fmtEta(ds.eta_h);
  const color=pct>=100?'blue':(run?'green':(ds.failures&&ds.failures.length?'red':'blue'));
  const badgeCls=run?'ok':((ds.failures&&ds.failures.length)?'err':'neutral');
  const badgeText=run?`● ${w} workers`:(ds.failures&&ds.failures.length?`⚠ ${ds.failures.length} failures`:(pct>=100?'✓ done':'○ idle'));
  let cur=ds.current||'';
  if(cur==='in-flight')cur='submitting…';
  const curHTML=cur?`<div style="font-size:11px;color:var(--muted);margin-top:2px">→ ${cur}</div>`:'';
  let failHTML='';
  if(ds.failures&&ds.failures.length){
    failHTML='<div class="failures">'+ds.failures.slice(0,5).map(([mo,r])=>`<div class="failure-row"><span class="mo">${mo}</span><span class="reason">${r}</span></div>`).join('')+'</div>';
  }
  return `<div class="card">
    <h2><span class="status ${run?'on':'off'}"></span>${name}<span class="badge ${badgeCls}" style="margin-left:auto">${badgeText}</span></h2>
    <div style="color:var(--muted);font-size:12px;margin-bottom:8px">${note}</div>
    <div class="progress"><div class="progress-bar"><div class="progress-fill ${color}" style="width:${Math.min(pct,100)}%"></div></div>
    <div style="display:flex;justify-content:space-between;margin-top:4px;font-size:12px"><span style="font-weight:600">${ds.n}/${ds.expected} ${fmtPct(pct)}</span><span style="color:var(--muted)">${eta==='—'&&pct<100?(run?'retrying…':'stalled'):eta}</span></div></div>
    <div class="stats">
      <div class="stat"><div class="val">${ds.files_last_hr}</div><div class="lbl">files/hr</div></div>
      <div class="stat"><div class="val">${w}</div><div class="lbl">workers</div></div>
      <div class="stat"><div class="val">${age}</div><div class="lbl">last file</div></div>
    </div>
    ${curHTML}${failHTML}
  </div>`;
}
function gridHTML(title,data){
  if(!data||!data.length)return'';
  const MONTHS=['J','F','M','A','M','J','J','A','S','O','N','D'];
  let h='<th class="yr">yr</th>'+MONTHS.map(m=>`<th>${m}</th>`).join('')+'<th class="cnt">✓</th>';
  const rows=data.map(r=>{
    let cells='<td class="yr">'+r.year+'</td>';
    r.cells.forEach(c=>{cells+=`<td><span class="cell" title="${c.ym}: ${c.tip}" style="background:${c.color}"></span></td>`});
    cells+='<td class="cnt">'+r.done+'</td>';
    return'<tr>'+cells+'</tr>';
  }).join('');
  return`<div class="card full"><h2>${title}</h2><div style="display:flex;gap:12px;margin-bottom:6px">${[['#3fb950','done'],['#f85149','failed'],['#e3b341','no data'],['#30363d','missing']].map(([c,l])=>`<span style="display:flex;align-items:center;gap:4px;font-size:11px;color:var(--muted)"><span style="width:10px;height:10px;border-radius:2px;background:${c};display:inline-block"></span>${l}</span>`).join('')}</div><table class="month-grid"><tr>${h}</tr>${rows}</table></div>`;
}
function render(data){
  if(!data)return;
  const d=data.datasets;
  const cards=$('#cards');
  cards.innerHTML=
    cardHTML('era5','ERA5-Land','features · 2010–2024 · CDS',d.era5)+
    cardHTML('gpm','GPM IMERG','rain labels · 2000–2026 · Harmony',d.gpm);
  const grids=$('#grids');
  grids.innerHTML=
    gridHTML('GPM completed months',data.grids.gpm)+
    gridHTML('ERA5 completed months',data.grids.era5);
  const feed=$('#feed');
  const act=data.activity||[];
  feed.innerHTML=act.slice().reverse().map(a=>`<div class="activity-item"><span class="ds ${a.ds}">${a.ds.toUpperCase()}</span><span class="month">${a.month}</span><span class="msg">${a.msg}</span></div>`).join('')||'<div style="color:var(--muted);font-size:13px">waiting for activity…</div>';
  const wbox=$('#era5-workers');
  const workers=data.era5_workers||[];
  const colors={started:'#58a6ff',submitting:'#79c0ff','rate-limited':'#e3b341',FAILED:'#f85149',complete:'#3fb950'};
  wbox.innerHTML=workers.length?workers.map(w=>{const b=w.stage.split(' ')[0];return`<div class="activity-item"><span style="font-family:monospace;font-size:12px;color:var(--blue);min-width:30px">${w.id}</span><span class="month">${w.month}</span><span style="font-size:12px;color:${colors[b]||'#8b949e'}">${w.stage}</span><span style="font-size:11px;color:var(--muted);margin-left:auto">~${w.elapsed_s.toFixed(0)}s</span></div>`}).join(''):'<div style="color:var(--muted);font-size:13px">no active workers</div>';
  const now=new Date();
  $('#clock').textContent=now.toLocaleTimeString();
}
(async function loop(){render(await poll());setTimeout(loop,5000)})();
</script></body></html>"""

if __name__ == "__main__":
    import sys
    if "--json" in sys.argv:
        print(json.dumps(api_data(), indent=2))
    else:
        print(f"dashboard on :{PORT}", flush=True)
        HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
