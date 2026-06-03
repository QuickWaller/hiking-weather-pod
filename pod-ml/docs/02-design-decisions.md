# Design decisions — the *why*, with diagrams

Each section: the choice, the parameter value, and the reasoning. Update the diagram **and** the prose
when a decision changes.

---

## Prediction horizon & the metric (skill over climatology)

**Choice:** sweep prediction **lead** ∈ {6, 12, 24, 48 h}; report **Brier Skill Score vs. climatology**,
never raw accuracy.

Any forecast decomposes into two parts:

```mermaid
flowchart LR
    C["Climatology<br/>(location + month + elevation)<br/>= base rate"] --> F(("Forecast"))
    Y["Synoptic state<br/>(pressure level + tendency)<br/>= what's happening now"] --> F
```

A single barometer can't see upstream, but it *can* sense the **synoptic state**, which in NZ persists
~1–3 days (regular westerly fronts). So pressure tendency carries signal out to ~12–36 h — which is also
the actionable window for hiking ("push to the hut today or tomorrow?").

**The trap:** as the horizon grows, the synoptic signal decays toward the climatological mean, so
climatology carries more of the prediction. Evaluated on **raw accuracy**, a useless model scores ~85%
just by echoing "it's usually dry." We therefore measure **skill *over* climatology** — does knowing the
*sensor reading* beat just knowing where and when you are. The climatology baseline uses a fixed
**1991–2020** reference period (pod-knowable, no train/val leakage).

---

## Label = max severity (not total accumulation)

**Choice:** the acute-danger label is the **maximum severity class in [T, T+H]**, not integrated rainfall.

For hiking safety, one violent frontal hour (ridge/exposure danger) matters more than the same total
dribbled over a day. A second, independent model uses **24 h accumulation** for **river/crossing risk** —
sustained soakers that never spike but still make a crossing lethal. Two hazards, two labels:

```mermaid
flowchart TD
    GPM["GPM IMERG precip"] --> MX["max of hourly intensity<br/>→ ACUTE model (0-5)"]
    GPM --> AC["24h sum<br/>→ RIVER model (watch/orange/red)"]
    MX --> A["Banner / Worried / buzzer"]
    AC --> B["River-risk indicator"]
```

---

## Sensor trust split (pressure backbone, T/H low-trust)

**Choice:** lean on **pressure tendencies** as the high-trust backbone; **down-weight temp/humidity**.

```mermaid
flowchart TD
    BME["BME280<br/>(backpack, cabled probe, pointing down)"] --> PR["Pressure"]
    BME --> TH["Temp / Humidity"]
    PR -->|"siting-robust;<br/>tendency cancels bias"| HI["HIGH trust"]
    TH -->|"radiative warm bias +<br/>poor ventilation when stationary"| LO["LOW trust (down-weight)"]
    HI --> FV["Feature vector"]
    LO --> FV
```

**Why:** gas pressure equalises regardless of a warm case — it doesn't care about siting. Temp/humidity on a
pack suffer solar/radiative warm bias, *worst* when stationary (no airflow) — which is exactly when inference
is gated to run. Absolute pressure bias (±1 hPa) and GPS-altitude error (~0.12 hPa/m → 1.2–3.6 hPa) both
**cancel in tendencies** (subtraction), so rates beat absolute level. Training augments a **one-sided warm
bias** on temp (contamination only warms) and a per-station pressure offset.

---

## Validation split (contiguous past→future, embargoed)

**Choice:** train 2010–2022 / val 2023 / test 2024, with an **embargo = H** at each boundary. Never random.

```mermaid
flowchart LR
    T["Train<br/>2010-2022"] --> E1[/"embargo H"/] --> V["Val<br/>2023"] --> E2[/"embargo H"/] --> Te["Test<br/>2024"]
```

**Why not random:** weather is autocorrelated — a randomly-held-out hour sits *between* two training hours,
so the model interpolates (trivial, leaks) instead of extrapolating to an unseen future (the real deployment
task). The **embargo** drops samples whose label window straddles a boundary (adjacent samples share almost
their whole window). When we add cells, the time boundary is **global** across all cells, because neighbouring
cells at the same timestamp are near-duplicate observations of the same weather system.

---

## Class structure — ordinal threshold decomposition {#threshold}

**Choice:** K−1 binary "severity ≥ k" classifiers, **not** a single 6-way softmax. Class count set
empirically (count class-4/5 events first; likely merge extreme → ~5 classes).

```mermaid
flowchart LR
    F["Feature vector"] --> B2["P(severity ≥ 2)"] --> Y["Yellow banner"]
    F --> B4["P(severity ≥ 4)"] --> R["Red banner + Worried"]
    F --> B5["P(severity ≥ 5)"] --> Z["Buzzer (overrides quiet hours)"]
```

**Why:** the pod's banner *is* a set of thresholds, so this maps 1:1. Each binary gets its own
**operating point** — high-severity thresholds biased toward recall (catch storms) but capped to limit
false alarms (**cry-wolf erodes trust**, making the warning useless). Imbalance handled with
`scale_pos_weight` + majority undersampling; **no SMOTE** (it fabricates temporally-incoherent weather).
Metric: **PR-AUC + per-class recall** (ROC-AUC flatters rare-event performance).

---

## Feature parity — one code path {#feature-parity}

**Choice:** the pod's C++ feature functions are the **single source of truth**; training calls them via cffi.

```mermaid
flowchart TD
    SRC["C++ feature functions<br/>(extern C, no Wire.h/Arduino deps)"] --> LIB["compiled shared lib"]
    LIB -->|"cffi"| TR["Training: ERA5 → features"]
    LIB -->|"firmware"| POD["Pod: sensors → features"]
    TR --> MODEL[("trained model")]
    MODEL --> POD
```

**Why:** if features were implemented twice (Python + C++), any difference — even a different pressure-rate
estimator — means the model trains on one distribution and runs on another, degrading **silently**
(training-serving skew). One shared implementation makes the mismatch *impossible by construction*. A small
**golden-vector** suite guards against future drift. The **sensor-sim layer** (offset, temp-comp, altitude,
cadence, quantization, warm-bias augmentation) sits in front of this and runs even during the skill probe —
otherwise the probe measures the skill of clean reanalysis, not of the pod.

---

## Climate non-stationarity & the training window

**Choice:** acquire the **full 1991–2024** record, decide the training window **empirically** (ablation),
use a **recent** climatology reference (2005–2022, not WMO 1991–2020), and rely on trend-robust features.

NZ has warmed ~0.1 °C/decade (modest mean drift over our span), but heat extremes are ~**4–5× more frequent**
and rainfall geography is shifting (east drying, west/south wetting). So the climate is non-stationary — the
question is whether old data still helps. The key is *what kind of model we have*:

```mermaid
flowchart TD
    CC["Climate change"] --> M["Marginal distribution + base rates<br/>SHIFT (more extremes, drier east...)"]
    CC -. "negligible on an hours timescale" .-> P["Conditional physics:<br/>current state → next-hours weather<br/>~ STATIONARY"]
    M --> R1["use a RECENT climatology reference (2005-2022)"]
    M --> R2["training-window ABLATION decides how far back to train"]
    P --> R3["old data still teaches valid physics;<br/>tendencies/anomalies are trend-robust"]
```

**Why we're robust:** the scary non-stationarity results are about *climate emulators / long-range projection*
that must extrapolate the warming trend itself. We don't — we predict short-range severity *given the current
state*. That conditional mechanism (front + falling pressure → rain in hours) is stationary. Climate change
shifts the **marginals and base rates**, not the hours-ahead physics, so old data is valid (if differently
distributed) — and because **extreme classes are data-starved**, more years likely *helps the rare tail*.

**Where it does bite (and the fixes):**
- *Absolute* temperature is non-stationary (a "warm day" in 1995 ≠ 2024) → we already lean on **tendencies**
  and treat temp/humidity as low-trust; where temperature is used, prefer **anomalies vs. a recent normal**.
- The **climatology reference** matters most: 1991–2020 understates "normal now", so we use a recent
  **2005–2022** window (train-only, no val/test leak). Trend-adjusted normals are a future refinement.
- We **don't assume** — step 5 runs a **training-window ablation** ({2015,2010,2000,1991}→2022, all evaluated
  on 2023/24) to measure where older years stop helping. Val/test stay the *most recent* years, so we always
  evaluate on the current climate (what the pod faces).

---

## Gridded model: pre- and post-training grid logic

The point probe proved a single location has skill. To **train for real** we go from 5 points to the whole
country — but **not** by pulling the full ERA5 × GPM grid over 25 years (a terabyte). The architecture lets
us avoid that.

```mermaid
flowchart TD
    subgraph PRE["PRE-TRAINING (build one common-grid table)"]
      E["ERA5-Land<br/>dynamic features"] --> J
      G["GPM IMERG<br/>rain labels"] --> J
      D["DEM (ETOPO)<br/>static: elevation, ruggedness"] --> J
      C["coastline<br/>static: dist-to-coast"] --> J
      J["rows = (land cell × hour)<br/>X = dynamic + static · y = GPM"]
    end
    J --> TR[("ONE global model<br/>cells told apart by<br/>static covariates")]
    TR --> POST
    subgraph POST["POST-TRAINING (shrink the map)"]
      POST1["run model over FULL grid<br/>→ per-cell skill / bias"] --> SK["SKATER → contiguous zones<br/>+ per-zone calibration"]
    end
    SK --> SHIP["ship: 1 tree model<br/>+ zone raster + per-zone offsets"]
```

### One global model, cells told apart by static covariates

**Choice:** train **one** model where each row is an ERA5-Land 0.1° cell carrying its **static context**
(elevation, distance-to-coast, lat/lon) — *not* per-cell or per-zone models.

The model learns *"given this terrain and this pressure trend → this much rain"*, which **generalises to
cells it never saw**. Two payoffs: (1) we can **train on a *sample* of cells**, not all ~6 000 land cells,
because the covariate relationship generalises; (2) it's the only valid order — **SKATER zones can't be
defined until a model exists**, so we train global first regardless.

### Two cheap pulls, not one terabyte

**Choice:** split the ERA5 acquisition so we never pull full-grid × full-history.

```mermaid
flowchart LR
    A["(a) deep history<br/>~200 stratified points<br/>2000-2024 hourly"] --> M[("global model")]
    M --> B["(b) full grid, SHORT window<br/>~1-2 yr · only to run the<br/>trained model everywhere"]
    B --> Z["SKATER zoning"]
```

(a) is the **training** data (the current 5-point pull scaled up). (b) is needed only at the **end**, to run
the finished model over every cell for the zoning pass.

### Static vs dynamic — and what bakes into firmware

**Choice:** pull the **full grid for the cheap STATIC layers**; **sample** the expensive **dynamic** history.

| Grid | Pull every cell? | On the MCU? |
|---|---|---|
| **Dynamic** (ERA5 hourly history) | No — sample | No — time-varying weather the pod senses live |
| **Static** (elevation, ruggedness, coast-dist, **zone ID**, per-cell climatology) | **Yes — cheap** (~6 k cells × bytes) | **Yes — a compressed slice flashes in** |

So the pod ships knowing, for its GPS spot: which **zone** (→ which calibration), its **coast-distance**, the
local **climatological baseline**. Elevation it just *measures*. All KB-scale.

### Altitude: feature resolution ≠ label resolution

**Choice:** elevation is a **cell-representative** value in training, **continuous**, fed the pod's **own
measured altitude** at inference.

The knot is two different resolutions. **Labels are hard-capped at 0.1° (~11 km)** — GPM reports one rain
number per cell, so within-cell rain variation is *not in the truth* and *cannot be learned*. Feeding
elevation finer than the label buys no trainable signal (this is the grain of truth in "it's trained on
averages"). But two things still hold:

- **Don't aggregate to a hand-picked grid; sample the DEM at the cell** so the elevation feature means
  "ground height here" — exactly what the pod feeds at inference (its baro/GPS altitude). The model learns
  the elevation→rain gradient **across** cells (which spans the full 0–2 000 m range cleanly).
- **At inference the pod plugs in its precise altitude** and rides that learned continuous gradient.
  Sub-cell precision is a **sound physical extrapolation** (more height → more orographic rain), not
  validatable (no sub-cell labels exist) — but it's free, so we keep it.

### Stratified sampling — even across elevation, not proportional

**Choice:** ~200 cells sampled **~evenly across elevation bands** (`[0,50,150,400,800,1400]+ m`), retaining
the 5 original probes. High alpine terrain is **rare but is exactly where the orographic signal lives**, so
proportional sampling (which is ~90 % lowland) would starve the gradient. Sampling is seeded and writes a
**committed** `config/sampled_points.csv`, so both machines pull the identical set.

### Smaller calls made alongside

- **Nowcasting (current rain/snow/storm) — build in from the start as horizon 0.** It's the same label
  machinery with no forward window (`X` at `T`, `y` at `T`), usually the **highest-skill** output and a free
  sanity floor (can't nowcast rain from humidity → forecasting is hopeless). **Snow is nearly free** — we
  already store `probabilityLiquidPrecipitation` (frozen/liquid split) + pod temp.
- **Sun vs cloudy-dry — parked as a cheap later experiment.** Label is free (ERA5 `tcc` total cloud cover);
  pod humidity/pressure carry signal. But it's **comfort, not safety**, and multi-day cloud *forecast* is
  harder than rain (cloud is local/chaotic) — the *nowcast* is the feasible part. Build the label, see the
  number, ride behind the hazards.
- **Ground cover / land cover / soil — dropped for v1, parked not abandoned.** They're **runoff** variables
  (weak causal link to rain-from-sky; importance would prune them). Their home is the future **river-flooding
  model**, where ground composition governs rain → river. v1 static features stay elevation + coast + lat/lon.
