#!/usr/bin/env python3
"""
tile_viewer.py — Interactive map tile viewer for pod SD card tiles.

Serves a browser-based pan viewer over a rendered tile directory.
Tiles load lazily as you move around — only the visible window is fetched.

Usage (tiles on this machine):
  python tile_viewer.py ~/tiles/nz_10km_regular

Usage (tiles on VM, view from laptop):
  VM:     python tile_viewer.py ~/tiles/nz_10km_regular
  Laptop: ssh -L 8080:localhost:8080 claude-vm
  Then open http://localhost:8080

Controls:
  Drag       pan
  Arrow keys  move one tile (+ Shift = 5 tiles)
  Home        return to grid centre
"""

import argparse
import http.server
import json
import sys
import threading
import webbrowser
from pathlib import Path
from urllib.parse import urlparse

# ── Embedded viewer HTML ───────────────────────────────────────────────────────
_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Pod Map Viewer</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { background: #111; overflow: hidden; }
canvas { display: block; cursor: grab; user-select: none; }
canvas.drag { cursor: grabbing; }
#hud {
  position: fixed; top: 0; left: 0; right: 0; height: 28px;
  display: flex; align-items: center; gap: 20px; padding: 0 12px;
  background: rgba(0,0,0,0.72); color: #ccc; font: 12px/28px monospace;
  pointer-events: none; z-index: 10;
}
#pos  { color: #7cf; }
#load { color: #fc7; min-width: 90px; }
#hint { margin-left: auto; color: #666; }
</style>
</head>
<body>
<canvas id="c"></canvas>
<div id="hud">
  <span id="pos">loading…</span>
  <span id="load"></span>
  <span id="hint">drag · arrows · Home=centre</span>
</div>
<script>
const TW = 200, TH = 200, HUD = 28;
let meta = null, gsz = 0, cRow = 0, cCol = 0;
let vpX = 0, vpY = 0;
let drag = false, dsx = 0, dsy = 0, vpX0 = 0, vpY0 = 0;
const cache = {};   // key → Image | false (error) | undefined (loading)
let pending = 0;

const canvas = document.getElementById('c');
const ctx    = canvas.getContext('2d');
const posEl  = document.getElementById('pos');
const loadEl = document.getElementById('load');

// placeholder tile (grey border, dark fill)
const ph = (() => {
  const c = document.createElement('canvas'); c.width = TW; c.height = TH;
  const x = c.getContext('2d');
  x.fillStyle = '#1c1c1c'; x.fillRect(0,0,TW,TH);
  x.strokeStyle = '#2a2a2a'; x.strokeRect(0.5,0.5,TW-1,TH-1);
  return c;
})();

function tileKey(r, c) {
  return String(r).padStart(2,'0') + '_' + String(c).padStart(2,'0');
}

function loadTile(r, c) {
  const k = tileKey(r, c);
  if (k in cache) return cache[k];
  cache[k] = undefined;
  pending++;
  loadEl.textContent = 'loading ' + pending + '…';
  const img = new Image();
  img.onload = () => { cache[k] = img;  pending--; if (!pending) loadEl.textContent = ''; render(); };
  img.onerror= () => { cache[k] = false; pending--; if (!pending) loadEl.textContent = ''; };
  img.src = '/tiles/tile_' + k + '.png';
  return undefined;
}

function render() {
  if (!meta) return;
  const W = canvas.width, H = canvas.height;
  ctx.fillStyle = '#111'; ctx.fillRect(0, 0, W, H);

  const c0 = Math.max(0,     Math.floor(vpX / TW));
  const r0 = Math.max(0,     Math.floor((vpY - HUD) / TH));
  const c1 = Math.min(gsz-1, Math.ceil((vpX + W) / TW));
  const r1 = Math.min(gsz-1, Math.ceil((vpY - HUD + H) / TH));

  for (let r = r0; r <= r1; r++) {
    for (let c = c0; c <= c1; c++) {
      const x = c * TW - vpX;
      const y = r * TH - vpY + HUD;
      const img = loadTile(r, c);
      ctx.drawImage(img || ph, x, y);
    }
  }

  // crosshair at viewport centre
  const hx = W / 2, hy = H / 2 + HUD / 2;
  ctx.strokeStyle = 'rgba(255,60,60,0.55)'; ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(hx-14, hy); ctx.lineTo(hx+14, hy);
  ctx.moveTo(hx, hy-14); ctx.lineTo(hx, hy+14);
  ctx.stroke();

  // hud
  const cx = vpX + W/2, cy = vpY + (H-HUD)/2;
  const r = Math.floor(cy / TH), c = Math.floor(cx / TW);
  let txt = '[' + r + ', ' + c + ']';
  if (r >= 0 && r < gsz && c >= 0 && c < gsz) {
    const lat = meta.centre_lat - (r - cRow) * meta.tile_km / 111.0;
    const lon = meta.centre_lon + (c - cCol) * meta.tile_km /
                (111.0 * Math.cos(meta.centre_lat * Math.PI / 180));
    txt += '   lat ' + lat.toFixed(4) + '  lon ' + lon.toFixed(4);
  }
  posEl.textContent = txt;
}

function centreView() {
  vpX = cCol * TW + TW/2 - canvas.width/2;
  vpY = cRow * TH + TH/2 - (canvas.height - HUD)/2;
}

async function init() {
  const res = await fetch('/meta.json');
  meta = await res.json();
  gsz  = meta.grid_size;
  cRow = meta.centre_row;
  cCol = meta.centre_col;
  canvas.width  = window.innerWidth;
  canvas.height = window.innerHeight;
  centreView();
  render();
}

window.addEventListener('resize', () => {
  canvas.width  = window.innerWidth;
  canvas.height = window.innerHeight;
  render();
});

canvas.addEventListener('mousedown', e => {
  drag = true; canvas.classList.add('drag');
  dsx = e.clientX; dsy = e.clientY; vpX0 = vpX; vpY0 = vpY;
});
window.addEventListener('mouseup',   () => { drag = false; canvas.classList.remove('drag'); });
window.addEventListener('mousemove', e => {
  if (!drag) return;
  vpX = vpX0 - (e.clientX - dsx);
  vpY = vpY0 - (e.clientY - dsy);
  render();
});

window.addEventListener('keydown', e => {
  const step = (e.shiftKey ? 5 : 1) * TW;
  const moves = { ArrowLeft:[-step,0], ArrowRight:[step,0], ArrowUp:[0,-step], ArrowDown:[0,step] };
  if (moves[e.key]) { e.preventDefault(); vpX += moves[e.key][0]; vpY += moves[e.key][1]; render(); }
  else if (e.key === 'Home') { centreView(); render(); }
});

init();
</script>
</body>
</html>"""

# ── HTTP handler ───────────────────────────────────────────────────────────────
class _Handler(http.server.BaseHTTPRequestHandler):
    tile_dir: Path = None

    def log_message(self, *_): pass  # suppress per-request noise

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ('/', '/index.html'):
            self._send(200, 'text/html; charset=utf-8', _HTML.encode())
        elif path == '/meta.json':
            p = self.tile_dir / 'meta.json'
            self._send(200, 'application/json', p.read_bytes())
        elif path.startswith('/tiles/'):
            name = path[7:]
            p = self.tile_dir / name
            if p.exists() and p.suffix == '.png':
                data = p.read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self.send_header('Cache-Control', 'max-age=86400')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                self.send_error(404)
        else:
            self.send_error(404)

    def _send(self, code, ct, body: bytes):
        self.send_response(code)
        self.send_header('Content-Type', ct)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# ── Entry point ────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument('tile_dir', help='Directory with tile_RR_CC.png + meta.json')
    ap.add_argument('--port', type=int, default=8080, help='Port (default 8080)')
    ap.add_argument('--no-browser', action='store_true',
                    help="Don't auto-open browser (useful when running on VM)")
    args = ap.parse_args()

    tile_dir = Path(args.tile_dir).expanduser().resolve()
    if not tile_dir.exists():
        sys.exit(f'ERROR: {tile_dir} does not exist')
    if not (tile_dir / 'meta.json').exists():
        sys.exit(f'ERROR: no meta.json found in {tile_dir}')

    _Handler.tile_dir = tile_dir
    meta = json.loads((tile_dir / 'meta.json').read_text())
    gsz  = meta.get('grid_size', '?')

    print(f'Tile viewer  →  http://localhost:{args.port}')
    print(f'Tiles:  {tile_dir}')
    print(f'Grid:   {gsz}×{gsz}  ({gsz**2 if isinstance(gsz,int) else "?"} tiles)')
    print('Press Ctrl-C to stop.')

    if not args.no_browser:
        threading.Timer(0.4, webbrowser.open, [f'http://localhost:{args.port}']).start()

    server = http.server.ThreadingHTTPServer(('', args.port), _Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')


if __name__ == '__main__':
    main()
