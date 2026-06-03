# Pipeline overview

v1 is **point-based** — we prove a single-location model has real skill *before* building the spatial
zoning machinery (SKATER), which is deferred to v2. The skill probe (step 5) is a hard gate: if a point
model can't beat climatology, no amount of zoning or tuning will save it.

```mermaid
flowchart TD
    S1["1 · Scaffold + env"] --> S2["2 · Data acquisition<br/>+ variable verification<br/>(ERA5-Land + GPM IMERG, NZ)"]
    S2 --> S3["3 · Sensor-sim + features<br/>(shared C feature code via cffi)"]
    S3 --> S4["4 · Label construction<br/>(max-severity + accumulation,<br/>embargo, timestamp alignment)"]
    S4 --> S5["5 · Skill probe<br/>(horizon sweep, BSS vs climatology)"]
    S5 --> G{"Does the sensor beat<br/>climatology?"}
    G -->|yes| S6["6 · Expand: more cells,<br/>threshold-decomposition models, tuning"]
    G -->|no| R["Rethink: shorter horizon, or<br/>ship as a trend-indicator only"]
    S6 --> S7["7 · v2: zoning (SKATER),<br/>compact tree-interpreter export, flash to pod"]
```

## Why this order

- **Riskiest unknown first.** The single biggest risk is *scientific*, not engineering: can one point predict
  rain hours ahead at all? Step 5 answers it cheaply before we invest in zoning, export, or firmware.
- **Data/variable verification (step 2) before features (step 3).** The design assumes certain variables exist
  in ERA5-Land/GPM (e.g. it gives *surface* pressure, not MSLP). We confirm the real catalogues before writing
  feature code against assumptions.
- **Features (step 3) share code with the pod.** Built once in C++, called from Python via cffi, so the model
  trains on the exact bytes the pod will compute — see [02-design-decisions.md](02-design-decisions.md#feature-parity).

## Phase 2 — "train for real" (gridded)

The point probe (steps 1–5) cleared the gate: a single location predicts near-term rain. We're now scaling
from 5 points to the whole country **without** pulling a terabyte, via a **one global model + static
covariates** architecture — full design and diagrams in
[02 · Gridded model](02-design-decisions.md#gridded-model-pre--and-post-training-grid-logic).

```mermaid
flowchart TD
    P2a["DEM (ETOPO) → land mask + elevation<br/>(download_dem.py)"] --> P2b["stratify ~200 cells across<br/>elevation bands (sample_points.py)<br/>→ config/sampled_points.csv"]
    P2b --> P2c["bulk ERA5 pull at those cells<br/>(download_era5 --points-file)"]
    GPM["GPM grid pull<br/>(download_gpm_harmony)"] --> P2d
    P2c --> P2d["labels (fwd windows + nowcast h0 + snow)<br/>+ training table → train global model"]
    P2d --> P2e["post-training SKATER zoning<br/>+ per-zone calibration → flash"]
```

**Status (2026-06-04):** DEM + sampler done (`config/sampled_points.csv` = 205 cells); GPM and ERA5 pulls
running in the background on the VM — see
[03 · Acquisition status](03-datasets.md#acquisition-status-2026-06-04). **Next:** the label builder (forward
windows + horizon-0 nowcast + snow), then assemble the training table and train.
