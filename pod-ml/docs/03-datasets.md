# Datasets — which ERA5 product, and why

The ERA5 archive has several *products* that are easy to confuse. Picking the wrong one silently breaks
either feature parity (using variables the pod can't sense) or the tendency features (using daily data).

## ERA5 product families

| Product (CDS id) | Grid | Cadence | Levels | Use for us? |
|---|---|---|---|---|
| ERA5-Land hourly (`reanalysis-era5-land`) | **0.1°** | hourly | **surface** | ✅ **FEATURES** |
| ERA5 single levels (`reanalysis-era5-single-levels`) | 0.25° | hourly | surface | ⚠️ gust + MSLP + CAPE labels only |
| ERA5 pressure levels (`...-pressure-levels`) | 0.25° | hourly | **upper air (37 lvls)** | ❌ pod can't sense upper air |
| ERA5 *daily statistics* (any) | 0.25° | **daily** | — | ❌ daily erases pressure tendency |

## Why ERA5-Land for features

- **0.1° (~9 km)** resolves NZ's terrain (valleys, coast, rain shadow) far better than 0.25°.
- **Surface variables only** — matches what the pod's BME280 + GPS can actually measure, which is required
  for feature parity (the model may only use inputs the pod can reproduce on-device).

### Variables we pull (and what we derive)

| Need | ERA5-Land variable | Note |
|---|---|---|
| Pressure | `surface_pressure` | **No MSLP in ERA5-Land** → we reduce to sea level via orography ourselves |
| Temperature | `2m_temperature` | Kelvin → °C |
| Humidity | `2m_dewpoint_temperature` | **No direct RH** → derive RH from T + Td |
| Wind | `10m_u_component_of_wind`, `10m_v_component_of_wind` | mean wind (see gusts caveat) |
| Precip (cross-check) | `total_precipitation` | accumulated; GPM IMERG is the primary label source |
| Elevation | orography / surface geopotential | for the sea-level pressure reduction |

## Labels come from elsewhere

- **Precip** → **GPM IMERG** (better precip than ERA5-Land; verify timestamp convention for the
  strictly-after-T window).
- **Wind gusts** → **ERA5 single levels** (`instantaneous_10m_wind_gust`) — **ERA5-Land has no gusts.**
  Decision deferred to step 4 (label construction): use single-levels gusts, or proxy from ERA5-Land mean
  wind. MSLP and CAPE also live here if we ever want them as *label-side* context (not pod features).

## What we explicitly do NOT use

- **Pressure-level (upper-air) data** — the pod can't measure 500/850 hPa fields, so using them would break
  feature parity. They're only training-time info the device lacks → unusable at inference.
- **Daily-aggregated products** — destroy the sub-daily pressure tendency that is our main signal.

## Step-2 verification results (2026-06-02)

Pulled the 1-week June-2022 slice via the time-series endpoint and confirmed reality vs. the assumptions
above. Outcome: **assumptions hold.**

- **Delivery format gotcha:** despite `data_format: netcdf`, the time-series endpoint returns a **`.zip`
  of three per-group NetCDF files** (wind / 2m-temperature / pressure-precipitation). We extract + merge
  on the shared coords (`compat="override"`) — handled in `download_era5.load_timeseries()`.
- **Variables/units confirmed:** `sp` (Pa), `t2m`/`d2m` (K), `u10`/`v10` (m s⁻¹), `tp` (m, de-accumulated).
  No `msl`, no gusts — as expected.
- **Time coord:** `valid_time`, **hourly** (3600 s spacing), instantaneous for state variables. The
  de-accumulated `tp` period convention (hour-ending vs -beginning) is **TBD at step 4** — matters only
  for labels, and GPM is the primary label source anyway.

### ⚠️ ERA5-Land is land-only — coastal cells are NaN-masked

The original West-Coast probe point (Hokitika, −42.72/170.97 → snapped −42.7/171.0) came back **all-NaN**:
a 9 km cell on NZ's razor-thin West Coast is mostly Tasman Sea, so ERA5-Land masks it. Christchurch,
Mt Cook, Auckland, and Milford were all fine (168/168). Fix: relocated the West-Coast point inland to a
valid foothills cell (−42.70/171.10).

**Downstream implication (note for v2 zoning / inference):** a hiker's GPS can also land on a masked
coastal cell. The runtime zone-lookup will need a **"nearest valid land cell" fallback** (snap to the
closest non-masked cell) rather than returning NaN features. Cheap to precompute from the land-sea mask.

### GPM IMERG labels — verified (2026-06-02)

Pulled 2 half-hour granules (GPM_3IMERGHH **V07** Final) for 2022-06-01:
- **Field `precipitation`** (V07 name; was `precipitationCal` in V06), units **mm/hr**, dims (time, lon, lat).
- **Timestamp = period-BEGINNING (confirmed via `time_bnds`).** `time` is the window start; `time_bnds =
  [start, start+30 min]` (00:00 granule → [00:00, 00:30]; 00:30 → [00:30, 01:00]), matching the filename
  `S…-E…`. → for the strictly-after-T label, sum granules with `time_bnds.start ≥ T`.
- Calendar is cftime **DatetimeJulian** — convert when aligning to ERA5's `datetime64`.
- Sample NZ-box precip reached ~47 mm/hr (vs ERA5-Land's smoothed ~18) — GPM captures the extremes ERA5
  misses, which is the whole reason it's the label source.
- **Bonus fields:** `probabilityLiquidPrecipitation` (%, rain/snow split), `precipitationQualityIndex`,
  `randomError` (mm/hr, optional sample weighting).
- **Access gotcha (reproducibility):** GES DISC returns HTTP 403 `{"error_description":"EULA Acceptance
  Failure","resolution_url":"…/approve_app?client_id=e2WVk8Pw6weeLUKZYOxvTQ"}` until that client is
  approved once per Earthdata account. earthaccess surfaces it as a misleading generic "EULA" traceback.
- **Full label pull (step 4):** granules are GLOBAL (~30 MB each, 48/day). Pulling years of these is heavy
  → use spatial subsetting (Harmony/OPeNDAP) to the NZ box, or extract only the probe-point pixels.

## Static: elevation (DEM) — ETOPO 2022

For point **stratification** and the **elevation feature** we use **ETOPO 2022** (NOAA NCEI, public domain),
not Copernicus 30 m, for v1:

- **OPeNDAP-subset to the NZ box**, so only the subset (~MBs) transfers — no giant global download and **no
  rasterio/GIS dependency** (xarray + netcdf4 read it). `download_dem.py` → `data/raw/dem_nz.nc`.
- **30 arc-sec (~0.9 km)** is ample: GPM labels are 11 km, so finer elevation adds no *trainable* signal, and
  inference uses the pod's own altitude anyway. Copernicus 30 m point-sampling is a clean later swap if
  feature-importance says elevation carries a lot.
- Negative values are ocean (bathymetry) → **land mask = elevation > 0**. `sample_points.py` aggregates the
  DEM onto the ERA5-Land 0.1° grid (per-cell mean elevation over land pixels + land fraction), keeps
  majority-land cells, and stratify-samples across elevation bands. See
  [02 · Gridded model](02-design-decisions.md#gridded-model-pre--and-post-training-grid-logic).

## Acquisition status (2026-06-04)

Two background pulls running on the VM (different services, no contention):

| Pull | Module | Output | Range | ETA |
|---|---|---|---|---|
| **GPM** rain labels (HHR 30-min), full NZ grid | `download_gpm_harmony` | `data/raw/gpm_grid/gpm_YYYY-MM.nc` (checkpointed per month) | 2000-06 → 2024-12, newest-first | ~40 min/month → recent 5 yr ~2 days, full ~8–9 days |
| **ERA5** features at 205 stratified cells | `download_era5 --points-file` | `data/raw/era5land_ts_<name>_*.nc` (checkpointed per point) | 2000 → 2024 | queue-paced, resumable |

> GPM ends at **2024**, not 2025: IMERG **Final** latency means late-2025 isn't posted yet — the pull skips
> empty recent months cleanly. ERA5 matches the **2000–2024 GPM overlap** (no point pulling features where
> there's no rain label). Both `data/raw/*` are gitignored and re-derived on each machine; the **point list**
> (`config/sampled_points.csv`) is committed so both machines pull the identical set.
