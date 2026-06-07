# Pod-ML Architecture

## Overview

Pod-ML trains and validates LightGBM weather prediction models for the hiking pod. It uses ERA5-Land
reanalysis as features and GPM IMERG satellite rainfall as labels, trains a global model across NZ,
then validates against real-time Open-Meteo observations.

**Key principle:** features are pod-replicable only — no wind, no upper-air data. The model must reproduce
the same output from the same sensor readings the pod computes on-device.

## Data Flow

```
ERA5-Land gridded (2010–2024)         GPM IMERG (2000–2024)
data/raw/era5_grid/core/              data/raw/gpm_grid/
        ↓                                    ↓
download_era5_grid.py                download_gpm_harmony.py
        ↓                                    ↓
era5_load.load_era5_nz()          ←→  labels_gpm.build_labels_gpm()
        ↓                                    ↓
features.py: pressure/temp/humidity    forward-window severity labels
(tendencies, absolute levels,          (0.5 / 2.5 / 7.6 mm/hr × 6/12/24/48 h)
 month/hour UTC)
        ↓                                    ↓
              train_grid.py (global model, static covariates)
                              ↓
                    LightGBM model
                              ↓
              post-training SKATER zoning + per-zone calibration
                              ↓
                    flash to pod MCU
```

## Directory Layout

```
data/
├── raw/
│   ├── era5_grid/
│   │   ├── core/               # sp, t2m, d2m, tp — 2010–2024, monthly 0.1° grids
│   │   └── more_labels_1/      # snowfall, surface_runoff — not yet downloaded
│   ├── gpm_grid/               # GPM IMERG 30-min rain labels, 2000–2024
│   ├── openmeteo/              # real-time hourly observations, 5 probe points
│   └── dem_nz.nc               # NZ elevation (ETOPO 2022, static)
└── clean/
    └── labels/                 # processed label files (future step)
```

## Modules

### Data Acquisition

- **`download_era5_grid.py`** — ERA5-Land full NZ spatial grid via CDS. Group-based:
  `--group core` (sp, t2m, d2m, tp) or `--group more_labels_1` (snowfall, surface_runoff).
  Writes monthly NetCDFs to `data/raw/era5_grid/<group>/`. Checkpointed per month.
- **`download_gpm_harmony.py`** — GPM IMERG satellite rainfall via Harmony API.
  Monthly 0.1° grids, 30-min resolution → `data/raw/gpm_grid/`.
- **`download_dem.py`** — ETOPO 2022 elevation, NZ bounding box → `data/raw/dem_nz.nc`.
- **`fetch_openmeteo.py`** — On-demand Open-Meteo query (precip, pressure, temp, humidity).
  Historical API covers 1950–present at any lat/lon. Run after a hike to get ground-truth for
  that route + time window. No cron job — query on demand.

### Data Loading

- **`era5_load.py`** — Load cached ERA5 gridded months:
  - `load_era5_nz(start_year, end_year, group="core")` — lazy spatial dataset
  - `load_point_from_grid(name, cfg, group="core")` — extract nearest grid cell for a probe point

### Feature Engineering

- **`features.py`** — Pod-replicable feature vector (13 features):
  - `sp_hPa` — absolute surface pressure
  - `sp_rate_3h` … `sp_rate_72h` — pressure tendencies (6 windows)
  - `rh`, `rh_trend_3h` — humidity + 3h trend
  - `t2m_C`, `t2m_trend_3h` — temperature + 3h trend
  - `month`, `hour_utc` — seasonality / time of day
  - **Contract:** pod C++ code must reproduce these bit-for-bit. No wind features (no anemometer).

- **`sensorsim.py`** — Sensor degradation layer (BME280-like biases). Train on clean ERA5 → test
  on sensor-degraded features = "deployable" skill estimate.

### Labels

- **`labels.py`** — Rain-severity labels from ERA5 precipitation (optimistic ceiling — circular).
- **`labels_gpm.py`** — Rain-severity labels from GPM IMERG (honest — independent of ERA5 features).
  Forward-looking window, three thresholds (0.5 / 2.5 / 7.6 mm/hr), four horizons (6/12/24/48 h).

### Model Training & Probing

- **`probe.py`** — Point skill probe: train on one grid cell's history, evaluate BSS vs climatology.
  Uses `load_point_from_grid` to extract a probe point from the gridded cache.
- **`probe_with_static.py`** — Same with elevation + climatology static features added.
- **`train_grid.py`** — Full gridded training: one global model across all sampled cells.

### Validation

- **`validate.py`** — Integrity check on downloaded monthly grid files (ERA5 + GPM). Emits JSON
  for the Hermes agent or a human summary. Checks variable presence, timestep count, time axis sanity.
- **`validate_openmeteo.py`** — Compare model predictions vs. real-time Open-Meteo observations.
- **`config_validate.py`** — Pre-run check: probe points in NZ bounds, directories exist, ERA5 grid present.

### Static Features

- **`sample_points.py`** — Stratified sampling of ERA5-Land cells across elevation bands.
  Writes `config/sampled_points.csv` (committed; both machines pull the identical set).
- **`static_features.py`** — Elevation, zone ID, climatology from the ERA5 gridded cache.

## Validation Strategy

On-demand historical query after each hike — Open-Meteo historical API (backed by ERA5, 1950–present,
any lat/lon, hourly, free). Query the exact route coordinates + time window for instant post-hoc
validation. No cron job or pre-collection needed.

## Known Limitations

1. **Circular ERA5 labels** — `labels.py` uses the same ERA5 physics for features + labels. Use
   `labels_gpm.py` for honest evaluation.
2. **GPM download in progress** — labels incomplete; skip missing months gracefully during training.
3. **No field data yet** — model trained on reanalysis, untested on actual pod sensor readings.
4. **Coastal NaN cells** — ERA5-Land masks ocean cells; inference needs a nearest-valid-land fallback.
