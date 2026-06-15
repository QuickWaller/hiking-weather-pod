# 12 — Recent-data GPM fine labels (IMERG Late Run)

**Status:** decided + tooling built & smoke-tested, 2026-06-13.

## Decision

The **fine model** and **combined weights** are validated/labelled against **GPM IMERG Late Run**, pulled
per GPS-point-and-time for recent hikes. MetService API access is *not* a dependency — we can layer a station
cross-check on later if we ever want it, but the pipeline does not wait on it.

We explicitly **rejected ERA5 / Open-Meteo as the rain truth** for this. Open-Meteo's historical archive *is*
ERA5 under the hood, and ERA5 precipitation is a reanalysis **model output**, not an observation — biased
exactly where NZ hurts (convective showers, orographic uplift). Worse, the coarse model already trains on GPM
labels, so regressing the fine output toward ERA5 rain would pull it *away* from truth, not toward it. ERA5/
Open-Meteo stay in their lane: **feature** sources (pressure/temp/humidity), never the rain label.

## Why Late Run specifically

GPM IMERG publishes three runs of the same V07 product. Our training archive (`gpm_grid/`) is the **Final
Run** — gauge-corrected but ~3.5 months latent, so it can *never* cover a hike you did last week.

| Run | short-name | latency | gauge-corrected | use |
|---|---|---|---|---|
| Early | `GPM_3IMERGHHE` | ~4 h | no | last few days |
| **Late** | `GPM_3IMERGHHL` | **~14 h** | no | **last week / month — fine labels** |
| Final | `GPM_3IMERGHH` | ~3.5 mo | yes | training archive (unchanged) |

Late is satellite-only (no gauge correction) — a minor extra raw-satellite bias over NZ terrain, acceptable
for labels, and it keeps the fine labels in the **same observation family** as the coarse model's GPM labels.
Same 0.1° (~10 km) grid, same half-hourly cadence, same `precipitation` field (mm/hr), same period-beginning
timestamps as the Final Run.

**Harmony collection concept-id (v07):** `C2723754845-GES_DISC` — verified via CMR, sits next to Final's
`...847`. Lives in `config/nz_domain.yaml` → `gpm_imerg_late:`.

## Semantics — this is a *check*, not a forecast label

The training archive feeds forward-looking labels (rain accumulated *after* time T). The fine-label tool does
the opposite: it returns the rain intensity for the half-hour granule that **contains** the query time —
"what was actually falling where/when the pod was." Query time T → granule start = `floor(T, 30 min)`.

## Tool — `download_gpm_late.py`

A second, independent downloader (the Final-Run archive puller is untouched). Takes GPS points (or boxes) with
specific UTC times; writes to a **separate** directory so it never mixes with the training archive.

```
# batch — the pod-driven path (CSV: time,lat,lon[,name], UTC times)
python -m podml.download_gpm_late --queries hike_2026-06-11.csv

# single point at one time
python -m podml.download_gpm_late --lat -36.66 --lon 174.73 --time 2026-06-11T21:00 --name long_bay

# one point, every half-hour over a window
python -m podml.download_gpm_late --lat -36.66 --lon 174.73 --start 2026-06-11T20:00 --end 2026-06-11T23:00

# a box — store the gridded cutout (NetCDF), no point extraction
python -m podml.download_gpm_late --bbox 174.5,-36.9,175.0,-36.4 --start 2026-06-11T21:00 --end 2026-06-11T22:00
```

**Outputs** (separate from `gpm_grid/`):
- `data/raw/gpm_fine/fine_labels.csv` — appended point results: `name, query_time_utc, lat, lon,
  granule_start_utc, pixel_lat, pixel_lon, precip_mm_hr, prob_liquid_pct, quality_index`
- `data/raw/gpm_fine/grids/late_<UTC>.nc` — cutout grids (`--bbox` mode)

Queries are grouped by half-hour granule so each granule is pulled once even with many points. All times are
**UTC** (the pod logs GPS UTC). Times more recent than the ~14 h latency resolve to `NaN` with a printed note.

## Verification (2026-06-13)

Smoke-tested end-to-end on the VM against the existing Harmony plumbing (reuses `_run_job`/`_open_grid`):

- Harmony accepts the Late concept-id through the **unchanged** request path; bbox subsetting returns a small
  cutout (not the global granule).
- **Long Bay, 09:00 NZST 12-Jun (= 21:00 UTC 11-Jun)** → grid pixel −36.65/174.75 (the ~10 km cell, ~3.4 km
  off the beach), **0.0 mm/hr**, 100 % liquid, quality 0.78. Cross-checked against ERA5 (0.0 mm surrounding
  hours) → the zero is a genuine dry reading, not a fill value.
- Batch path with two points in different half-hours grouped into the correct two granules.

Unit tests: `tests/test_gpm_late.py` (granule flooring, tz→UTC normalisation, queries-CSV parsing/validation).

## Worked example — reading a row

`long_bay, 2026-06-11 21:00:00, -36.66, 174.73, 2026-06-11 21:00:00, -36.65, 174.75, 0.0, 100.0, 0.782`
means: at the pod's logged position (−36.66, 174.73) for the half-hour beginning 21:00 UTC, the nearest GPM
cell (−36.65, 174.75) observed **0.0 mm/hr** of rain, of which 100 % would have been liquid (vs frozen), with
a quality index of 0.78 (0–1, higher = more confident retrieval).
