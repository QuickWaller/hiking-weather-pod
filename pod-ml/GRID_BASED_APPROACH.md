# Grid-Based Training: Complete Workflow

## Problem We're Solving

Current point-based model (5 locations) has **geographic bias:**
- **Hokitika (wet):** BSS 0.24–0.25 ✓ Good
- **Christchurch (dry):** BSS -0.002 to -0.11 ✗ Fails

**Root cause:** Model learned "rain is frequent" from all 5 training points (which are all wet/moderate). At dry Christchurch, this bias becomes a liability.

**Solution:** Train on **all NZ grid cells** with **static features** (elevation, baseline rainfall). Model learns: "at this elevation, with this baseline rainfall, pressure drop means X."

## Data Strategy

### 1. ERA5 Gridded Data

**Current status:** Only have point timeseries (100 files, 2000–2024).  
**Need:** Full grid for 2010–2022 (train years).

**Three options:**

| Option | Pros | Cons | Action |
|--------|------|------|--------|
| **Pangeo Zarr** (recommended) | Cloud-optimized, no download, lazy eval, scalable | Need to verify exact store URL | Use this FIRST |
| **Google Cloud Storage** | Fast, no auth, scriptable | Need gsutil or google-cloud-storage library | Second choice |
| **CDS API** | Official, flexible subsets | Slow, interactive, requires auth | Last resort |

**Recommendation: Start with Pangeo Zarr** (cloud-native, no download overhead).

### 2. Static Features Per Grid Cell

Already implemented in `static_features.py`:

#### Elevation
- **Source:** DEM (already downloaded via `download_dem.py`)
- **Resolution:** ~0.05° (~5 km)
- **Usage:** Climate zone classification (lowland/hill/alpine)

#### 20-Year Climatology
- **Source:** Compute from ERA5 2010–2022
- **Variables:** Pressure mean, temp mean, humidity mean, precipitation mean
- **Computation:** Simple xarray `.mean(dim='time')` over 13 years
- **Usage:** Baseline rainfall/pressure (model learns anomalies relative to baseline)

#### Climate Zone
- **Derived from elevation:** 0m = lowland (zone 0), 300m = hill (1), 1000m = alpine (2), 2000m = high alpine (3)
- **Pod-queryable:** POD can compute this at runtime from DEM lookup table

### 3. Full Grid Training

**Data shape:**
- ERA5 grid: 0.1° resolution → ~100 lat × 80 lon = 8000 cells
- 13 years × 365 days × 24 hours = 114k timesteps
- **Total:** 8000 cells × 114k timesteps = 912M samples (pooled training)

**Training:**
```python
# Pseudocode
all_features = []
all_labels = []

for year in 2010..2022:
    for month in 1..12:
        # Load ERA5 grid for this month
        era5_grid = load_era5_zarr(year, month)
        
        # Reshape grid → (timesteps, cells)
        features = reshape_to_2d(era5_grid)
        
        # Add elevation + climatology (constant per cell)
        elevation = repeat_for_all_time(dem_grid)
        features = concatenate([features, elevation])
        
        # Build labels from this month's precipitation
        labels = build_labels(era5_grid.tp)
        
        all_features.append(features)
        all_labels.append(labels)

# Train single LightGBM on all data
model = LGBMClassifier()
model.fit(concatenate(all_features), concatenate(all_labels))

# Generate per-cell skill maps
skill_map = per_cell_skill(model.predict(test_features), test_labels)
```

### 4. Validation

Once GPM download complete (June 18):
- Extract GPM at all 8000 grid cells
- Compare model predictions vs GPM truth
- Generate **skill maps** showing which regions are predictable
- Identify remaining biases

## Implementation Timeline

| Phase | Task | Status | Est. Time |
|-------|------|--------|-----------|
| 1 | Find & verify Pangeo Zarr URL | **TODO** | 1 day |
| 2 | Load ERA5 grid → NZ domain | **TODO** | 2 days |
| 3 | Compute 20yr climatology | **TODO** | 1 day |
| 4 | Reshape + add static features | **TODO** | 1 day |
| 5 | Train full grid model | **TODO** | 1 day |
| 6 | Generate skill maps | **TODO** | 1 day |
| 7 | Validate with GPM (June 18+) | **Blocked** | 1 day |

**Total:** ~1 week implementation, then wait for GPM completion.

## Expected Improvements

| Metric | Point-Based | Grid-Based | Why |
|--------|-----------|-----------|-----|
| Training samples | 5 × 114k = 570k | 8000 × 114k = 912M | 1600× more data |
| Christchurch skill | -0.11 | ? (predicted: +0.1+) | Elevation context helps |
| Hokitika skill | +0.24 | ? (predicted: +0.3+) | More data = tighter fit |
| Generalization | 5-point overfitting | Cross-region transfer | Model learns real patterns |

## Code Scaffolding

Already written (stubs ready for implementation):
- `static_features.py` — Load elevation, compute climatology, add to features
- `train_grid.py` — Full grid training loop, per-cell skill maps
- `download_era5_grid.py` — ERA5 grid acquisition (Pangeo/GCS/CDS options)

## Next Steps

1. **Verify Pangeo Zarr availability** (Google for "era5-land pangeo zarr" or check Pangeo docs)
2. **Implement `download_era5_grid.py` zarr option** (xarray + zarr library)
3. **Compute climatology** (simple: `era5_grid.mean(dim='time')`)
4. **Implement `train_grid.py` main function** (reshape → train → skill maps)
5. **Wait for GPM** (June 18) and validate on full satellite data

## Pod Integration (Later)

Once model is trained on grid:
- Pod stores elevation + zone lookup table (small, ~1MB)
- Pod gets GPS location
- Pod queries elevation/zone from table
- Pod adds these as features to pressure/temp/humidity
- Model predicts rain with geographic context

No MCU changes needed — just adds static query table.

---

**Status:** Framework in place, waiting on ERA5 grid access + GPM completion.  
**Owner:** You (grid training) + Claude (implementation).  
**Timeline:** Ready to start Week of June 4, completion by June 20.
