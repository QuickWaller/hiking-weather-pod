#!/usr/bin/env python3
"""
map_tile_gen.py  —  Generate e-ink map tiles for pod SD card.

Reads LINZ NZ Topo50 GeoPackage files from ~/linz-data/ (downloaded by
pod-ml/scripts/linz/linz_pull.py) and renders 200×200 4-colour tiles for
the Waveshare 1.54" e-Paper (G) display.

Tiles are centred on any GPS coordinate (no WebMercator grid alignment).

Outputs per tile:
  <out>/tile_RR_CC.png   - preview PNG
  <out>/tile_RR_CC.bin   - 2bpp binary for pod (4px/byte, MSB-first)
  <out>/meta.json        - grid params for pod C++ GPS lookup

Usage:
  pip install fiona shapely pyproj pillow requests

  # Generate 3×3 tile grid centred on Tongariro crossing trailhead:
  python map_tile_gen.py --lat -39.15 --lon 175.65 --radius 4 --preview

  # Inspect available GeoPackage layers:
  python map_tile_gen.py --inspect --lat -39.15 --lon 175.65

  # Synthetic demo (no GeoPackage data needed):
  python map_tile_gen.py --demo --preview

GeoPackage data: set LINZ_BASE_DIR in .env or env var (default: ~/linz-data)
DOC huts/campsites: set DOC_API in .env — run --fetch-doc to cache them locally
"""

import argparse, json, math, os, sys
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

try:
    import fiona
    HAS_FIONA = True
except ImportError:
    HAS_FIONA = False

try:
    from shapely.geometry import box as _shp_box, shape as _shp_shape
    HAS_SHAPELY = True
except ImportError:
    HAS_SHAPELY = False

try:
    from pyproj import Transformer as _Transformer
    _nztm_to_wgs84 = _Transformer.from_crs("EPSG:2193", "EPSG:4326", always_xy=True)
    HAS_PYPROJ = True
except ImportError:
    HAS_PYPROJ = False

# ── .env ──────────────────────────────────────────────────────────────────────
def _load_env():
    env_path = Path(__file__).parent.parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())
_load_env()

# ── Display ───────────────────────────────────────────────────────────────────
W, H = 200, 200
BLEED = 10  # extra pixels per side for seamless tile edges

# ── GeoPackage data location ──────────────────────────────────────────────────
LINZ_BASE_DIR = os.environ.get("LINZ_BASE_DIR", os.path.expanduser("~/linz-data"))

# Mapping from logical name → (sub-dir, filename) under LINZ_BASE_DIR
LAYER_GPKG: dict[str, tuple[str, str]] = {
    "contours":     ("contours",     "nz-contours.gpkg"),
    "tracks":       ("tracks",       "nz-track-centrelines.gpkg"),
    "roads":        ("roads",        "nz-road-centrelines.gpkg"),
    "lakes":        ("lakes",        "nz-lake-polygons.gpkg"),
    "rivers":       ("rivers",       "nz-river-centrelines.gpkg"),
    "rivers_major": ("rivers_major", "nz-river-centrelines-250k.gpkg"),
    "coastline":    ("coastline",    "nz-coastlines-and-islands.gpkg"),
    "peaks":        ("peaks",        "nz-height-points.gpkg"),
    "glaciers":     ("glaciers",     "nz-ice-polygons.gpkg"),
    "place_names":  ("place_names",  "nz-place-names.gpkg"),
}

def _gpkg_path(layer: str) -> Path:
    subdir, fname = LAYER_GPKG[layer]
    return Path(LINZ_BASE_DIR) / subdir / fname

# ── Colours ───────────────────────────────────────────────────────────────────
BLACK  = (0,   0,   0)
WHITE  = (255, 255, 255)
YELLOW = (255, 255, 0)
RED    = (255, 0,   0)
PALETTE_CODES = {BLACK: 0x0, WHITE: 0x1, YELLOW: 0x2, RED: 0x3}
_COLOUR_MAP = {"BLACK": BLACK, "WHITE": WHITE, "YELLOW": YELLOW, "RED": RED}

# ── Tweakable options (from .env) ─────────────────────────────────────────────
def _eint(key, default):
    try: return int(os.environ.get(key, default))
    except (ValueError, TypeError): return default

def _ecol(key, default):
    return _COLOUR_MAP.get(os.environ.get(key, "").upper(), default)

def _estr(key, default):
    return os.environ.get(key, default).upper()

CFG_CONTOURS        = _estr("MAP_CONTOURS",           "EVERY_40")  # INDEX_ONLY | EVERY_40 | ALL
CFG_CONTOUR_MINOR_W = _eint("MAP_CONTOUR_MINOR_WIDTH", 1)
CFG_CONTOUR_MAJOR_W = _eint("MAP_CONTOUR_MAJOR_WIDTH", 2)
CFG_RIVER_COLOUR    = _ecol("MAP_RIVER_COLOUR",        YELLOW)
CFG_RIVER_WIDTH     = _eint("MAP_RIVER_WIDTH",         2)
CFG_LAKE_COLOUR     = _ecol("MAP_LAKE_COLOUR",         YELLOW)
CFG_ROAD_COLOUR     = _ecol("MAP_ROAD_COLOUR",         BLACK)
CFG_ROAD_WIDTH      = _eint("MAP_ROAD_WIDTH",          1)
CFG_HWY_COLOUR      = _ecol("MAP_HWY_COLOUR",          RED)
CFG_HWY_WIDTH       = _eint("MAP_HWY_WIDTH",           3)
CFG_TRACK_COLOUR    = _ecol("MAP_TRACK_COLOUR",        RED)
CFG_TRACK_WIDTH     = _eint("MAP_TRACK_WIDTH",         2)
CFG_PEAK_RADIUS     = _eint("MAP_PEAK_RADIUS",         3)
CFG_SHOW_STREAMS    = os.environ.get("MAP_SHOW_STREAMS", "1") != "0"
CFG_HUT_SHAPE       = _estr("MAP_HUT_SHAPE",           "HOUSE")   # HOUSE | CROSS | SQUARE | CIRCLE
CFG_HUT_COLOUR      = _ecol("MAP_HUT_COLOUR",          RED)
CFG_HUT_SIZE        = _eint("MAP_HUT_SIZE",            5)
CFG_CAMP_SHAPE      = _estr("MAP_CAMP_SHAPE",          "TENT")    # TENT | TRIANGLE | CIRCLE
CFG_CAMP_COLOUR     = _ecol("MAP_CAMP_COLOUR",         RED)
CFG_CAMP_SIZE       = _eint("MAP_CAMP_SIZE",           5)

# ── Road classification ───────────────────────────────────────────────────────
def _road_tier(props: dict) -> str:
    hway  = props.get("hway_num")
    lanes = props.get("lane_count") or 0
    surf  = props.get("surface") or ""
    if lanes >= 4:                      return "motorway"
    if hway:                            return "state_highway"
    if surf == "sealed" and lanes >= 2: return "sealed_road"
    if surf == "sealed":                return "sealed_minor"
    if surf == "metalled":              return "metalled"
    return "unmetalled"

def _draw_dashed(draw, pts, fill, width, dash=6, gap=3):
    for i in range(len(pts) - 1):
        x0, y0 = pts[i]; x1, y1 = pts[i + 1]
        length = math.hypot(x1 - x0, y1 - y0)
        if length < 1:
            continue
        t = 0.0
        while t < length:
            t1 = min(t + dash, length)
            f, e = t / length, t1 / length
            p0 = (int(x0 + f*(x1-x0)), int(y0 + f*(y1-y0)))
            p1 = (int(x0 + e*(x1-x0)), int(y0 + e*(y1-y0)))
            if p0 != p1:
                draw.line([p0, p1], fill=fill, width=width)
            t += dash + gap

# ── Geography helpers ─────────────────────────────────────────────────────────
def make_bbox(centre_lat: float, centre_lon: float, half_km: float,
              ref_lat: float = None) -> tuple:
    """Compute (west, south, east, north) WGS84 for a square tile of side 2*half_km.
    ref_lat: use this latitude for longitude scaling (grid consistency across rows)."""
    dlat = half_km / 111.0
    cos_lat = math.cos(math.radians(ref_lat if ref_lat is not None else centre_lat))
    dlon = half_km / (111.0 * cos_lat)
    return (centre_lon - dlon, centre_lat - dlat,
            centre_lon + dlon, centre_lat + dlat)

def bbox_km_width(bbox: tuple) -> float:
    west, south, east, north = bbox
    lat_c = (south + north) / 2
    return math.pi * 6371 * math.cos(math.radians(lat_c)) * (east - west) / 180

def coord_to_px(coord, bbox: tuple, w=None, h=None) -> tuple[int, int]:
    """WGS84 (lon, lat[, z]) coordinate → (px, py). Allows off-screen values for PIL lines."""
    if w is None: w = W
    if h is None: h = H
    lon, lat = coord[0], coord[1]
    west, south, east, north = bbox
    px = int((lon - west) / (east - west) * w)
    py = int((north - lat) / (north - south) * h)
    return px, py

def clamp_px(px: int, py: int) -> tuple[int, int]:
    return max(0, min(W - 1, px)), max(0, min(H - 1, py))

# ── GeoJSON geometry helpers ──────────────────────────────────────────────────
def geom_linestrings(geom):
    """Yield [[lon,lat],...] lists for each line component."""
    t, c = geom["type"], geom["coordinates"]
    if t == "LineString":
        yield c
    elif t == "MultiLineString":
        yield from c
    elif t == "Polygon":
        yield c[0]
    elif t == "MultiPolygon":
        for poly in c:
            yield poly[0]

def geom_rings(geom):
    """Yield all rings (including holes) for polygon rendering."""
    t, c = geom["type"], geom["coordinates"]
    if t == "Polygon":
        yield from c
    elif t == "MultiPolygon":
        for poly in c:
            yield from poly

def geom_centroid(geom):
    """Approximate (lon, lat) centre of any geometry, or None."""
    t, c = geom["type"], geom["coordinates"]
    if t == "Point":
        return c[0], c[1]
    if t == "LineString" and c:
        m = c[len(c) // 2]
        return m[0], m[1]
    if t in ("Polygon", "MultiPolygon"):
        outer = c[0] if t == "Polygon" else c[0][0]
        if outer:
            xs = [p[0] for p in outer]
            ys = [p[1] for p in outer]
            return sum(xs) / len(xs), sum(ys) / len(ys)
    return None

# ── GeoPackage query + polygon clip ──────────────────────────────────────────
def _clip_polygon_rings(feat_geom, tile_box):
    """Clip a polygon geometry to the tile bbox using shapely.
    Returns list of coord lists (exterior rings of clipped polygons), or None on failure.
    """
    if not HAS_SHAPELY or tile_box is None:
        return None
    try:
        clipped = _shp_shape(feat_geom).intersection(tile_box)
        if clipped.is_empty:
            return []
        if clipped.geom_type == "Polygon":
            return [list(clipped.exterior.coords)]
        if clipped.geom_type == "MultiPolygon":
            return [list(g.exterior.coords) for g in clipped.geoms]
        return []
    except Exception:
        return None

def open_sources() -> dict:
    """Open all available GeoPackage sources. Caller must close() each."""
    if not HAS_FIONA:
        print("WARNING: fiona not installed — pip install fiona")
        return {}
    sources = {}
    for name in LAYER_GPKG:
        p = _gpkg_path(name)
        if p.exists():
            sources[name] = fiona.open(str(p))
        else:
            print(f"  WARNING: {p} not found — layer '{name}' skipped")
    return sources

# ── Render from GeoPackage sources ────────────────────────────────────────────
def render_tile_gpkg(sources: dict, bbox: tuple, draw, img, tile_km: float = 2.0,
                     canvas_w=None, canvas_h=None) -> dict:
    """Render all GeoPackage layers onto draw. Returns feature counts per layer."""
    west, south, east, north = bbox
    tile_box = _shp_box(west, south, east, north) if HAS_SHAPELY else None
    _cw = canvas_w or W
    _ch = canvas_h or H

    def px(coord):
        return coord_to_px(coord, bbox, _cw, _ch)

    stats = {}

    # Coastline — fill land WHITE on yellow ocean, then outline
    src = sources.get("coastline")
    if src:
        count = 0
        for feat in src.filter(bbox=bbox):
            geom = feat.get("geometry")
            if not geom:
                continue
            rings = _clip_polygon_rings(geom, tile_box)
            if rings is None:
                rings = list(geom_rings(geom))
            for ring in rings:
                pts = [px(c) for c in ring]
                if len(pts) >= 3:
                    draw.polygon(pts, fill=WHITE)
            # Draw actual coastline using unclipped geometry (bleed crop removes clip-edge artifacts)
            for ring in geom_rings(geom):
                pts = [px(c) for c in ring]
                if len(pts) >= 2:
                    draw.line(pts + [pts[0]], fill=BLACK, width=1)
            count += 1
        if count:
            stats["coastline"] = count

    # Lakes — YELLOW fill
    src = sources.get("lakes")
    if src:
        count = 0
        for feat in src.filter(bbox=bbox):
            geom = feat.get("geometry")
            if not geom:
                continue
            rings = _clip_polygon_rings(geom, tile_box)
            if rings is None:
                rings = list(geom_rings(geom))
            for ring in rings:
                pts = [px(c) for c in ring]
                if len(pts) >= 3:
                    draw.polygon(pts, fill=CFG_LAKE_COLOUR, outline=BLACK)
            count += 1
        if count:
            stats["lakes"] = count

    # Contours — drawn first so rivers/roads render on top
    src = sources.get("contours")
    if src:
        minor_feats, major_feats = [], []
        for feat in src.filter(bbox=bbox):
            geom = feat.get("geometry")
            if not geom:
                continue
            elev = (feat.get("properties") or {}).get("elevation")
            try:
                elev_int = int(elev)
            except (TypeError, ValueError):
                elev_int = None

            if CFG_CONTOURS == "INDEX_ONLY":
                if elev_int is not None and elev_int % 100 == 0:
                    minor_feats.append(feat)  # flat weight at 10km — no bold
            elif CFG_CONTOURS == "EVERY_40":
                if elev_int is not None and elev_int % 40 == 0:
                    minor_feats.append(feat)
            else:  # ALL
                is_major = elev_int is not None and elev_int % 100 == 0
                if is_major:
                    major_feats.append(feat)
                else:
                    minor_feats.append(feat)
        for feat in minor_feats:
            for seg in geom_linestrings(feat["geometry"]):
                pts = [px(c) for c in seg]
                if len(pts) >= 2:
                    draw.line(pts, fill=BLACK, width=CFG_CONTOUR_MINOR_W)
        for feat in major_feats:
            for seg in geom_linestrings(feat["geometry"]):
                pts = [px(c) for c in seg]
                if len(pts) >= 2:
                    draw.line(pts, fill=BLACK, width=CFG_CONTOUR_MAJOR_W)
        total = len(minor_feats) + len(major_feats)
        if total:
            stats["contours"] = total

    # Streams (1:50k) — rendered after contours
    has_major = "rivers_major" in sources
    src = sources.get("rivers")
    if src and CFG_SHOW_STREAMS:
        count = 0
        for feat in src.filter(bbox=bbox):
            geom = feat.get("geometry")
            if not geom:
                continue
            for seg in geom_linestrings(geom):
                pts = [px(c) for c in seg]
                if len(pts) >= 2:
                    if tile_km <= 2:
                        # 2km: 2px yellow with 4px black casing
                        draw.line(pts, fill=BLACK, width=4)
                        draw.line(pts, fill=CFG_RIVER_COLOUR, width=2)
                    elif has_major:
                        draw.line(pts, fill=BLACK, width=3)
                        draw.line(pts, fill=CFG_RIVER_COLOUR, width=1)
                    else:
                        draw.line(pts, fill=BLACK, width=CFG_RIVER_WIDTH + 2)
                        draw.line(pts, fill=CFG_RIVER_COLOUR, width=CFG_RIVER_WIDTH)
            count += 1
        if count:
            stats["streams" if has_major else "rivers"] = count

    # Major rivers (1:250k) — thinner at 10km
    src = sources.get("rivers_major")
    if src:
        count = 0
        for feat in src.filter(bbox=bbox):
            geom = feat.get("geometry")
            if not geom:
                continue
            for seg in geom_linestrings(geom):
                pts = [px(c) for c in seg]
                if len(pts) >= 2:
                    if tile_km >= 8:
                        draw.line(pts, fill=BLACK, width=4)
                        draw.line(pts, fill=CFG_RIVER_COLOUR, width=2)
                    else:
                        draw.line(pts, fill=BLACK, width=CFG_RIVER_WIDTH + 4)
                        draw.line(pts, fill=CFG_RIVER_COLOUR, width=CFG_RIVER_WIDTH + 2)
            count += 1
        if count:
            stats["rivers_major"] = count

    # Roads — tiered rendering by scale
    src = sources.get("roads")
    if src:
        tiers: dict[str, list] = {t: [] for t in
            ("motorway","state_highway","sealed_road","sealed_minor","metalled","unmetalled")}
        for feat in src.filter(bbox=bbox):
            if feat.get("geometry"):
                tiers[_road_tier(feat.get("properties") or {})].append(feat)

        large = tile_km >= 8  # 10km style

        def _road_segs(feat_list):
            for feat in feat_list:
                for seg in geom_linestrings(feat["geometry"]):
                    pts = [px(c) for c in seg]
                    if len(pts) >= 2:
                        yield pts

        # Render order: smallest roads first, largest last (so major roads sit on top)
        if large:
            # 10km: 2-lane sealed RED 2px; single-lane/metalled/unmetalled hidden
            for pts in _road_segs(tiers["sealed_road"]):
                draw.line(pts, fill=RED, width=2)
        else:
            # 2km/4km: minor roads first, then sealed on top
            for pts in _road_segs(tiers["unmetalled"] + tiers["metalled"] + tiers["sealed_minor"]):
                draw.line(pts, fill=RED, width=2)
            for pts in _road_segs(tiers["sealed_road"]):
                draw.line(pts, fill=RED, width=2)

        # State highways + motorways last — on top of all roads
        hw_w = 3 if not large else 2
        for pts in _road_segs(tiers["state_highway"] + tiers["motorway"]):
            draw.line(pts, fill=BLACK, width=hw_w + 2)
            draw.line(pts, fill=RED,   width=hw_w)

        total = sum(len(v) for v in tiers.values())
        if total:
            stats["roads"] = total
            stats["highways"] = len(tiers["motorway"]) + len(tiers["state_highway"])

    # Tracks — foot tracks RED thin, no casing; hidden at 10km
    src = sources.get("tracks")
    if src and tile_km < 8:
        count = 0
        for feat in src.filter(bbox=bbox):
            geom = feat.get("geometry")
            if not geom:
                continue
            use = (feat.get("properties") or {}).get("track_use")
            if use != "foot":
                continue
            for seg in geom_linestrings(geom):
                pts = [px(c) for c in seg]
                if len(pts) >= 2:
                    draw.line(pts, fill=CFG_TRACK_COLOUR, width=2)
            count += 1
        if count:
            stats["foot_tracks"] = count

    return stats


def render_place_names(sources, bbox, draw, tile_km):
    """Render place name labels, clamped so text stays within tile boundaries."""
    src = sources.get("place_names")
    if not src:
        return {}

    try:
        font = ImageFont.load_default(size=10)
    except TypeError:
        font = ImageFont.load_default()

    if tile_km >= 8:
        show_types = {"Town", "City", "Place"}
        max_hier = 9
    elif tile_km >= 4:
        show_types = {"Town", "City", "Place", "Pass", "Range", "Lake", "Suburb"}
        max_hier = 11
    else:
        show_types = {"Town", "City", "Place", "Pass", "Range", "Lake", "Suburb",
                      "Hill", "Valley", "Glacier", "Forest", "Scenic Reserve", "Historic Site"}
        max_hier = 13

    # Collect candidates and sort by hierarchy (lower = more important)
    candidates = []
    for feat in src.filter(bbox=bbox):
        props = feat.get("properties") or {}
        ft    = props.get("feat_type") or ""
        hier  = props.get("label_hierarchy")
        hier_ok = hier is not None and int(hier) <= max_hier
        if ft not in show_types and not hier_ok:
            continue
        name = (props.get("name") or "").strip()
        if not name:
            continue
        lat = props.get("crd_latitude")
        lon = props.get("crd_longitude")
        if lat is None or lon is None:
            continue
        p_x, p_y = coord_to_px((lon, lat), bbox)
        if 0 <= p_x < W and 0 <= p_y < H:
            h = int(hier) if hier is not None else 99
            candidates.append((h, name, p_x, p_y))

    candidates.sort(key=lambda c: c[0])

    def boxes_overlap(a, b):
        return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]

    placed = []
    count = 0
    for _hier, name, p_x, p_y in candidates:
        tx, ty = p_x + 4, p_y - 4
        tb = draw.textbbox((tx, ty), name, font=font)
        # Clamp label so text + padding stays within tile
        if tb[2] + 1 > W:
            tx -= (tb[2] + 1 - W)
        if tb[3] + 1 > H:
            ty -= (tb[3] + 1 - H)
        if tb[0] - 1 < 0:
            tx += (1 - tb[0])
        if tb[1] - 1 < 0:
            ty += (1 - tb[1])
        tb = draw.textbbox((tx, ty), name, font=font)
        padded = (tb[0]-2, tb[1]-2, tb[2]+2, tb[3]+2)
        if any(boxes_overlap(padded, p) for p in placed):
            continue
        placed.append(padded)
        draw.rectangle([tb[0]-1, tb[1]-1, tb[2]+1, tb[3]+1], fill=WHITE)
        draw.ellipse([p_x - 2, p_y - 2, p_x + 2, p_y + 2], fill=BLACK)
        draw.text((tx, ty), name, fill=BLACK, font=font)
        count += 1

    stats = {"place_names": count} if count else {}
    return stats, placed

# ── POI sprites ───────────────────────────────────────────────────────────────
def _draw_sprite(draw, px, py, shape, size, colour, border=False):
    s = size
    bw = max(1, s // 3)
    if shape == "HOUSE":
        roof_y = py - s // 3
        pts = [(px, py-s), (px+s, roof_y), (px+s, py+s//2),
               (px-s, py+s//2), (px-s, roof_y)]
        if border:
            draw.line(pts + [pts[0]], fill=BLACK, width=bw * 2 + 1)
        draw.polygon(pts, fill=colour)
        dw = max(1, s//3)
        draw.rectangle([px-dw, py+s//2-max(1, s//3), px+dw, py+s//2], fill=WHITE)
    elif shape == "TENT":
        pts = [(px, py-s), (px-s, py+s), (px+s, py+s)]
        if border:
            draw.line(pts + [pts[0]], fill=BLACK, width=bw * 2 + 1)
        draw.polygon(pts, fill=colour)
    elif shape == "CIRCLE":
        if border:
            draw.ellipse([px-s-bw, py-s-bw, px+s+bw, py+s+bw], fill=BLACK)
        draw.ellipse([px-s, py-s, px+s, py+s], fill=colour)
    elif shape == "SQUARE":
        if border:
            draw.rectangle([px-s-bw, py-s-bw, px+s+bw, py+s+bw], fill=BLACK)
        draw.rectangle([px-s, py-s, px+s, py+s], fill=colour)
    elif shape == "CROSS":
        t = max(1, s // 2)
        if border:
            draw.rectangle([px-s-bw, py-t-bw, px+s+bw, py+t+bw], fill=BLACK)
            draw.rectangle([px-t-bw, py-s-bw, px+t+bw, py+s+bw], fill=BLACK)
        draw.rectangle([px-s, py-t, px+s, py+t], fill=colour)
        draw.rectangle([px-t, py-s, px+t, py+s], fill=colour)
    elif shape == "TRIANGLE":
        pts = [(px, py-s), (px-s, py+s), (px+s, py+s)]
        if border:
            draw.line(pts + [pts[0]], fill=BLACK, width=bw * 2 + 1)
        draw.polygon(pts, fill=colour)
    else:
        if border:
            draw.ellipse([px-s-bw, py-s-bw, px+s+bw, py+s+bw], fill=BLACK)
        draw.ellipse([px-s, py-s, px+s, py+s], fill=colour)

# ── Pre-rendered sprite images (RGBA, cached) ─────────────────────────────────
ASSETS_DIR = Path(__file__).parent / "assets"
_SPRITE_CACHE: dict = {}

def _render_sprite_img(shape, size, colour):
    pad = max(2, size // 3)
    dim = size * 2 + pad * 2 + 1
    img = Image.new("RGBA", (dim, dim), (255, 255, 255, 0))
    d   = ImageDraw.Draw(img)
    c   = dim // 2
    _draw_sprite(d, c, c, shape, size, colour, border=True)
    return img

def _render_combined_img(size, colour):
    pad  = max(2, size // 3)
    gap  = size + pad
    half = size + pad
    w    = gap * 2 + half * 2 + 1
    h    = size * 2 + pad * 2 + 1
    img  = Image.new("RGBA", (w, h), (255, 255, 255, 0))
    d    = ImageDraw.Draw(img)
    cy   = h // 2
    cx   = w // 2
    _draw_sprite(d, cx - gap, cy, "HOUSE", size, colour, border=True)
    _draw_sprite(d, cx + gap, cy, "TENT",  size, colour, border=True)
    return img

_SPRITE_FILES = {
    "HOUSE": "sprite_HUT.png",
    "TENT":  "sprite_TENT.png",
}

def _sprite_img(shape, size, colour):
    key = (shape, size, colour)
    if key in _SPRITE_CACHE:
        return _SPRITE_CACHE[key]
    path = ASSETS_DIR / _SPRITE_FILES.get(shape, f"sprite_{shape}.png")
    img = Image.open(path).convert("RGBA") if path.exists() else _render_sprite_img(shape, size, colour)
    _SPRITE_CACHE[key] = img
    return img

def _combined_sprite_img(size, colour):
    key = ("combined", size, colour)
    if key in _SPRITE_CACHE:
        return _SPRITE_CACHE[key]
    path = ASSETS_DIR / "sprite_combined.png"
    if path.exists():
        img = Image.open(path).convert("RGBA")
    else:
        hut_spr  = _sprite_img(CFG_HUT_SHAPE,  CFG_HUT_SIZE,  CFG_HUT_COLOUR)
        camp_spr = _sprite_img(CFG_CAMP_SHAPE, CFG_CAMP_SIZE, CFG_CAMP_COLOUR)
        gap = 3
        w   = hut_spr.width + gap + camp_spr.width
        h   = max(hut_spr.height, camp_spr.height)
        img = Image.new("RGBA", (w, h), (255, 255, 255, 0))
        img.paste(hut_spr,  (0, (h - hut_spr.height)  // 2), mask=hut_spr)
        img.paste(camp_spr, (hut_spr.width + gap, (h - camp_spr.height) // 2), mask=camp_spr)
    _SPRITE_CACHE[key] = img
    return img

def save_sprites():
    ASSETS_DIR.mkdir(exist_ok=True)
    size   = max(CFG_HUT_SIZE, CFG_CAMP_SIZE)
    colour = CFG_HUT_COLOUR
    files  = {
        "sprite_HUT.png":      _render_sprite_img("HOUSE", CFG_HUT_SIZE,  CFG_HUT_COLOUR),
        "sprite_TENT.png":     _render_sprite_img("TENT",  CFG_CAMP_SIZE, CFG_CAMP_COLOUR),
        "sprite_combined.png": _render_combined_img(size, colour),
    }
    for name, img in files.items():
        p = ASSETS_DIR / name
        img.save(p)
        print(f"  {p}  {img.size}")

def _paste_sprite(tile_img, spr, px, py):
    ox = px - spr.width  // 2
    oy = py - spr.height // 2
    tile_img.paste(spr, (ox, oy), mask=spr)

# ── DOC API — fetch, cache, overlay ──────────────────────────────────────────
DOC_BASE      = "https://api.doc.govt.nz"
DOC_CACHE_DIR = Path(__file__).parent.parent / "experiments" / "doc_cache"

def fetch_doc_cache():
    key = os.environ.get("DOC_API")
    if not key:
        sys.exit("ERROR: set DOC_API in .env")
    headers = {"x-api-key": key}
    DOC_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for resource in ("huts", "campsites"):
        url = f"{DOC_BASE}/v2/{resource}"
        print(f"Fetching {url} ...")
        r = requests.get(url, headers=headers, timeout=60)
        r.raise_for_status()
        data = r.json()
        if data:
            print(f"  Sample keys: {list(data[0].keys())}")
        path = DOC_CACHE_DIR / f"{resource}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  {len(data)} {resource} saved -> {path}")

def load_doc_cache():
    result = {}
    for resource in ("huts", "campsites"):
        path = DOC_CACHE_DIR / f"{resource}.json"
        if path.exists():
            result[resource] = json.loads(path.read_text(encoding="utf-8"))
            print(f"  DOC cache: {len(result[resource])} {resource}")
        else:
            result[resource] = []
            print(f"  DOC cache: no {resource}.json (run --fetch-doc first)")
    return result

def _doc_ll(item):
    """Extract (lat, lon) from a DOC API item. DOC API returns NZTM2000 (EPSG:2193)."""
    try:
        easting  = float(item["x"])
        northing = float(item["y"])
    except (KeyError, TypeError, ValueError):
        return None
    if not HAS_PYPROJ:
        return None
    lon, lat = _nztm_to_wgs84.transform(easting, northing)
    return lat, lon

def render_doc_overlays(tile_img, doc_cache, bbox, tile_km=10.0, placed_boxes=None):
    """Draw DOC huts + campsites for this tile. Merges nearby hut+camp pairs.
    At 4km/2km, also renders name labels with collision avoidance."""
    west, south, east, north = bbox

    def ll_to_px(lat, lon):
        x = int((lon - west)  / (east  - west)  * W)
        y = int((north - lat) / (north - south) * H)
        return max(0, min(W-1, x)), max(0, min(H-1, y))

    huts, camps = [], []
    for item in doc_cache.get("huts", []):
        ll = _doc_ll(item)
        if ll and south <= ll[0] <= north and west <= ll[1] <= east:
            huts.append((ll_to_px(*ll), item.get("name", "")))
    for item in doc_cache.get("campsites", []):
        ll = _doc_ll(item)
        if ll and south <= ll[0] <= north and west <= ll[1] <= east:
            camps.append((ll_to_px(*ll), item.get("name", "")))

    merge_dist = CFG_HUT_SIZE + CFG_CAMP_SIZE + 4
    pairs = sorted(
        (math.hypot(hp[0] - cp[0], hp[1] - cp[1]), hi, ci)
        for hi, (hp, _hn) in enumerate(huts)
        for ci, (cp, _cn) in enumerate(camps)
        if math.hypot(hp[0] - cp[0], hp[1] - cp[1]) <= merge_dist
    )

    merged_huts, merged_camps = set(), set()
    sprite_positions = []
    for _, hi, ci in pairs:
        if hi in merged_huts or ci in merged_camps:
            continue
        (hx, hy), hname = huts[hi]
        (cx, cy), cname = camps[ci]
        spr = _combined_sprite_img(max(CFG_HUT_SIZE, CFG_CAMP_SIZE), CFG_HUT_COLOUR)
        mx, my = (hx + cx) // 2, (hy + cy) // 2
        _paste_sprite(tile_img, spr, mx, my)
        sprite_positions.append((mx, my, hname))
        merged_huts.add(hi)
        merged_camps.add(ci)

    hut_spr  = _sprite_img(CFG_HUT_SHAPE,  CFG_HUT_SIZE,  CFG_HUT_COLOUR)
    camp_spr = _sprite_img(CFG_CAMP_SHAPE, CFG_CAMP_SIZE, CFG_CAMP_COLOUR)
    for hi, ((hx, hy), hname) in enumerate(huts):
        if hi not in merged_huts:
            _paste_sprite(tile_img, hut_spr, hx, hy)
            sprite_positions.append((hx, hy, hname))
    for ci, ((cx, cy), cname) in enumerate(camps):
        if ci not in merged_camps:
            _paste_sprite(tile_img, camp_spr, cx, cy)
            sprite_positions.append((cx, cy, cname))

    # At 4km/2km, render name labels next to sprites (with collision avoidance)
    label_count = 0
    if tile_km <= 5 and sprite_positions:
        draw = ImageDraw.Draw(tile_img)
        try:
            font = ImageFont.load_default(size=9)
        except TypeError:
            font = ImageFont.load_default()
        boxes = list(placed_boxes) if placed_boxes else []
        def _boxes_overlap(a, b):
            return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]
        for sx, sy, name in sprite_positions:
            if not name:
                continue
            # Strip common suffixes to save space
            short = name.replace(" Hut", "").replace(" Campsite", "").replace(" Camp", "")
            tx, ty = sx + CFG_HUT_SIZE + 3, sy - 4
            tb = draw.textbbox((tx, ty), short, font=font)
            if tb[2] + 1 > W:
                tx -= (tb[2] + 1 - W)
            if tb[3] + 1 > H:
                ty -= (tb[3] + 1 - H)
            if tb[0] - 1 < 0:
                tx += (1 - tb[0])
            if tb[1] - 1 < 0:
                ty += (1 - tb[1])
            tb = draw.textbbox((tx, ty), short, font=font)
            padded = (tb[0]-2, tb[1]-2, tb[2]+2, tb[3]+2)
            if any(_boxes_overlap(padded, b) for b in boxes):
                continue
            boxes.append(padded)
            draw.rectangle([tb[0]-1, tb[1]-1, tb[2]+1, tb[3]+1], fill=WHITE)
            draw.text((tx, ty), short, fill=BLACK, font=font)
            label_count += 1

    return {"huts": len(huts), "campsites": len(camps),
            "combined": len(merged_huts), "doc_labels": label_count}

# ── Demo mode (synthetic data, no GeoPackage) ─────────────────────────────────
def render_demo(draw, bbox):
    import random
    west, south, east, north = bbox
    rng = random.Random(int(abs(west * 100) + abs(south * 100)))

    def px(lon, lat):
        return (max(0, min(W-1, int((lon - west) / (east - west) * W))),
                max(0, min(H-1, int((north - lat) / (north - south) * H))))

    cx, cy = (west + east) / 2, (south + north) / 2
    span_lon, span_lat = east - west, north - south

    for elev in range(0, 500, 20):
        scale = 1 - elev / 500
        rx, ry = span_lon * 0.45 * scale, span_lat * 0.40 * scale
        pts = [px(cx + rx * math.cos(2*math.pi*i/40),
                  cy + ry * math.sin(2*math.pi*i/40)) for i in range(41)]
        draw.line(pts, fill=BLACK, width=2 if elev % 100 == 0 else 1)

    river = [px(west + span_lon * (0.1 + 0.7*t) + rng.uniform(-0.002, 0.002),
                south + span_lat * (0.2 + 0.6*t) + rng.uniform(-0.002, 0.002))
             for t in [i/19 for i in range(20)]]
    draw.line(river, fill=BLACK, width=1)

    lx, ly = west + span_lon * 0.2, south + span_lat * 0.15
    lake = [px(lx + span_lon*0.07*math.cos(2*math.pi*i/20),
               ly + span_lat*0.05*math.sin(2*math.pi*i/20)) for i in range(21)]
    draw.polygon(lake, fill=YELLOW, outline=BLACK)

    track = [px(cx + span_lon*(0.1 + 0.3*math.sin(t*math.pi)),
                south + span_lat*(0.2 + 0.6*t) + rng.uniform(-0.003, 0.003))
             for t in [i/14 for i in range(15)]]
    draw.line(track, fill=RED, width=1)

    hx, hy = px(cx + span_lon*0.1, cy + span_lat*0.1)
    draw.ellipse([hx-4, hy-4, hx+4, hy+4], fill=RED)
    pkx, pky = px(cx, cy)
    draw.ellipse([pkx-3, pky-3, pkx+3, pky+3], fill=BLACK)

# ── Overlays ──────────────────────────────────────────────────────────────────
def draw_overlays(draw, km_width):
    font = ImageFont.load_default()
    ax, ay = W - 15, 18
    draw.polygon([(ax, ay-10), (ax-5, ay+5), (ax+5, ay+5)], fill=BLACK)
    draw.text((ax-3, ay+6), "N", fill=BLACK, font=font)
    bar_w = int(W / km_width * 0.5)
    bx, by = 5, H - 8
    draw.rectangle([bx, by-3, bx+bar_w, by], fill=BLACK)
    draw.text((bx, by-14), "500m", fill=BLACK, font=font)

# ── Palette quantisation ──────────────────────────────────────────────────────
_PAL_IMG: Image.Image | None = None

def _pal_img() -> Image.Image:
    global _PAL_IMG
    if _PAL_IMG is None:
        _PAL_IMG = Image.new("P", (1, 1))
        flat = []
        for rgb in [BLACK, WHITE, YELLOW, RED]:
            flat.extend(rgb)
        flat.extend([0] * (256 * 3 - len(flat)))
        _PAL_IMG.putpalette(flat)
    return _PAL_IMG

def quantize_to_palette(img: Image.Image) -> Image.Image:
    """Snap every pixel to the nearest 4-colour palette entry, no dither."""
    return (img.convert("RGB")
               .quantize(palette=_pal_img(), dither=Image.Dither.NONE)
               .convert("RGB"))

# ── 2bpp packing (matches img_to_epd.py) ─────────────────────────────────────
def nearest_code(rgb):
    r, g, b = rgb
    best, best_d = 0x1, float("inf")
    for (pr, pg, pb), code in PALETTE_CODES.items():
        d = (r-pr)**2 + (g-pg)**2 + (b-pb)**2
        if d < best_d:
            best_d, best = d, code
    return best

def img_to_bin(img):
    raw = img.convert("RGB").tobytes()
    buf = []
    for row in range(H):
        for col in range(0, W, 4):
            byte = 0
            for bit in range(4):
                px_idx = col + bit
                if px_idx < W:
                    i = (row * W + px_idx) * 3
                    code = nearest_code((raw[i], raw[i+1], raw[i+2]))
                else:
                    code = 0x1
                byte |= code << (6 - bit * 2)
            buf.append(byte)
    return bytes(buf)

# ── Inspect (GeoPackage schema diagnostic) ────────────────────────────────────
def inspect_gpkg(lat, lon, tile_km=2.0):
    if not HAS_FIONA:
        sys.exit("ERROR: pip install fiona")
    bbox = make_bbox(lat, lon, tile_km / 2)
    print(f"Bbox: W={bbox[0]:.4f} S={bbox[1]:.4f} E={bbox[2]:.4f} N={bbox[3]:.4f}")
    print(f"Coverage: {bbox_km_width(bbox):.2f} km wide\n")
    for layer in LAYER_GPKG:
        p = _gpkg_path(layer)
        if not p.exists():
            print(f"  {layer:12s}  MISSING ({p})")
            continue
        with fiona.open(str(p)) as src:
            feats = list(src.filter(bbox=bbox))
            schema = src.schema
            print(f"  {layer:12s}  {len(feats):5d} features in tile  "
                  f"| schema: geom={schema['geometry']} "
                  f"props={list(schema['properties'].keys())[:6]}")

# ── Single tile ───────────────────────────────────────────────────────────────
def make_tile(sources, centre_lat, centre_lon, tile_km, row, col, out_dir,
              demo=False, doc_cache=None, base_only=False, ref_lat=None):
    bbox = make_bbox(centre_lat, centre_lon, tile_km / 2, ref_lat=ref_lat)

    if demo:
        img  = Image.new("RGB", (W, H), WHITE)
        draw = ImageDraw.Draw(img)
        render_demo(draw, bbox)
        stats = {}
    else:
        # Render terrain with bleed margin for seamless tile edges
        bw, bh = W + 2 * BLEED, H + 2 * BLEED
        dx = (bbox[2] - bbox[0]) / W * BLEED
        dy = (bbox[3] - bbox[1]) / H * BLEED
        bleed_bbox = (bbox[0] - dx, bbox[1] - dy, bbox[2] + dx, bbox[3] + dy)
        big = Image.new("RGB", (bw, bh), YELLOW)
        draw = ImageDraw.Draw(big)
        stats = render_tile_gpkg(sources, bleed_bbox, draw, big, tile_km=tile_km,
                                 canvas_w=bw, canvas_h=bh)
        img = big.crop((BLEED, BLEED, BLEED + W, BLEED + H))

    if not base_only:
        draw = ImageDraw.Draw(img)
        name_stats, placed_boxes = render_place_names(sources, bbox, draw, tile_km)
        stats.update(name_stats)

        if doc_cache:
            doc_counts = render_doc_overlays(img, doc_cache, bbox,
                                             tile_km=tile_km, placed_boxes=placed_boxes)
            for k, v in doc_counts.items():
                if v:
                    print(f"    doc_{k}: {v}")

        draw_overlays(draw, bbox_km_width(bbox))

    out  = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"tile_{row:02d}_{col:02d}"
    quantized = quantize_to_palette(img)
    quantized.save(out / f"{stem}.png")
    if not base_only:
        (out / f"{stem}.bin").write_bytes(img_to_bin(quantized))

    for k, v in stats.items():
        print(f"    {k}: {v}")
    return quantized

# ── Grid ──────────────────────────────────────────────────────────────────────
def generate_grid(centre_lat, centre_lon, radius_km, tile_km, out_dir,
                  demo=False, base_only=False):
    n_tiles = math.ceil(radius_km / tile_km)
    gsz = n_tiles * 2 + 1
    cos_lat = math.cos(math.radians(centre_lat))

    print(f"Grid: {gsz}×{gsz}  (tile={tile_km:.1f} km, "
          f"coverage={gsz * tile_km:.0f} km across, {gsz**2} tiles)"
          + ("  [base only]" if base_only else ""))

    sources = {} if demo else open_sources()
    doc_cache = None if base_only else load_doc_cache()

    images = []
    tiles_meta = []
    for row in range(gsz):
        for col in range(gsz):
            dr = row - n_tiles  # positive = south of centre
            dc = col - n_tiles  # positive = east of centre
            tile_lat = centre_lat - dr * tile_km / 111.0
            tile_lon = centre_lon + dc * tile_km / (111.0 * cos_lat)
            bbox = make_bbox(tile_lat, tile_lon, tile_km / 2, ref_lat=centre_lat)
            print(f"  [{row:02d},{col:02d}]  lat={tile_lat:.4f}  lon={tile_lon:.4f}")
            img = make_tile(sources, tile_lat, tile_lon, tile_km, row, col,
                            out_dir, demo=demo, doc_cache=doc_cache,
                            base_only=base_only, ref_lat=centre_lat)
            images.append((row, col, img))
            tiles_meta.append({
                "row": row, "col": col,
                "centre_lat": round(tile_lat, 6),
                "centre_lon": round(tile_lon, 6),
                "bbox": list(bbox),
            })

    for src in sources.values():
        src.close()

    meta = {
        "centre_lat": centre_lat,
        "centre_lon": centre_lon,
        "tile_km": tile_km,
        "grid_size": gsz,
        "centre_row": n_tiles,
        "centre_col": n_tiles,
        "tiles": tiles_meta,
    }
    (Path(out_dir) / "meta.json").write_text(json.dumps(meta, indent=2))
    print("meta.json written")
    return images, gsz

def make_preview(images, gsz, path):
    canvas = Image.new("RGB", (gsz * W, gsz * H), WHITE)
    for row, col, img in images:
        canvas.paste(img, (col * W, row * H))
    canvas.save(path)
    print(f"Preview -> {path}")

# ── Overlay pass ─────────────────────────────────────────────────────────────
def apply_tile_overlay(base_path, sources, doc_cache, tile_meta, tile_km, out_dir):
    """Load a base PNG and apply overlay layers (labels, sprites, decorations)."""
    row, col = tile_meta["row"], tile_meta["col"]
    bbox = tuple(tile_meta["bbox"])

    img = Image.open(base_path).convert("RGB")
    draw = ImageDraw.Draw(img)

    stats, placed_boxes = render_place_names(sources, bbox, draw, tile_km)

    if doc_cache:
        doc_counts = render_doc_overlays(img, doc_cache, bbox,
                                         tile_km=tile_km, placed_boxes=placed_boxes)
        for k, v in doc_counts.items():
            if v:
                print(f"    doc_{k}: {v}")

    draw_overlays(draw, bbox_km_width(bbox))

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stem = f"tile_{row:02d}_{col:02d}"
    quantized = quantize_to_palette(img)
    quantized.save(out / f"{stem}.png")
    (out / f"{stem}.bin").write_bytes(img_to_bin(quantized))

    for k, v in stats.items():
        print(f"    {k}: {v}")


def _is_ocean_tile(img_path):
    """Check if a base tile is pure yellow (ocean — no land features)."""
    img = Image.open(img_path).convert("RGB")
    extrema = img.getextrema()
    return extrema == ((255, 255), (255, 255), (0, 0))


def generate_overlay(base_dir, out_dir):
    """Apply overlay layers to all base tiles. Fast pass — no terrain re-render."""
    import shutil
    base = Path(base_dir)
    meta_path = base / "meta.json"
    if not meta_path.exists():
        sys.exit(f"ERROR: {meta_path} not found")

    meta = json.loads(meta_path.read_text())
    tile_km = meta["tile_km"]
    tiles = meta.get("tiles", [])

    if not tiles:
        sys.exit("ERROR: no tiles in meta.json")

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Pre-render canonical ocean tile (yellow + north arrow + scale bar)
    ocean_img = Image.new("RGB", (W, H), YELLOW)
    ocean_draw = ImageDraw.Draw(ocean_img)
    draw_overlays(ocean_draw, tile_km)
    ocean_quantized = quantize_to_palette(ocean_img)
    ocean_png_path = out / "_ocean.png"
    ocean_quantized.save(ocean_png_path)
    ocean_bin = img_to_bin(ocean_quantized)

    print(f"Overlay: {len(tiles)} tiles from {base_dir} -> {out_dir}")

    sources = open_sources()
    doc_cache = load_doc_cache()

    ocean_count = 0
    land_count = 0
    for t in tiles:
        row, col = t["row"], t["col"]
        stem = f"tile_{row:02d}_{col:02d}"
        base_png = base / f"{stem}.png"
        if not base_png.exists():
            print(f"  [{row:02d},{col:02d}]  SKIP — base not found")
            continue

        if _is_ocean_tile(base_png):
            ocean_quantized.save(out / f"{stem}.png")
            (out / f"{stem}.bin").write_bytes(ocean_bin)
            ocean_count += 1
            continue

        print(f"  [{row:02d},{col:02d}]  lat={t['centre_lat']:.4f}  lon={t['centre_lon']:.4f}")
        apply_tile_overlay(base_png, sources, doc_cache, t, tile_km, out_dir)
        land_count += 1

    for src in sources.values():
        src.close()

    shutil.copy2(meta_path, out / "meta.json")
    print(f"Overlay complete — {land_count} land + {ocean_count} ocean = {land_count + ocean_count} tiles -> {out_dir}")

# ── CLI ───────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--demo",        action="store_true",
                    help="Synthetic tiles — no GeoPackage data needed")
    ap.add_argument("--inspect",     action="store_true",
                    help="Print GeoPackage layer info for one tile then exit")
    ap.add_argument("--fetch-doc",   action="store_true",
                    help="Download DOC huts+campsites to cache and exit (needs DOC_API in .env)")
    ap.add_argument("--save-sprites", action="store_true",
                    help="Write sprite PNGs to assets/ for external editing, then exit")
    ap.add_argument("--lat",    type=float,
                    default=float(os.environ.get("MAP_LAT", -39.15)),
                    help="Centre latitude  (default: MAP_LAT from .env)")
    ap.add_argument("--lon",    type=float,
                    default=float(os.environ.get("MAP_LON", 175.65)),
                    help="Centre longitude (default: MAP_LON from .env)")
    ap.add_argument("--radius", type=float,
                    default=float(os.environ.get("MAP_RADIUS", 4.0)),
                    help="Coverage radius in km (default: MAP_RADIUS from .env, 4 km)")
    ap.add_argument("--tile-km", type=float,
                    default=float(os.environ.get("MAP_TILE_KM", 2.0)),
                    help="Coverage per tile in km (default: MAP_TILE_KM from .env, 2 km = ~10 m/px)")
    ap.add_argument("--out",    default=None,
                    help="Output directory (default: pod/experiments/map_tiles/)")
    ap.add_argument("--preview", action="store_true",
                    help="Stitch all tiles into one preview PNG")
    ap.add_argument("--base-only", action="store_true",
                    help="Terrain only — no labels, sprites, or decorations (overlay pass later)")
    ap.add_argument("--overlay",   action="store_true",
                    help="Apply overlay (labels, sprites, scale bar, north arrow) to base tiles")
    ap.add_argument("--base-dir",  default=None,
                    help="Directory containing base tiles (required with --overlay)")
    args = ap.parse_args()

    if args.fetch_doc:
        fetch_doc_cache()
        return

    if args.save_sprites:
        print("Saving sprites to assets/:")
        save_sprites()
        return

    if args.inspect:
        inspect_gpkg(args.lat, args.lon, args.tile_km)
        return

    if args.overlay:
        if not args.base_dir:
            sys.exit("ERROR: --overlay requires --base-dir")
        out_dir = args.out or str(
            Path(__file__).parent.parent / "experiments" / "map_tiles"
        )
        generate_overlay(args.base_dir, out_dir)
        return

    out_dir = args.out or str(
        Path(__file__).parent.parent / "experiments" / "map_tiles"
    )
    images, gsz = generate_grid(
        args.lat, args.lon, args.radius, args.tile_km, out_dir,
        demo=args.demo, base_only=args.base_only,
    )
    if args.preview:
        make_preview(images, gsz, Path(out_dir) / "preview.png")


if __name__ == "__main__":
    main()
