# Currently Working On

Active tasks and in-flight work. Check at session start — confirm with user what's still live vs dropped.

## Map tile pipeline — 4km render

**Status:** 4km base render running on VM (PID unknown — check `ps aux | grep map_tile_gen`)
**Started:** 2026-06-18
**Grid:** 377×377 = 142,129 tiles. `MAP_CONTOURS=EVERY_40 MAP_SHOW_STREAMS=0`
**Output:** `~/tiles/nz_4km_v2_base/` on claude-vm
**Progress log:** `~/tiles/nz_4km_v2_base.log` — check with `grep '\[' ~/tiles/nz_4km_v2_base.log | tail -1`

**When base finishes, run overlay:**
```bash
source ~/cyber-deck-and-weather-station/pod-ml/.venv/bin/activate
cd ~/cyber-deck-and-weather-station/pod/tools
python map_tile_gen.py --overlay --base-dir ~/tiles/nz_4km_v2_base --out ~/tiles/nz_4km_v2 \
  > ~/tiles/nz_4km_v2_overlay.log 2>&1 &
```

**After overlay:** check a land tile on the dashboard (http://192.168.2.156:8000/map, select `nz_4km_v2`). Verify hut/campsite name labels render at 4km. Then decide on 2km render.

## Pending (not started)

- 10km offset grid (base + overlay) — same code, `--lat -40.855 --lon 172.560`
- 4km offset grid — same code, `--lat -40.855 --lon 172.530`
- 2km render — `MAP_CONTOURS=ALL MAP_SHOW_STREAMS=1`, not started yet
