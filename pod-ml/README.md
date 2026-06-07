# pod-ml: NZ Hiking Weather Prediction ML Pipeline

ML pipeline for NZ weather prediction + real-time pod validation.

## Data Status

| Dataset | Location | Status |
|---|---|---|
| ERA5-Land `core` grid | VM `data/raw/era5_grid/core/` | ✅ Done — 180 months (2010–2024), sp/t2m/d2m/tp |
| ERA5-Land `more_labels_1` | VM `data/raw/era5_grid/more_labels_1/` | ⏳ Not started — snowfall + surface_runoff |
| GPM IMERG rain labels | VM `data/raw/gpm_grid/` | ⏳ Downloading — 2000–2024 |
| DEM (ETOPO 2022) | Local `data/raw/dem_nz.nc` | ✅ Done — static, one-time |
| Open-Meteo validation | VM `data/raw/openmeteo/` | ✅ Live — hourly cron, 5 probe points |

## Directory Layout

```
data/
├── raw/
│   ├── era5_grid/
│   │   ├── core/               # sp, t2m, d2m, tp — 2010–2024, monthly grids
│   │   └── more_labels_1/      # snowfall, surface_runoff — not yet downloaded
│   ├── gpm_grid/               # GPM IMERG 30-min rain labels (downloading)
│   ├── openmeteo/              # real-time hourly observations, 5 probe points
│   └── dem_nz.nc               # NZ elevation (static)
└── clean/
    └── labels/                 # processed label files (future)
```

## Key Commands

```bash
# Download ERA5 variable groups (run on VM)
python -m podml.download_era5_grid --group core
python -m podml.download_era5_grid --group more_labels_1

# Validate downloaded data integrity
python -m podml.validate

# Run skill probe (requires ERA5 core + GPM)
python -m podml.probe
python -m podml.probe --sensor-sim     # deployable estimate (BME280 biases)
python -m podml.probe --label-source gpm  # honest transfer test

# Config check
python -m podml.config_validate
```

## Validation Strategy

On-demand historical query after each hike — Open-Meteo's historical API (backed by ERA5) covers
1950–present at any lat/lon, free, hourly. Query the exact route coordinates + time window for instant
post-hoc validation. No pre-collection or cron jobs needed; `fetch_openmeteo.py` handles ad-hoc queries.

## Documentation

- `docs/01-pipeline.md` — pipeline overview and phase 2 plan
- `docs/02-design-decisions.md` — design choices with diagrams (label type, sensor trust, validation split)
- `docs/03-datasets.md` — ERA5 product choice, variable groups, acquisition status
- `docs/04-results.md` — skill probe results
- `ARCHITECTURE.md` — module descriptions and data flow

---

See [../CLAUDE.md](../CLAUDE.md) for full project context.
