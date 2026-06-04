# Pod-ML Weather Prediction Pipeline

## Overview

Pod-ML is a data engineering + machine learning pipeline that trains and validates LightGBM weather prediction models for the hiking pod. The pipeline enables **field validation** of pod predictions against real-world weather data.

**Key principle:** Train on historical ERA5 data (2010–2022) with clean sensor inputs → validate on real 2024 observations (Open-Meteo) to discover model weaknesses before field deployment.

## Architecture

```
ERA5 timeseries (2010–2022)        Open-Meteo observations (2024+)
        ↓                                  ↓
 download_era5.py ←────────────→ fetch_openmeteo.py
        ↓                                  ↓
data/raw/era5land_ts_*.nc        data/raw/openmeteo/*.csv
        ↓                                  ↓
 raw_signals() ←────────────────────→ openmeteo_to_signals()
        ↓                                  ↓
features.py: pressure/temp/humidity     (same feature format)
   (tendencies, absolute levels, month/hour)
        ↓                                  ↓
 build_features()              build_features_from_signals()
        ↓                                  ↓
data/features_era5.csv    (features match schema exactly)
        ↓                                  ↓
labels.py (ERA5 precip)    labels_gpm.py (satellite rainfall)
        ↓                                  ↓
ge{thr}_h{h} binary labels for:   (same 12-column format)
  0.5, 2.5, 7.6 mm/hr
  6, 12, 24, 48 hour horizons
        ↓                                  ↓
train/test split (2010–2022 / 2024)
        ↓
 LGBMClassifier (50 models: 3 thresholds × 4 horizons × 5 points)
        ↓
probe.py: Brier Skill Score (BSS) vs climatology baseline
        ↓
outputs/skill_probe_era5.csv  &  skill_probe_gpm.csv
outputs/feature_importance_*.csv
```

## Modules

### Data Acquisition

- **`download_era5.py`** — ERA5-Land hourly reanalysis (2010–2022) via CDS API. Returns NetCDF with sp, t2m, d2m, u10, v10.
- **`download_gpm_harmony.py`** — GPM IMERG satellite rainfall via Harmony API. Monthly 0.1° grids, 30-min resolution.
- **`download_dem.py`** — Digital elevation model for altitude-based sampling.
- **`fetch_openmeteo.py`** — Real-time hourly weather observations (precip, pressure, temp, humidity) from Open-Meteo. Cron-driven, 7-day rolling window.

### Feature Engineering

- **`features.py`** — Pod-replicable feature vector (24 features):
  - Pressure absolute + 6 pressure tendencies (3h–72h windows)
  - Temperature + 3h trend
  - Humidity + 3h trend
  - Month, hour UTC (for seasonality, time-of-day)
  - **Contract:** Pod C++ code must reproduce these bit-for-bit. No wind features (pod has no anemometer).

- **`sensorsim.py`** — Sensor degradation layer:
  - Adds realistic noise to pressure/temp/humidity (BME280-like biases)
  - Pressure offset (cancels in trends, persists in absolute level)
  - Temperature warm bias (±1.5°C) + small noise
  - Humidity noise + clipping to [0, 100]%
  - **Use case:** Train on clean ERA5 → test on sensor-degraded features = "deployable" skill.

### Labels (Ground Truth)

- **`labels.py`** — Binary rain-severity labels from ERA5 precipitation:
  - Forward-looking window (6h, 12h, 24h, 48h)
  - Three thresholds (0.5, 2.5, 7.6 mm/hr)
  - Output: 12 columns (ge{threshold}_h{horizon})
  - **Caveat:** Circular (ERA5 features + ERA5 labels) → optimistic skill ceiling.

- **`labels_gpm.py`** — Binary rain-severity labels from GPM IMERG (honest):
  - Satellite-measured rainfall (independent of ERA5)
  - Resample 30-min → hourly max (rainfall semantics)
  - Same output format as `labels.py` (drop-in replacement)
  - **Use case:** Test ERA5-trained model on GPM labels → gap = circularity bias.

### Point Sampling

- **`sample_points.py`** — Extract ERA5 and GPM timeseries at specific lat/lon:
  - Nearest-neighbor or bilinear interpolation
  - Handles missing/corrupted data gracefully
  - 5 NZ probe points: Hokitika, Christchurch, Mt Cook, Long Bay, Milford (see `config.py`)

### Model Training & Validation

- **`probe.py`** — Dress-rehearsal skill probe:
  - Train: LGBMClassifier on 2010–2022 ERA5 features + labels
  - Test: 2024 features + (ERA5 or GPM) labels
  - Metrics: Brier Skill Score (BSS), Precision-Recall AUC, confusion breakdown at 70% recall
  - Separate "clean" (optimistic ceiling) vs "sensor-sim" (deployable) skill tracks
  - **Flag:** `--label-source {era5,gpm}` for side-by-side comparison

- **`validate_openmeteo.py`** — Real-time validation against Open-Meteo:
  - Loads Open-Meteo hourly observations for each probe point
  - Builds features + labels from the same data
  - Trains on 70%, tests on 30% (quick baseline)
  - Or integrates with pre-trained ERA5 model (research-mode)
  - **Use case:** "How is the model performing on actual NZ weather right now?"

### Plotting & Analysis

- **`plots.py`** — Visualization utilities:
  - Skill vs horizon (line plots)
  - Confusion matrices
  - Feature importance (bar charts)

## Data Paths

```
data/
├── raw/
│   ├── era5land/               # ERA5-Land NetCDFs from CDS (2010–2022)
│   │   └── era5land_ts_2010-2022.nc
│   ├── gpm_grid/               # GPM IMERG monthly grids (2024+, incomplete)
│   │   └── gpm_2024-03.nc, gpm_2024-04.nc, ...
│   ├── dem/                    # Elevation data (auxiliary)
│   └── openmeteo/              # Real-time observations (cron-fetched, 7-day rolling)
│       ├── hokitika_westcoast.csv
│       ├── christchurch_lee.csv
│       └── ...
│
├── features/                   # Processed features (cache, optional)
│   └── features_era5_*.csv
│
└── processed/                  # Final train/test datasets (intermediate)
```

## Validation Workflow (Field Deployment)

1. **Collect field data** — Pod logs on hikeS with manual activity groundtruth
2. **Compare pod predictions vs. Open-Meteo** — Use `validate_openmeteo.py`
3. **Identify systematic biases** — pressure overestimation? activity misclassification?
4. **Label field data** — Manually note: precipitation (yes/no), temperature, visibility, activity
5. **Retrain on field data** — Transfer learning: start with ERA5 weights, fine-tune on real pod logs
6. **Redeploy** — Updated model with field-learned adjustments

## Testing

- **51 tests:** Features (trailing slope, RH calculation, feature parity), labels, sensorsim, GPM label loading
- **64 tests** after recent expansion (edge cases: NaN handling, boundary conditions, sign conventions)
- Run all: `pytest` (from pod-ml root)
- Run one suite: `pytest tests/test_features.py -v`

## Known Limitations

1. **Circular ERA5 labels** — Features and labels from same physics model. BSS is optimistic ceiling (true skill is lower).
2. **Incomplete GPM data** — Only 11 of 294 months downloaded (June 18 ETA for completion). Labels skip missing months gracefully.
3. **No field data yet** — Model trained on ERA5 reanalysis, untested on actual pod sensor data.
4. **No activity validation** — Pod predicts activity (climbing/walking/resting) but not yet validated in field.
5. **Single model per point** — No spatial transfer learning (Mt Cook model can't help Hokitika).

## Next Steps

1. **Fix probe.py** — Support mixed label sources (ERA5 train, GPM test) for honest transfer validation
2. **Collect field data** — 5–10 hikes with pod + manual groundtruth
3. **Expand validation** — Storm confidence, activity accuracy, modifier (temp/visibility)
4. **Retrain on field data** — Fine-tune ERA5 weights with real pod observations
5. **Automate GPM completion** — When download finishes (June 18), re-run probe with full dataset

## References

- ERA5-Land: https://www.ecmwf.int/en/forecasts/datasets/reanalysis-datasets/era5-land
- GPM IMERG: https://gpm.nasa.gov/data/imerg
- Open-Meteo: https://open-meteo.com (CC BY 4.0, free tier)
- LightGBM: https://lightgbm.readthedocs.io
