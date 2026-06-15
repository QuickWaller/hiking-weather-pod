# Model Architecture — Combined Coarse / Climatology / Fine Rain Forecast

> **Status: DESIGN (proposed), refined 2026-06-14.** The **coarse** model is built and evaluated (the
> production ensemble — see `11-rain-amount-bakeoff.md` and `10-deployment-and-sync.md` §1b). **Climatology**
> is trivially available (per-cell/month from the GPM archive). The **fine** model and the **gating/weight
> layer** are *not yet implemented* — this doc captures the architecture settled in the 2026-06-13/14 design
> conversations so we build against a written reference.
>
> **Supersedes:** (a) the earlier **two-way** (fine + coarse, climatology welded inside coarse) framing —
> climatology is now a **first-class third model**; (b) any **hardcoded horizon ownership** ("fine owns 0–3 h",
> "coarse owns 6–24 h") — ownership is **emergent** from measured skill; (c) the **rain-onset button** as the
> fine-side truth — the button was removed from the hardware (2026-06-13); fine-side truth is now **GPM-Late**
> (see `12-recent-gpm-fine-labels.md`).

---

## 1. The big picture — three forecasters, one fan

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  INPUTS                                                                        │
│   pod sensors (P/T/RH, 10-min)     ERA5 + GPM (gridded)      GPM archive       │
│   — ONLY where you have walked      — EVERYWHERE             — EVERYWHERE       │
└─────────┬───────────────────────────────┬──────────────────────────┬──────────┘
          │                               │                          │
   ┌──────▼───────┐               ┌────────▼────────┐        ┌────────▼─────────┐
   │  FINE        │               │  COARSE         │        │  CLIMATOLOGY     │
   │  local model │               │  ERA5-trained   │        │  per-cell/month  │
   │  (visited    │               │  ensemble       │        │  rain distribution│
   │   cells)     │               │  (everywhere)   │        │  (static, every- │
   │  q50/q75/q90 │               │  q50/q75/q90    │        │   where) q50/75/90│
   └──────┬───────┘               └────────┬────────┘        └────────┬─────────┘
          │ Q_fine(τ)                Q_coarse(τ)                Q_clim(τ)
          └───────────────┬───────────────┴──────────────────────────┘
                  ┌────────▼─────────┐
                  │   GATING / MIX    │   weights w(cell, horizon[, season])
                  │ Q = w_c·Q_coarse  │   from the WEIGHT MODEL (§4), one per
                  │   + w_k·Q_clim    │   model, ≥0, sum to 1
                  │   + w_f·Q_fine    │   ◄── combination rule OPEN (§3 / D2)
                  └────────┬─────────┘
                  ┌────────▼─────────┐
                  │  RECALIBRATION    │   single all-hours isotonic/PIT recal on the COMBINED
                  │  (D3)             │   output vs GPM (calibrates occurrence + amount jointly)
                  └────────┬─────────┘
                  ┌────────▼─────────┐
                  │  OUTPUT fan       │  one-sided q50/q75/q90 fan (mm/hr, self-gating)
                  └────────┬─────────┘
                  ┌────────▼─────────┐
                  │  e-ink display    │  bottom-aligned rain fan
                  └──────────────────┘
```

The three base models are **independent forecasters**; everything novel is in **how they're combined** — the
weight model (§4) and the mix (§3). **No model is assigned a horizon.** Each is eligible at every lead time;
the share it gets at a given (cell, horizon) is set *only* by its measured skill there.

---

## 2. The three base models

| | **COARSE** (built) | **CLIMATOLOGY** (available) | **FINE** (proposed) |
|---|---|---|---|
| Source | ERA5 reanalysis + GPM labels | per-cell/month GPM history | pod sensors (P/T/RH, 10-min) |
| Coverage | **everywhere** on the NZ grid | **everywhere** (static lookup) | **only visited cells** |
| Update cadence | **manual VM retrain** (infrequent) | **static** (recompute rarely) | **per-sync refit** (every trip) |
| Data regime | data-rich (simulated hiker) | data-rich (archive) | **data-scarce** (a few cells, growing) |
| Output | q50/q75/q90 + Tweedie mean | q50/q75/q90 (empirical) | q50/q75/q90 |
| Role | the synoptic backbone | the safe floor / cold-start base | local correction + sub-hourly edge |

- **Coarse** is trained on the full climate record (ERA5 features, GPM labels), via the motion-sim pipeline
  so its inputs match the pod's signal. It keeps real skill across all 24 h — it does **not** decay to
  climatology at long lead.
- **Climatology** is "what rain does here, this month," with nothing live. It's the **uncorrelated** term
  (coarse and fine both lean on pressure; climatology doesn't) and the guaranteed floor for unvisited cells.
- **Fine** is the only model trained on **real** pod data, at cells you've actually walked. Its edge is local
  bias + **temporal resolution** (10-min dynamics resolve a frontal pressure-V the hourly coarse aliases).
  It is a **peer** (it emits its own distribution, Decision 1 = A), so the *weight model* — not a structural
  anchor — is what keeps a young, noisy fine model out of the forecast. **All cold-start safety lives in the
  gate (§4).**

> Why three, not two-with-climatology-baked-into-coarse: the three live on **three different update loops**
> (manual / static / per-sync), and welding the static everywhere-known climatology into the manually-retrained
> coarse (a) costs ~0.03 CRPSS as a fixed blend tax in cells where the model already wins, and (b) hides the one
> uncorrelated term that helps the combined spread. Separating it lets each weight be **earned**, not fixed.

---

## 3. Combining them — the weighted mix

Per quantile level τ ∈ {0.50, 0.75, 0.90}, at cell *c* and horizon *h*:

```
Q_combined(c,h,τ)  =  w_coarse(c,h)·Q_coarse  +  w_clim(c,h)·Q_clim  +  w_fine(c,h)·Q_fine
                       weights ≥ 0, sum to 1 (SPARSEMAX over three skill-driven logits — can zero a model out), from the META-MODEL (§4)
```

- All three models stay **distributional** — none is reduced to a binary/category.
- The weights are **functions of (cell-features, horizon[, season])**, not per-cell constants — that's what
  lets them generalise to unvisited cells (§6).

**Two sub-decisions still OPEN here:**

- **(D2) Combination rule — decided on ACCURACY (CRPS), not spread/safety** (this is a personal device; there
  is no over-warning bias). The two candidates:
  - *Average the quantiles* (**Vincentization**) — sharper, often better CRPS (Lichtendahl 2013), **but** risks
    over-confidence on the correlated coarse+fine pair, and loses in genuine-disagreement / bimodal cases
    (front-timing: the averaged middle is the one value truth never takes — CRPS punishes mass where the
    outcome isn't).
  - *Mix the distributions* (**linear pool**) — raw form is *under-confident / over-dispersed* → a CRPS cost;
    **but linear-pool + the D3 recalibration = the beta-linear-pool** (Gneiting & Ranjan), the accuracy-
    optimised pooling form.
  Neither dominates — it's **regime-dependent** (Vincentization wins where the models agree, linear pool wins
  where they genuinely disagree). **Decision: bake off recalibrated-linear-pool vs recalibrated-Vincentization
  on horizon-weighted CRPS + bootstrap CI** (same protocol as the N-vs-E rain bake-off, `11-rain-amount-bakeoff.md`);
  **default-scaffold linear pool** until the numbers land. **No hybrid** — Vincentizing the coarse+fine pair
  destroys the §5 disagreement signal *and* over-confidences the correlated pair (dominated).
- **(D3) Calibration — DECIDED: a single all-hours isotonic/PIT recalibration of the combined output**, per
  horizon, fit on **held-out GPM** (replaces *all* per-model conformal). **No wet-conditional, no occurrence
  split** — consistent with the all-hours self-gating distribution. The point mass at 0 is handled by the
  **randomized-PIT** (an observed 0 gets a PIT value spread over `[0, P(dry)]`, making dry hours informative
  about `P(dry)`); the monotone map then calibrates **occurrence and amount jointly**, one map. This recal is
  also what makes D2's linear pool competitive (= the **beta-linear-pool**) and the D2 bake-off fair. Trade:
  CQR's finite-sample coverage *guarantee* → asymptotic (acceptable for a personal device accumulating data).

---

## 4. The meta-model — the gating layer that sets the weights

The weights come from a **small meta-model** whose only job is to output the three mixing weights. It is
**stacking / learning-to-blend** (the three base models are *experts*; this is the *gating network*). It is
**not** a forecaster, and there is **no infinite regress**: it's trained *directly* against the final blended
forecast's error (blend-CRPS vs GPM truth), one meta-level, terminates.

Crucially, the meta-model is **situation-aware**, not a static trust-map: it conditions on *what the weather is
doing right now*, not just where/when you are. So it's a **router** — "in a frontal regime at short lead in
rugged terrain, route to fine" — not a fixed lookup.

### Inputs — what the meta-model sees

Five families. ★ = highest-value / start-here; the rest add as visited cells accumulate (the gate is fit on
**sparse** disagreement signal, so start lean and grow).

- **A. Dynamic regime/state** — *what the weather is doing now* (generalises **physically** → cheap Tier 1/2):
  **pressure tendency** (multi-window rate — front strength), pressure level, humidity (level + trend),
  temperature trend / dewpoint depression. NB pressure tendency **overlaps with the disagreement feature (B)**
  — both proxy "dynamic regime", so it's a *candidate*, **ARD-judged**, not assumed essential. Its non-redundant
  edge: it tells the gate *when fine's dynamics-reading is trustworthy* (real front vs flat-pressure noise), and
  it works **off-trip** where disagreement is undefined. This family is what makes the meta-model a router.
- **B. Inter-model signals** — *how much the choice matters, and is today anomalous*:
  ★ **coarse-vs-fine disagreement magnitude** (a scalar gap, **not** the raw distributions — limits
  overfitting/circularity), and **forecast-vs-climatology distance** (anomaly).
- **C. Static terrain descriptors** — *where the coarse grid fails* (all engineered from the DEM, computed once
  per cell, looked up on-device — see "Terrain" below). ★ **sub-grid elevation anomaly** and **upwind-barrier
  height (prevailing W/NW)**; plus elevation, slope, aspect, multi-scale ruggedness/relief, TPI, distance to
  coast.
- **D. Temporal** — ★ **horizon**; season/month (cyclic); time-of-day (cyclic — diurnal convection).
- **E. Evidence/confidence** — how much data the gate has for this cell. **De-emphasised by decision**
  (2026-06-14): a young deployment is *allowed to over-trust fine to a degree*, so this is a *light* shrinkage
  (or left to the partial-pooling/GP uncertainty), **not** a hard evidence-gate.

> **Terrain is the backbone of the static set** — and for the meta-model specifically, because **fine beats
> coarse exactly where the coarse ERA5 grid (~9–31 km) can't resolve local topography.** Flat → coarse already
> represents you → low `w_fine`; rugged → coarse smooths your valley away → fine has room → high `w_fine`.
> The pointed feature is the **sub-grid elevation anomaly** (cell's true elevation − coarse grid-cell mean):
> a big anomaly literally means "coarse is wrong about where you are." Compute ruggedness/relief **multi-scale**
> (~1/5/20 km) to capture both the immediate valley and the regional barrier — the scalar form of "the
> surrounding height map." Data is in hand (`dem_nz.nc`, ETOPO 2022; `download_dem.py`/`maps.py`).
>
> **No-live-wind constraint:** orographic direction matters, but the pod has **no wind sensor** (compass
> dropped, never a weather input). So directional terrain enters **statically** — **aspect** and
> **prevailing-direction (NZ westerly) upwind barriers** — which captures most of NZ's westerly-dominated
> orographic signal. *Live*-flow-relative terrain is out; computing it from ERA5 wind at training time would be
> a train/serve-skew trap (the pod can't reproduce it). A pressure-pattern flow proxy is a maybe-later.

### Generalising across cells — the three tiers

`w` is built from three stacked tiers (over the inputs above), in increasing data-hunger:

```
 w(cell, h)  =        f_θ( features(cell), h )            +        u(cell)
                ┌──────────────┴───────────────┐                  └───┬───┘
        ┌───────┴────────┐          ┌───────────┴──────────┐          │
        │   TIER 1       │          │      TIER 2          │     ┌─────┴──────┐
        │ global effects │          │   interactions /     │     │  TIER 3    │
        │ one slope per  │          │ varying coefficients │     │ per-cell   │
        │ feature, same  │          │ a feature's IMPACT   │     │ offset:    │
        │ everywhere     │          │ BENDS by cell        │     │ idiosyncratic│
        └───────┬────────┘          └──────────┬───────────┘     └─────┬──────┘
        generalises ✓                generalises ✓            does NOT generalise
        (function of features)        (function of features)   (needs that cell's visits;
                                                                shrinks → 0 without)
```

| Tier | Captures | Function of… | Generalises to unvisited cells? |
|---|---|---|---|
| **1 — global effects** | average impact of each feature on the weight | features | **Yes** |
| **2 — interactions** | "pressure-drop matters more in alpine than flat" | features | **Yes** |
| **3 — per-cell offset** | what features genuinely *can't* explain | nothing — idiosyncratic | **No** (needs visits) |

**Two properties that make this work:**

1. **ARD — confidence shrinks along *weight-relevant* feature changes, not raw distance.** "Similar cells →
   similar weights" must mean similar in the features that actually drive the allocation, weighted by how much
   each matters. The early learner (a Gaussian Process, GP) uses **Automatic Relevance Determination**: a
   *separate learned lengthscale per feature*. Features irrelevant to the weight get long lengthscales (moving
   along them doesn't reduce confidence); features that strongly drive it get short ones (a small change
   collapses confidence). A dissimilar cell (in the *relevant* metric) → high uncertainty → **shrink `w_fine`
   toward 0**, i.e. fall back to the safe coarse/clim base.
   - The weight-relevant features are **not** the rain-relevant ones: they describe *where the global model is
     locally wrong and where sub-hourly signal helps* (terrain ruggedness, coastal proximity, valley
     enclosure, elevation, horizon) — not mean rainfall. ARD discovers them because it's fit against the
     **weight-skill** signal.
   - Chicken-and-egg: the relevance metric is itself learned, so with few cells **seed it with domain priors**
     (ruggedness / coast / elevation plausibly relevant; **raw lat/lon must not dominate** or it memorises
     locations), and sharpen as cells accumulate.
   - **Feature-design instruction:** the descriptors that plausibly modulate fine-vs-coarse must be *in* the
     feature set, or fine's edge falls through to Tier 3 (needs visits, doesn't generalise).

2. **Decomposition — only `w_fine` needs visited cells.** The **coarse-vs-climatology** split can be pinned
   **everywhere** from the GPM archive (both models exist on every cell; GPM truth covers every cell) — a
   data-rich, global fit done at **manual-retrain** time. So the data-scarce, GP/ARD extrapolation problem is
   **one number — fine's weight — on top of an already-solid global base**, not three weights from a handful
   of cells. (The existing `cell_weights.json` from `fit_cell_weights` is the scalar precursor of the
   coarse-vs-clim weight; extend it to per-(cell, horizon).)

**Which learner, by cells walked:** few → **GP / regularised additive** (smooth, low-variance, *extrapolates
with the error bars* that drive the ARD shrinkage); many → **regularised tree ensemble** (finds interactions,
matches the pod's tree evaluator). The unit of data is the **cell**, not the row.

---

## 5. How the gate learns — there is no weight label

You never observe "the correct weight." It's a **latent** quantity learned **end-to-end** by scoring the
*combined* forecast against rain that actually fell:

```
   features(cell), horizon ──► w = gate(…) ──► Q_combined = Σ wᵢ·Qᵢ ──► CRPS( Q_combined , GPM truth )
                                                                              │
                                              update gate params  ◄───────────┘  (Tier 1+2 = f_θ, Tier 3 = u)
```

- **Signal lives in disagreement.** When the models *agree*, an hour teaches the weight nothing. It's pinned
  by hours where they **diverge and you saw the outcome** — fronts, onsets — so effective signal is *sparser*
  than "hours hiked." Lean on regularisation + the global coarse-vs-clim skill prior.
- **Cold start is clean.** No trips → `u = 0`, `w_fine = 0`; the combined forecast = the **global coarse/clim
  blend**, sensible from day zero. Trips then *nudge* a sensible surface, not build one from scratch.

---

## 6. Generalising across cells — partial pooling + ARD

```
   VISITED                         UNVISITED (inherit via weight-relevant features)
   ┌─────────┐                     ┌─────────┐   ┌─────────┐
   │ cell 1  │  trip truth ──┐     │ cell 2  │   │ cell 3  │
   │ u₁ moves│               │     │ u=0     │   │ u=0     │
   └────┬────┘               │     └────┬────┘   └────┬────┘
        │                    ▼          │             │
        └──── refits ──►  f_θ(features) ┴─────────────┘   evaluated at each cell's OWN features
                            │   → similar where close in the RELEVANT (ARD) metric, not raw distance;
                            ▼     shrink w_fine → coarse/clim base as relevant-dissimilarity (uncertainty) grows
```

`f_θ` carries a visited cell's lesson to its look-alikes through their **weight-relevant** features; each gets
its own weight, **similar not copied**. The further a cell is in the *relevant* metric, the more its `w_fine`
shrinks toward the safe coarse/clim base.

---

## 7. The horizon axis — emergent, never hardcoded

The weight is also a function of **lead time**, and that shape is **fit from skill, never typed in.**

```
 w (→fine)
   1 │ fine ███▆▄▂                                  shape EMERGES from measured skill;
     │ coarse/clim ▂▄▆█████████████████████          "fine helps more at short lead"
   0 └────┴────┴────┴────┴────┴────┴──── lead h       is a RESULT, not a rule.
       0    3    6    9   12        24
```

- **No model owns a horizon.** Fine's short-lead dominance, and climatology's rise at long lead / unvisited
  cells, are **outcomes** of the skill the data shows — not assignments. Coarse is *not* excluded from short
  lead; if it has skill there, it keeps weight there.
- **Climatology earns weight where coarse + fine lose skill** (e.g. long lead, data-sparse cells). It is **not
  assigned** the long horizons — it wins them only if it actually beats the others there.
- Horizon is an **input** to the gate. Skill may be **non-smooth** (diurnal cycle; a near-step at the fine
  sensor's timescale) — let the data show it; don't impose smoothness.

---

## 8. Deployment mapping (on-device)

The combined model ships as a **data file on SD**, run by a **streaming tree evaluator** (read all trees, no
early-stop or it breaks the probabilistic heads). The three-way split is *cheaper* on-device than the baked
blend:

| Component | On-device form | Size |
|---|---|---|
| coarse | tree ensemble, streamed from SD one tree at a time | ~10–20 MB |
| climatology | per-cell/month lookup table | kilobytes |
| fine | small regularised model / correction | small |
| weights | `(cell-features, horizon[, season])` → 3 weights lookup | small |

- Pulling climatology out into a lookup is *less* on-device cost than baking it into more trees.
- The pod's `/inputs` columns **are** the model's feature schema; the `manifest.json` schema-hash gate covers
  the whole bundle; mismatch → fall back to the rule-based algorithm (fail-safe). See `pod/docs/architecture.md`.

---

## 9. The field-update loop (sync)

```
   TRIP: pod logs /raw (10-min) + /inputs (exact feature vector) + /pred (hourly forecast)
         ──► SD card ──► laptop ──► VM
                              │
        join /inputs + /pred  ▼  to GPM-Late labels on UTC issue-hour (labels exist only on the VM)
                              │
   ┌──────────────────────────┴───────────────────────────┐
   ▼                                                       ▼
   re-fit the gate (Tiers 1–2) + u(cell) (Tier 3)      tune sensor calibration
   + the fine model, on all visited cells              (CALIBRATION LEADS — see below)
   (blend-CRPS loss, §5)                                from /raw vs Open-Meteo reference
```

- **`/inputs` is the train/serve-skew guard.** Because the pod logs the *exact* vector it consumed, the VM can
  replay it and reproduce the pod's forecast bit-for-bit (native parity test). So any pod-forecast-vs-GPM gap
  is **real model error**, not a logging artefact — the weight refit attributes skill correctly.
- **Calibration must lead.** The coarse model + gate are trained on *simulated* pod signals (motion-sim +
  sensor-sim). If real sensors differ, the prediction-vs-truth stream is contaminated and the refit
  mis-attributes the gap. So: correct constant pressure bias (on-pod LittleFS offset; cancels in tendencies
  anyway), inject measured noise magnitudes into sensor-sim (humidity is the dangerous channel), bench-measure
  the pressure thermal coefficient — *then* the three-way weight refit is trustworthy.
- **Cadence split:** full coarse retrain = a **manual VM job**; the per-sync gate + fine refit is the
  lightweight part. Truth = **GPM-Late** (amount, on UTC issue-hour); see `12-recent-gpm-fine-labels.md`.

---

## 10. Design principles

- **Three first-class models** — coarse, climatology, fine. Climatology is **not** welded into coarse.
- **Nothing is hardcoded to own a horizon** — ownership is a skill-driven outcome, including climatology's.
- **Learned, not hardcoded.** Weights are functions of (features, horizon) fit from skill — never typed-in.
- **Fine is a peer (A)** — emits its own distribution; the *gate* carries all cold-start safety (no anchor).
- **Confidence shrinks along weight-relevant features (ARD)**, not raw distance; seed relevance with domain
  priors; never let raw lat/lon dominate.
- **The meta-model is a situation-aware router** — it conditions on dynamic regime (pressure tendency),
  inter-model disagreement, and terrain, not just location/time. Terrain is the static backbone (fine wins
  where the coarse grid can't resolve topography); directional terrain is **static** (no wind sensor on the pod).
- **Young deployment may over-trust fine to a degree** (decided) — evidence-gating is a *light* shrinkage, not
  a hard gate.
- **Decompose by data availability** — coarse-vs-clim weight fit globally from GPM; only `w_fine` needs visits.
- **All models stay distributional** — none made binary/categorical.
- **Signal lives in disagreement** — regularise accordingly.
- **Don't impose smoothness** — skill may be genuinely bumpy (diurnal / sharp handover).
- **Mind correlated errors** — coarse + fine both lean on pressure; climatology is the uncorrelated term. It's
  why Vincentization risks over-confidence on the pair — one input to the **D2 CRPS bake-off** (decided on
  accuracy, not spread).
- **One calibration, downstream** — a single all-hours recalibration on the combined output (D3), not
  per-model; no wet-conditional split (occurrence + amount calibrated jointly via randomized-PIT).

---

## 11. Status & open questions

- **Built:** coarse (production ensemble) — assessed in **[coarse_model.md](coarse_model.md)**: honest
  true-distribution **CRPSS 0.534 (pure coarse) / 0.514 (coarse + climatology blend — the old welded
  two-way object)**, 100 % of cells positive, flat 0–24 h; key weakness = wet-tail under-coverage (q90 covers
  ~25 % of ≥0.5 mm events — an *information* ceiling: surface P/T/RH lack instability/moisture/uplift; the gap
  the fine model targets). **Available:** climatology. **Not built:** fine, the gate, the sync/refit loop.
- **OPEN decisions:**
  - **D2 — combination rule:** decided on **CRPS accuracy** (not spread/safety) — **bake off** recalibrated
    linear-pool vs recalibrated Vincentization on horizon-weighted CRPS + CI; **default-scaffold linear pool**
    until measured. Hybrid rejected (dominated). Awaiting the bake-off run.
  - **D3 — calibration:** DECIDED — a single **all-hours isotonic/PIT recalibration** of the combined output,
    per horizon (randomized-PIT for the dry mass); no wet-conditional / occurrence split; replaces per-model
    conformal. (Runs once the combined output exists.)
  - **D4 — weight form / granularity:** DECIDED — **sparsemax** over the logits (differentiable a.e., but
    yields *exact-zero* weights → a model can be switched fully off; entmax/α as a tunable fallback if it zeros
    too eagerly). **Not softmax** (no always-on residual; cleaner emergent ownership). Season/time-of-day enter
    as ARD-judged grow-into candidates, not asserted essential.
- **First real task** (before the gate is trusted): the **ARD relevance regression** — regress observed
  best-weight on candidate cell features to find which actually drive fine's edge, and **leave-one-cell-out
  validate** that "similar (in the relevant metric) → similar weight" holds. *If it doesn't generalise, the
  whole scheme can't — worth knowing early.*
- **Data hygiene blocking trust in the coarse numbers:** the clean re-grade on the true-distribution 2024 test
  (the ~5.7 %-vs-14 % wet-rate anomaly) + the `geo` per-cell skill map (the ~½-skill dilution flag). These also
  produce component-1 (the global coarse-vs-clim skill map).
- **Truth sources:** **GPM-Late** (amount, point, recent — the fine-side truth, replacing the removed button);
  MetService 1-min AWS gauge / radar QPE as a licensable upgrade (awaiting `nzsales@` reply). See
  `10-deployment-and-sync.md` §7.

> **References:** seamless nowcast/NWP blending (STEPS, pysteps), quantile aggregation / Vincentization,
> linear opinion pools, mixture-of-experts gating, Quantile Regression Averaging (QRA) + regularised QRA,
> Gaussian-process ARD, hurdle models.
