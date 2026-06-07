# Pod-ML Deployment Checklist

**Last updated:** 2026-06-07

## Data Status

| Dataset | Status | Notes |
|---|---|---|
| ERA5-Land `core` grid | ✅ Done | 180/180 months (2010–2024), VM `data/raw/era5_grid/core/` |
| ERA5-Land `more_labels_1` | ⏳ Downloading | 6/180 months, ETA ~29h; snowfall + surface_runoff |
| GPM IMERG | ⏳ Downloading | 98/295 (33%), ETA ~197h, VM `data/raw/gpm_grid/` |
| DEM | ✅ Done | `data/raw/dem_nz.nc` |
| Open-Meteo | On-demand | Query after hikes via `fetch_openmeteo.py`; no cron job |

## Pre-Run Checks

```bash
# Config + data integrity
python -m podml.config_validate

# Deep file integrity check (ERA5 + GPM grids)
python -m podml.validate
python -m podml.validate --dataset era5
python -m podml.validate --dataset gpm
```

## ERA5 Downloads (VM)

```bash
# Already done — core group (sp, t2m, d2m, tp), 2010–2024
python -m podml.download_era5_grid --group core

# Not yet started — supplemental labels
python -m podml.download_era5_grid --group more_labels_1
```

## Skill Probe

```bash
# Optimistic ceiling (ERA5 features, ERA5 labels)
python -m podml.probe

# Deployable estimate (ERA5 features, BME280 sensor-sim degradation)
python -m podml.probe --sensor-sim

# Honest transfer test (ERA5 features, GPM labels — once GPM complete)
python -m podml.probe --label-source gpm
```

## Feature Schema (Pod-Replicable)

13 columns — order is the contract (pod C++ must match bit-for-bit):

| # | Column | Description |
|---|---|---|
| 1 | `sp_hPa` | Absolute surface pressure |
| 2–7 | `sp_rate_3h` … `sp_rate_72h` | Pressure tendencies (6 windows) |
| 8 | `rh` | Relative humidity |
| 9 | `rh_trend_3h` | Humidity 3h trend |
| 10 | `t2m_C` | Temperature |
| 11 | `t2m_trend_3h` | Temperature 3h trend |
| 12 | `month` | Month of year |
| 13 | `hour_utc` | Hour UTC |

## Label Schema

- **Thresholds:** 0.5, 2.5, 7.6 mm/hr
- **Horizons:** 6, 12, 24, 48 hours
- **Columns:** `ge{thr}_h{h}` (e.g. `ge0.5_h6`, `ge2.5_h12`, `ge7.6_h48`)
- **Values:** 0 / 1 / NaN (incomplete future window)

## Known Issues

| Issue | Impact | Mitigation |
|---|---|---|
| ERA5 labels are circular | Optimistic ceiling | Use GPM labels for honest validation |
| GPM download incomplete | Limited honest labels | Graceful skip of missing months |
| No wind sensor on pod | Can't use u10/v10 features | Pressure tendencies sufficient |
| No field data yet | Untested on real pod sensors | Deploy ERA5-trained; fine-tune on hikes |
| Coastal cells NaN in ERA5-Land | Inference near coast fails | Nearest-valid-land fallback needed (v2) |

## Documentation

- `docs/01-pipeline.md` — pipeline overview and status
- `docs/02-design-decisions.md` — design choices with diagrams
- `docs/03-datasets.md` — ERA5 product choice, variable groups, acquisition status
- `ARCHITECTURE.md` — module descriptions and data flow
