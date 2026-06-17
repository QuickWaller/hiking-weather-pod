# Pod — Map Tile Pipeline

The pod's e-ink display shows a 2bpp terrain map tile centred on the current GPS position.
Tiles are **pre-generated on the VM** and copied to the SD card — no network access on the pod.

## Display constraint

The 1.54" 4-colour display is **200×200 px**, 2 bits per pixel:
`BLACK(0) WHITE(1) YELLOW(2) RED(3)`.

One tile = one screenful.

## Multi-zoom strategy

Three tile sizes, each as a **regular grid + half-cell-offset copy** (6 tile sets total).
The offset copy ensures a nearby tile is always available regardless of where the hiker
is within the grid — the pod picks whichever grid puts the GPS position closest to a tile centre.

| Tile size | m/px  | Contours                        | Streams              | Tracks      |
|-----------|-------|---------------------------------|----------------------|-------------|
| 2 km      | ~10   | ALL: every 20 m + bold 100 m   | rivers + streams     | foot tracks |
| 4 km      | ~20   | every 40 m flat                 | major rivers only    | foot tracks |
| 10 km     | ~50   | index only (100 m)              | major rivers only    | hidden      |

"ALL" = every 20m line; 100m index lines bold — full detail at 10m/px.
"Every 40 m flat" = equal-weight lines, no bold 100m index lines.
"Index only" = 100 m contours only — prevents solid-black fill in dense alpine terrain.

## Colour mapping

Render order (back to front): yellow ocean fill → coastline (land fill WHITE) → lakes → contours → streams → major rivers → minor roads → sealed roads → state highways → foot tracks → place names → DOC sprites.

| Layer | 2 km | 4 km | 10 km |
|-------|------|------|-------|
| Ocean background | YELLOW | YELLOW | YELLOW |
| Land background | WHITE | WHITE | WHITE |
| Contours minor | BLACK 1px every 20 m | BLACK 1px every 40 m | — |
| Contours index | BLACK 2px every 100 m | — | BLACK 1px every 100 m (flat weight) |
| Streams (1:50k) | YELLOW 2px + BLACK 4px casing | hidden | hidden |
| Major rivers (1:250k) | YELLOW 4px + BLACK 6px casing | YELLOW 4px + BLACK 6px casing | YELLOW 2px + BLACK 4px casing |
| Lakes | YELLOW fill + BLACK outline | YELLOW fill + BLACK outline | YELLOW fill + BLACK outline |
| Minor / metalled / unmetalled road | RED 2px | RED 2px | hidden |
| 2-lane sealed road | RED 2px | RED 2px | RED 2px |
| State highway + motorway | RED 3px + BLACK 5px casing | RED 3px + BLACK 5px casing | RED 2px + BLACK 4px casing |
| Foot tracks | RED 2px | RED 2px | hidden |
| Place names | BLACK text, WHITE box, BLACK dot | BLACK text, WHITE box, BLACK dot | BLACK text, WHITE box (cities/towns only) |
| Peaks | — | — | — |
| Huts | sprite + name label | sprite + name label | sprite (no label) |
| Campsites | sprite + name label | sprite + name label | sprite (no label) |

Huts and campsites within merge distance render as a combined side-by-side sprite.
At 2 km and 4 km, a name label is drawn next to each sprite (suffix "Hut"/"Campsite"/"Camp" stripped). Labels use collision avoidance against place names and other DOC labels — if a label would overlap an existing one, it is dropped (the sprite still renders).

Roads render largest-on-top: minor roads first, then sealed, then highways/motorways last so major roads always appear above smaller ones. All roads draw above rivers; rivers draw above streams.

## Sprite assets — two-pass rendering

Pre-rendered 32-bit RGBA PNGs in `pod/tools/assets/`. Edit in any image editor; save with alpha.

**Sprites:**
- `sprite_HUT.png` — standalone DOC hut
- `sprite_TENT.png` — standalone DOC campsite
- `sprite_combined.png` — hut + campsite at the same location (composited from the above two)

## Two-pass rendering: base + overlay

Tile generation is split into two passes so overlay content (labels, sprites, decorations) can be changed without re-rendering terrain:

- **Base pass** (`--base-only`): LINZ vector terrain only (coastline/land fill, lakes, contours, rivers, roads, tracks) on a yellow ocean background. Slow (~3 hrs for full NZ at 10 km). Outputs `*_base/` directories with `.png` + `meta.json` (no `.bin`).
- **Overlay pass** (`--overlay --base-dir <base>`): loads each base PNG, applies place name labels (clamped to tile boundary), DOC hut/campsite sprites, north arrow, and 500 m scale bar. Fast (~10 min for 22k tiles). Outputs final `.png` + `.bin`.

To update sprites or label styling without re-rendering terrain: edit the PNGs in `assets/` or tweak `render_place_names()`, then re-run the overlay pass only.

### Bleed rendering

Base tiles render to a canvas 10 px larger on each side (220×220), then crop to the final 200×200. This ensures lines crossing tile boundaries connect seamlessly — without bleed, integer rounding in `coord_to_px()` causes 1–2 px jumps at tile edges. The bleed also cleanly removes coastline clip-boundary artifacts (the polygon clip at the expanded edge is outside the crop area).

### Ocean tile detection

The overlay pass detects pure-yellow base tiles (ocean — no terrain features) and stamps them with a single pre-rendered canonical ocean tile (yellow + north arrow + scale bar) instead of running the full overlay pipeline. This skips ~80% of tiles since most of the 151×151 grid is open ocean.

Overlay labels are **clamped per-grid**: the same lat/lon maps to different pixel positions in regular vs offset grids, so each grid's overlay is independent.

## Tool: `map_tile_gen.py`

Location: `pod/tools/map_tile_gen.py`
Requires VM venv: `/home/claude/cyber-deck-and-weather-station/pod-ml/.venv/bin/activate`

```bash
# Base-only render (terrain, no labels/sprites/decorations)
MAP_CONTOURS=INDEX_ONLY MAP_SHOW_STREAMS=0 \
  python map_tile_gen.py --base-only --lat -40.9 --lon 172.5 --radius 750 --tile-km 10 \
    --out ~/tiles/nz_10km_v2_base

# Overlay pass (labels + sprites + north arrow + scale bar)
python map_tile_gen.py --overlay --base-dir ~/tiles/nz_10km_v2_base \
    --out ~/tiles/nz_10km_v2

# Single-pass render (both terrain + overlay in one — for small test grids)
python map_tile_gen.py --lat -39.15 --lon 175.65 --radius 8 --tile-km 4 --preview

# Inspect GeoPackage schema + feature counts for an area
python map_tile_gen.py --inspect --lat -39.15 --lon 175.65

# Synthetic demo — no GeoPackage data needed
python map_tile_gen.py --demo --preview
```

### Environment / config knobs

All overridable via env var or `.env` at repo root:

| Var | Default | Options |
|-----|---------|---------|
| `MAP_CONTOURS` | `EVERY_40` | `ALL` / `EVERY_40` / `INDEX_ONLY` |
| `MAP_SHOW_STREAMS` | `1` | `0` to hide 1:50k river layer |
| `MAP_CONTOUR_MINOR_WIDTH` | `1` | px |
| `MAP_CONTOUR_MAJOR_WIDTH` | `2` | px (only used in ALL mode) |
| `MAP_RIVER_WIDTH` | `2` | px (major rivers) |
| `MAP_ROAD_WIDTH` | `2` | px |
| `MAP_TRACK_WIDTH` | `2` | px |
| `MAP_HUT_SIZE` / `MAP_CAMP_SIZE` | `5` | sprite half-size px |

### Contour modes

| Mode | What renders |
|------|-------------|
| `ALL` | Every 20m line; 100m lines bold (`MAJOR_WIDTH`) — used at 2 km |
| `EVERY_40` | Every 40m line; all at equal weight (no bold index) — used at 4 km |
| `INDEX_ONLY` | 100m lines only, **flat weight** (same as minor width) — used at 10 km |

`INDEX_ONLY` is intentionally flat: bold 100m lines over-ink sparse alpine tiles at 10 km scale.

## LINZ vector data

Downloaded as GeoPackage to `~/linz-data/` on the VM by `pod-ml/scripts/linz/linz_pull.py`.
Renderer queries features via `fiona.filter(bbox=bbox)` — no network at generate time.

| Layer | LINZ ID | Notes |
|-------|---------|-------|
| contours | 50768 | 20m interval; `elevation` field |
| tracks | 50364 | DOC + Topo50 tracks |
| roads | 50329 | all road classes |
| lakes | 50293 | polygon fill |
| rivers | 50327 | 1:50k, all lines — no subtype field |
| rivers_major | 50182 | 1:250k, significant rivers only |
| coastline | 51153 | polygon — filled WHITE (land) on yellow ocean background |
| peaks | 50284 | downloaded, **not rendered** |
| glaciers | 50287 | downloaded, **not rendered** |
| cliffs   | 50233 | downloaded, **not rendered** |
| place_names | 51681 | NZ Gazetteer — towns, summits, lakes, bays etc. |

**Note:** LINZ rivers layers have no stream/river classification field — `rivers_major` (1:250k)
serves as a proxy for significant rivers, `rivers` (1:50k) for all waterways.

Place names are filtered by `feat_type` and `label_hierarchy` per zoom: 10 km shows only cities/towns/places (hierarchy ≤ 9); 4 km adds passes/ranges/lakes/suburbs; 2 km adds hills/valleys/glaciers/forests etc. Labels are sorted by hierarchy (most important first) and placed with collision avoidance — if a label would overlap a previously placed one, it is dropped.

## LINZ weekly update

A cron job on the VM refreshes all GeoPackage source files weekly. After an update, tiles
covering changed areas should be re-rendered (base pass + overlay pass). Cron is managed
via `pod-ml/scripts/linz/` — see `linz_pull.py` for the download script.

## Full-NZ generation

Render one zoom at a time, regular grid only first. Offset grids can be added later as a second pass — they share the same code but different `--lat/--lon` centre to shift tile boundaries by half a cell.

| Grid | Tiles | Est. size | Status |
|------|-------|-----------|--------|
| 10 km regular base | 22,801 | 228 MB | **done** |
| 10 km regular overlay | 22,801 | 228 MB | **done** |
| 10 km offset base  | 22,801 | 228 MB | pending |
| 10 km offset overlay | 22,801 | 228 MB | pending |
| 4 km regular base | 142,129 | ~1.4 GB | **rendering** |
| 4 km regular overlay | 142,129 | ~1.4 GB | pending (after base) |
| 4 km offset base  | 142,129 | ~1.4 GB | pending |
| 4 km offset overlay | 142,129 | ~1.4 GB | pending |
| 2 km regular  | ~142,129 | ~1.4 GB | pending |
| 2 km offset   | ~142,129 | ~1.4 GB | pending |

All tile sets fit on a 16 GB SD card alongside model files and logs.

### Render commands (VM)

All grids share the same centre (-40.9, 172.5) and 750 km radius. The env vars control styling per zoom level.

```bash
source ~/cyber-deck-and-weather-station/pod-ml/.venv/bin/activate
cd ~/cyber-deck-and-weather-station/pod/tools

# ── 10 km ────────────────────────────────────────────────────────────────────
# Pass 1: base (terrain only) — ~2.5 hrs each
MAP_CONTOURS=INDEX_ONLY MAP_SHOW_STREAMS=0 \
  python map_tile_gen.py --base-only \
    --lat -40.9 --lon 172.5 --tile-km 10 --radius 750 \
    --out ~/tiles/nz_10km_v2_base \
  > ~/tiles/nz_10km_v2_base.log 2>&1 &

# Offset grid (+5 km in lat and lon)
MAP_CONTOURS=INDEX_ONLY MAP_SHOW_STREAMS=0 \
  python map_tile_gen.py --base-only \
    --lat -40.855 --lon 172.560 --tile-km 10 --radius 750 \
    --out ~/tiles/nz_10km_v2_offset_base \
  > ~/tiles/nz_10km_v2_offset_base.log 2>&1 &

# Pass 2: overlay (labels + sprites + decorations) — ~10 min each
python map_tile_gen.py --overlay \
  --base-dir ~/tiles/nz_10km_v2_base --out ~/tiles/nz_10km_v2 \
  > ~/tiles/nz_10km_v2_overlay.log 2>&1 &

python map_tile_gen.py --overlay \
  --base-dir ~/tiles/nz_10km_v2_offset_base --out ~/tiles/nz_10km_v2_offset \
  > ~/tiles/nz_10km_v2_offset_overlay.log 2>&1 &

# ── 4 km ─────────────────────────────────────────────────────────────────────
# Base — every-40m contours, no 1:50k streams, foot tracks visible
MAP_CONTOURS=EVERY_40 MAP_SHOW_STREAMS=0 \
  python map_tile_gen.py --base-only \
    --lat -40.9 --lon 172.5 --tile-km 4 --radius 750 \
    --out ~/tiles/nz_4km_v2_base \
  > ~/tiles/nz_4km_v2_base.log 2>&1 &

MAP_CONTOURS=EVERY_40 MAP_SHOW_STREAMS=0 \
  python map_tile_gen.py --base-only \
    --lat -40.855 --lon 172.530 --tile-km 4 --radius 750 \
    --out ~/tiles/nz_4km_v2_offset_base \
  > ~/tiles/nz_4km_v2_offset_base.log 2>&1 &

# Overlay — includes hut/campsite name labels at 4 km
python map_tile_gen.py --overlay \
  --base-dir ~/tiles/nz_4km_v2_base --out ~/tiles/nz_4km_v2 \
  > ~/tiles/nz_4km_v2_overlay.log 2>&1 &

python map_tile_gen.py --overlay \
  --base-dir ~/tiles/nz_4km_v2_offset_base --out ~/tiles/nz_4km_v2_offset \
  > ~/tiles/nz_4km_v2_offset_overlay.log 2>&1 &

# ── 2 km ─────────────────────────────────────────────────────────────────────
# Base — all contours (20m + bold 100m), 1:50k streams, foot tracks
MAP_CONTOURS=ALL MAP_SHOW_STREAMS=1 \
  python map_tile_gen.py --base-only \
    --lat -40.9 --lon 172.5 --tile-km 2 --radius 750 \
    --out ~/tiles/nz_2km_v2_base \
  > ~/tiles/nz_2km_v2_base.log 2>&1 &

MAP_CONTOURS=ALL MAP_SHOW_STREAMS=1 \
  python map_tile_gen.py --base-only \
    --lat -40.855 --lon 172.515 --tile-km 2 --radius 750 \
    --out ~/tiles/nz_2km_v2_offset_base \
  > ~/tiles/nz_2km_v2_offset_base.log 2>&1 &

# Overlay — includes hut/campsite name labels at 2 km
python map_tile_gen.py --overlay \
  --base-dir ~/tiles/nz_2km_v2_base --out ~/tiles/nz_2km_v2 \
  > ~/tiles/nz_2km_v2_overlay.log 2>&1 &

python map_tile_gen.py --overlay \
  --base-dir ~/tiles/nz_2km_v2_offset_base --out ~/tiles/nz_2km_v2_offset \
  > ~/tiles/nz_2km_v2_offset_overlay.log 2>&1 &
```

## Tile viewer

Tiles are browsable via the pod-ml ops dashboard canvas viewer.

The dashboard server (`pod-ml/scripts/dashboard_server.py`) serves an interactive map at `/map`.
It uses `ThreadingHTTPServer` so tile requests load in parallel.
`meta.json` is served slim (scalars only — no per-tile array) for fast initial load.

```
http://192.168.2.156:8000/map
```

Controls: **drag** to pan · **arrow keys** to move (Shift = ×5 tiles) · **Home** = return to centre.
Grid selector in the top bar switches between available rendered grids.

## SD card layout

```
/maps/
  2km_regular/   meta.json  tile_RR_CC.bin …   (10,000 bytes each — 200×200 2bpp MSB-first)
  2km_offset/    meta.json  tile_RR_CC.bin …
  4km_regular/   meta.json  tile_RR_CC.bin …
  4km_offset/    meta.json  tile_RR_CC.bin …
  10km_regular/  meta.json  tile_RR_CC.bin …
  10km_offset/   meta.json  tile_RR_CC.bin …
```

The pod reads `meta.json` at boot to build a GPS→tile index, then streams individual `.bin`
files as the hiker moves. Zoom selection: 2 km preferred when available, 4 km as fallback,
10 km for wide-area context.
