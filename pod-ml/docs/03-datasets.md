# Datasets — which ERA5 product, and why

The ERA5 archive has several *products* that are easy to confuse. Picking the wrong one silently breaks
either feature parity (using variables the pod can't sense) or the tendency features (using daily data).

## ERA5 product families

| Product (CDS id) | Grid | Cadence | Levels | Use for us? |
|---|---|---|---|---|
| ERA5-Land hourly (`reanalysis-era5-land`) | **0.1°** | hourly | **surface** | ✅ **FEATURES + SUPPLEMENTAL LABELS** |
| ERA5 single levels (`reanalysis-era5-single-levels`) | 0.25° | hourly | surface | ⚠️ gust + MSLP + CAPE labels only |
| ERA5 pressure levels (`...-pressure-levels`) | 0.25° | hourly | **upper air (37 lvls)** | ❌ pod can't sense upper air |
| ERA5 *daily statistics* (any) | 0.25° | **daily** | — | ❌ daily erases pressure tendency |

## Why ERA5-Land for features

- **0.1° (~11 km)** resolves NZ's terrain (valleys, coast, rain shadow) far better than 0.25°.
- **Surface variables only** — matches what the pod's sensors + GPS can actually measure, which is required
  for feature parity (the model may only use inputs the pod can reproduce on-device).

### Variable groups

Variables are downloaded in named groups via `python -m podml.download_era5_grid --group <name>`.
Each group writes to `data/raw/era5_grid/<group>/era5land_nz_YYYY-MM.nc` with independent checkpointing.

#### `core` — feature variables (downloaded: 2010–2024, 180 months)

| ERA5-Land variable | Short name | Derived | Note |
|---|---|---|---|
| `surface_pressure` | `sp` | → MSLP via DEM | No MSLP in ERA5-Land — we reduce to sea level ourselves |
| `2m_temperature` | `t2m` | K → °C | |
| `2m_dewpoint_temperature` | `d2m` | → RH via Magnus formula | No direct RH in ERA5-Land |
| `total_precipitation` | `tp` | accumulated m | GPM IMERG is the primary label; this is a cross-check |

> **Wind (u10/v10) is not in the gridded download** — the pod has no anemometer, so wind is never a
> feature. It may appear as a label-side variable from ERA5 single-levels (gusts) if needed.

#### `more_labels_1` — supplemental label variables (downloading: 6/180 months, ETA ~29h as of 2026-06-07)

| ERA5-Land variable | Short name | Use |
|---|---|---|
| `snowfall` | `sf` | Snow severity label; alpine/sub-alpine sites |
| `surface_runoff` | `sro` | Ground saturation proxy; future river-flooding model |

Download command: `python -m podml.download_era5_grid --group more_labels_1`

## Labels come from elsewhere

- **Rain/storm** → **GPM IMERG** (better precip than ERA5-Land; verify timestamp convention for the
  strictly-after-T window).
- **Snow** → ERA5-Land `snowfall` (`more_labels_1` group above).
- **Wind gusts** → **ERA5 single levels** (`instantaneous_10m_wind_gust`) — ERA5-Land has no gusts.
  Decision deferred to step 4.

## What we explicitly do NOT use

- **Pressure-level (upper-air) data** — the pod can't measure 500/850 hPa fields, so using them would break
  feature parity. They're only training-time info the device lacks → unusable at inference.
- **Daily-aggregated products** — destroy the sub-daily pressure tendency that is our main signal.
- **ERA5-Land time-series product** (`reanalysis-era5-land-timeseries`) — only exposes 18 variables (no
  snowfall, no runoff) and delivers individual-point files. Superseded by the gridded download.

## Static data

### Elevation (DEM) — ETOPO 2022

`data/raw/dem_nz.nc` — one-time static file, NZ bounding box, OPeNDAP-subsetted (~MBs).

- **30 arc-sec (~0.9 km)** resolution, aggregated to the 0.1° ERA5-Land grid in `sample_points.py`.
- Used for: surface pressure → MSLP reduction; elevation feature; land-cell stratified sampling.
- Negative values = ocean (bathymetry) → land mask = elevation > 0.

### Open-Meteo (real-time + historical)

- **No cron job.** On-demand only — query after a hike via `fetch_openmeteo.py` with the route coordinates
  and time window. Open-Meteo historical API (backed by ERA5) goes back to 1950 at any lat/lon, hourly, free.
  Instant post-hoc validation without pre-collecting fixed-point data.

## Acquisition status (2026-06-07)

| Dataset | Location | Status | Notes |
|---|---|---|---|
| ERA5-Land `core` grid | VM `data/raw/era5_grid/core/` | ✅ Done | 180/180 months, 2010–2024, sp/t2m/d2m/tp |
| ERA5-Land `more_labels_1` | VM `data/raw/era5_grid/more_labels_1/` | ⏳ Downloading | 6/180 months, ETA ~29h, snowfall + surface_runoff |
| GPM IMERG labels | VM `data/raw/gpm_grid/` | ⏳ Downloading | 98/295 (33%), 2000–2024, ETA ~197h |
| DEM (ETOPO 2022) | Local `data/raw/dem_nz.nc` | ✅ Done | Static, one-time |
| Open-Meteo validation | VM `data/raw/openmeteo/` | On-demand | Query after hikes via `fetch_openmeteo.py`; no cron |

### ⚠️ ERA5-Land is land-only — coastal cells are NaN-masked

The original West-Coast probe point (Hokitika, −42.72/170.97 → snapped −42.7/171.0) came back all-NaN:
a 9 km cell on NZ's razor-thin West Coast is mostly Tasman Sea. Relocated inland to −42.70/171.10.

**Downstream implication (v2 zoning / inference):** a hiker's GPS can land on a masked coastal cell.
The runtime zone-lookup needs a **"nearest valid land cell" fallback** rather than returning NaN features.

### GPM IMERG labels — verified (2026-06-02)

Pulled 2 half-hour granules (GPM_3IMERGHH **V07** Final) for 2022-06-01:
- **Field `precipitation`** (V07 name; was `precipitationCal` in V06), units **mm/hr**, dims (time, lon, lat).
- **Timestamp = period-BEGINNING (confirmed via `time_bnds`).** → for the strictly-after-T label, sum
  granules with `time_bnds.start ≥ T`.
- Calendar is cftime **DatetimeJulian** — convert when aligning to ERA5's `datetime64`.
- Sample NZ-box precip reached ~47 mm/hr (vs ERA5-Land's smoothed ~18) — GPM captures the extremes ERA5
  misses, which is the whole reason it's the label source.
- **Access gotcha:** GES DISC returns HTTP 403 until the Earthdata client is approved once per account.
