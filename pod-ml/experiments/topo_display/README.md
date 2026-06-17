# Topo display experiment (PARKED 2026-06-12)

Exploration of rendering LINZ topo maps to the pod's **1.54" 4-colour e-ink** (black / white / red / yellow).
Parked after the colour scheme + scale were settled. Not wired into anything; reference only.

## Decisions
- **Single layer: TOPO50 only.** The two-layer TOPO50+TOPO250 zoom was dropped — too much complexity for the value.
- **Native window only, never downscale.** A downscaled wide area = unreadable mud; a **200 px native window** (1 map-px = 1 screen-px) is legible.
- **Scale (from GeoTIFF, NZTM2000 / EPSG:2193):** TOPO50 = **4.233 m/px** (= 1:50k @ 300 DPI), so a **200 px window ≈ 0.85 km** square (~13–15 min walk across — an "immediate surroundings" view).
- **Pre-tile offline, stream one ~10 KB 4-colour tile from SD per view** (kills the memory worry; never render the source on-device).
- **No Floyd–Steinberg dithering** — it speckles line-art. Use feature-class colour rules.

## Locked colour scheme ("G-swapped")
| Feature (source colour) | → 4-colour | Role |
|---|---|---|
| open ground / paper | **yellow** | accent — clearings/tussock/riverbeds (campsite, above-bushline cues) pop |
| bush / vegetation (green) | **white** | dominant background — black contours "breathe" on it (classic topo look) |
| rivers / lakes / sea (blue) | **red** | water / crossings — safety |
| contours + roads + tracks + text (brown/black) | **black** | linework |

- **Key insight:** make the *dominant* terrain the white background and the *minority* the accent — the eye goes to the rare/interesting thing. (Earlier "yellow bush" version was busier.)
- **Convention caveat:** this **inverts LINZ** (standard = white open, green bush). More legible, but "white = bush" reads backwards to a trained map-reader. Acceptable for a personal device.
- The same rules transfer to TOPO250 (roads black, water red, etc.) — kept here for reference even though TOPO250 isn't used.
- **Open polish (not needed to ship):** in steep terrain contours are dense; thinning to *index contours only* (needs vector data or morphological thinning) would clean it up further. White background already makes this optional.

## Files
- `originals/` — source GeoTIFFs (`BK34.tif` = TOPO50, `250-05.tif` = TOPO250). **Git-ignored** (large binaries).
- `scripts/` — throwaway render scripts (hardcoded paths assume repo root; tweak if re-running).
- `samples/` — rendered PNGs. `G_swap_locations.png` is the chosen scheme across 6 locations; `variations.png` = the A–D colour comparison.
