# Stellar-map legibility mock

A throwaway visual study for putting a star chart on the pod's **1.54" 4-colour
e-paper (200×200, Black/White/Red/Yellow, full-refresh only, 27×27 mm physical)**.
Not firmware — a PIL render to judge whether a sky chart is legible at this size
*before* writing any C++.

## Run
```
python mock.py
```
Outputs (in this folder):
- `sky_native.png` — true 200×200 (what the panel actually holds; still larger than the real 27 mm)
- `sky_x4.png` — nearest-neighbour ×4 so individual pixels are visible

Every pixel is snapped to the 4 panel inks at the end, so there's no
anti-aliasing the real display couldn't reproduce.

## Design decisions baked in
- **Black sky background.** On white paper, yellow has almost no contrast; on
  black, white *and* yellow both read as bright inks (and it's literally the
  night sky).
- **Colour semantics:** white = fixed framework (stars + constellation lines),
  red = noteworthy/transient (planets `+`, deep-sky markers), yellow =
  warm/diffuse (Moon disc, Milky Way). White vs yellow is treated as a *subtle*
  cue only — never load-bearing — because they look near-identical at 1px.
- **Shape over colour:** planets are red `+`, Moon is a phase disc, deep-sky are
  open squares — each reads even if you can't resolve the colour.
- **Magnitude → dot size** (3/2/1/single px); **min-separation dedup** so dense
  regions don't smear.
- **Looking-up orientation:** E on the left, W on the right (mirror of a desk
  star atlas).

## Findings so far
- Works better than expected: Crux, Orion, Scorpius read from the lines; red
  planets/Moon are unmistakable.
- **Weak point:** the yellow Milky Way stipple does *not* separate from the faint
  white star field — at 1px, faint-white ≈ yellow. A diffuse object only reads if
  it's denser/cloudier than any star group, or drawn as an outline.
- At 27 mm true size, single-pixel background stars are near the eye's resolution
  limit → plot **fewer** stars (~mag ≤2.5) and let the lines carry structure.

## v2 — sparse + confident (`mock_v2.py`)
Acts on the v1 findings: drops the faint star field, the Milky Way stipple, and
the dotted 30-deg ring. Shows only constellation lines + member stars, a few very
bright stars, planets, and the Moon. Two changes that worked:
- **Constellation lines in yellow, star-dots in white on top** — dots clearly pop
  over the lines; lines guide the eye without competing. Validated at true size.
- **No sub-pixel stars** — faintest plotted is 1px.

Outputs: `sky_v2_native.png`, `sky_v2_x4.png`. Every pattern (Orion, Scorpius,
Crux, the Pointers) reads at 27 mm. Looks sparse only because just 3 constellations
+ 2 loners are placed; a curated ~20-30 constellation set would fill the dome at
this same per-constellation density. **v2 is the working direction.**

The outer ring is the **horizon** (dome edge = ground, centre = zenith); it anchors
the N/E/S/W labels. v1's faint inner ring was dropped as clutter.

## Real sky (`sky_real.py`)
Drives the v2 style from real data instead of hand-placed stars:
- **Stars:** Hipparcos catalogue (skyfield), curated to mag <= 3.2 + a ~34-entry
  southern-weighted constellation whitelist + 4 px min-separation dedup.
  (`CURATE=False` shows the full mag-4.5 / all-88 sky -- an unreadable knot at
  200 px; that's the proof that curation is mandatory.)
- **Lines:** real constellation figures from d3-celestial (`conlines.json`,
  RA/Dec vertices), clipped at the horizon.
- **Bodies:** all 5 naked-eye planets + Sun + Moon from the de421 ephemeris, true
  alt/az, Moon illuminated-fraction phase, drawn only when above the horizon, as
  red `+` + 1-2 char labels.
- **Projection:** stereographic zenithal dome, looking-UP (N top, E left), horizon ring.

Deps: `pip install skyfield` (pulls de421.bsp ~17 MB + hip_main.dat into this
folder on first run; both cached). Needs the venv with pip bootstrapped.

```
python sky_real.py                 # default: Auckland 01:00 NZST 15 May 2026
python sky_real.py 2026 5 15 7 eve # any instant: Y M D H(UTC) [output-tag]
```

### Findings
- **Auckland @ 01:00 NZST 15 May 2026:** every planet + Sun + Moon is BELOW the
  horizon (Moon 8% lit). Correct -- the ecliptic has set. So that instant is a
  pure star+constellation chart; nothing to draw for bodies.
- **@ 19:00 NZST** (`_eve`): Jupiter (20deg, NW) + Venus (on horizon) render with
  red labels; red-on-black is clearly legible. May 2026 is otherwise a thin
  planet month.
- Curated real chart reads well; full uncurated sky does not. Hydra still sprawls
  near the zenith -- trim the whitelist further if wanted.

Outputs: `sky_real_native.png`/`_x4.png` (01:00), `sky_real_eve_*` (19:00), etc.

## Status
Exploratory only (2026-06-15). No firmware, no decision on what to include yet
(planets/Moon/deep-sky toggles are open). The render pipeline is now real:
catalogue + ephemeris + alt/az projection in the v2 style.
