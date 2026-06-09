# Forecast ensemble — from binary thresholds to a distributional plume

> **Living doc for the current design phase** — where the new approach is worked out, carrying the learnings
> from the concluded phase 06 ([06-feature-testing.md](06-feature-testing.md)): the motion-sim + pressure
> backbone is strong and well-calibrated, several standard add-ons proved neutral-or-harmful, and the
> binary-threshold framing has outlived its usefulness. **Status: in progress.** Every *model* change is a
> **hypothesis** to validate with bootstrap-CI ablations (the same bar as 06's A–D scorecard). Updated as
> decisions and results land.
>
> **What's built (2026-06-09):** `FEATURE_VECTOR_VERSION 3` is in `features.py` and passing 207 tests. The 07
> cache is **complete** on the VM (2861 cells, 2014–2024, k=4 → 1,510,608 endpoints, expanding to ~30.9 M train
> / 3.4 M val / 3.4 M test long-format rows). The trainer (`train_ensemble.py`) reshapes wide→long in one
> float32 pass (only the model-feature + cell/month/year columns) and is **running** (`--from-cache`); v3
> `--ablation` is next. v2 ablation is done — see §v2 for results and correct framing.

## 1. Why change anything

The current model is **15 independent binary classifiers** (3 rain thresholds × 5 horizons), each predicting
"will rain exceed X in the next H hours." It works (every model beats climatology), but the binary framing
fights what the pod is actually for. The reframed requirements:

- **Predictions must carry a probability** — and that probability need *not* come purely from the trained
  model; it can be **blended with the grid cell's own training/validation rain frequency**.
- **Severity** of rain (how much), not just yes/no.
- **Time until** it occurs — at a resolution finer than the current 6 h steps.
- The same, later, for **snow** (derivable from GPM `probabilityLiquidPrecipitation`) and **temperature**.
- Drawn as a **plume / fan chart**, renderable on the pod's 4-colour e-ink.

Binaries can't express severity, give only coarse "time until," and 15 of them have a latent coherence bug
(nothing stops `P(≥7.6) > P(≥0.5)`, which is impossible).

## 2. The model redesign

**Output a distribution of rain *amount*, not a set of yes/no calls.** Per variable (rain first), a small set
of models with **horizon as a feature**:

| Model | Objective | Role |
|---|---|---|
| mean | Tweedie (zero-inflated, log link) | the plume's centre line (`E[rain]`) |
| q10, q25, q75, q90 | LightGBM `quantile` (α = .10/.25/.75/.90) | the band edges |

That is **5 models for rain total** — *fewer* than today's 15 — because horizon is an input, not a separate
model per lead. From the predicted distribution everything else is a **read-off**: any banner threshold is a
CDF lookup (`P(rain ≥ 0.5/2.5/7.6)`, automatically coherent), expected amount is the mean, the heavy-rain tail
is the upper quantiles, and uncertainty is the spread. **Thresholds move from a *training* decision to a
*display* decision** — no binary is ever trained.

Supporting changes (each measured separately):

- **Horizon as a feature** (not 1 model per lead). Enables arbitrary-resolution plumes, shares strength across
  neighbouring leads (a 7 h forecast learns from the 6 h and 8 h data), and — critically for the pod — keeps
  it at *5* models instead of 5 × (number of horizons). This is load-bearing for both skill and flash.
- **Drop the 48 h horizon.** Weakest (BSS 0.099) and the most climatology-like; keeping 0–24 h leaves a
  mutually consistent set for pooling.
- **Feature additions:** see v2 and v3 below.
- **No class weighting.** Measured neutral-or-harmful (C3): reweighting doesn't change ranking and *decalibrates*,
  which a Brier/CRPS-judged probabilistic model can't afford. Sensitivity belongs at the **decision threshold**
  on a calibrated model, not in the training loss.

### Label semantics

`amount_h{H}` = **instantaneous GPM rain rate (mm/hr) at T+H** for H = 0 … 24. The nowcast (H=0) is the
current hour's GPM rate; H>0 is the 1-hour accumulation ending at T+H.

*Why not forward-window max?* `max(rain[T+1..T+H])` is monotone non-decreasing in H by construction — the
plume can only ramp up and plateau, which makes "when does it arrive and clear?" unreadable. Instantaneous rate
gives the bump-and-decay shape that answers the hiker's actual question. It also fits Tweedie cleanly (compound
Poisson-gamma per hour), whereas the max of correlated hours has an ugly distribution.

Two riders noted after the decision:

1. **Skill-vs-horizon check.** The 1-hour ERA5 accumulation is spiky at 18–24 h (single convective hours). After
   training, plot CRPSS vs horizon; if skill degrades visibly past ~18 h consider a short 3-hour trailing mean
   for the long tail only. Don't smooth preemptively — measure first.
2. **Alerting is not exactly recoverable.** `P(rain at any point in window) = P(max > 0)` needs the joint
   distribution across hours; per-hour marginal CDFs under-count by ignoring temporal correlation. A hiker
   reading the plume integrates it by eye and this is good enough. If calibrated alerting ever matters, it needs
   its own coarse-bin head, not a derivation from the plume.

### v2 feature additions — ✅ DONE (`FEATURE_VECTOR_VERSION 2`)

**Cyclic hour.** Replaced raw `hour_utc` (0–23, discontinuous at 23→0) with `hour_sin = sin(2π·h/24)` and
`hour_cos = cos(2π·h/24)`. Pod side: trivial (RTC hour into Magnus). Measurable on the 06 cache without a rebuild
(`--v2-ablation`).

**Dewpoint depression.** Added `dewpoint_dep = T − Td` where `Td` comes from inverting the Magnus/Tetens
relation (`td_from_t_rh` in `features.py`). More physical "how close to saturation" than raw RH, and
pod-sensible (AHT10 T+RH → invert on-device). Belongs in the pod-replicable vector alongside `rh`.

Both are guarded by golden-vector tests and a round-trip check (`rh_from_t_td(T, T − dewpoint_dep) ≈ RH`).

**v2 ablation results (06 binary cache — `outputs/motion/v2_ablation.csv`, n=12 rows):**

| Pair | Δ cyclic_hour | Δ dewpoint_dep | Notes |
|---|---|---|---|
| ge0.5_h6 | +0.0006 | +0.0005 | all CIs overlap |
| ge2.5_h12 | +0.0012 | +0.0008 | all CIs overlap |
| **ge7.6_h6** | −0.0012 | **−0.0024** | yellow flag — niche where dewpoint should help most |
| ge0.5_h24 | +0.0003 | +0.0004 | all CIs overlap |

**Verdict (correct framing):** Both features are **neutral on the 06 binary model, provisional keep.**
- `cyclic_hour` — keep. No regression anywhere; strictly more correct encoding (no phantom 23→0 ordinal gap)
  at negligible pod cost. The ablation's job was only to confirm no regression — it didn't.
- `dewpoint_dep` — **neutral, provisional.** All CIs overlap the baseline. The ge7.6_h6 delta is the yellow
  flag: that is the one case (heavy rain, short horizon) where a moisture-deficit level should theoretically
  help, and it trended the wrong way. Under "judge conditionally on niche cases" that's a flag, not clearance.
  The 06 arena was always a weak test — the level feature without its trend (td_trend_6h) is under-powered.
  The real verdict is the v3 ablation, which tests dewpoint_dep's marginal contribution *given td_trend_6h is
  already in the model* (the correct joint test; see v3 ablation plan below).

### v3 feature additions — ✅ BUILT, cache building (`FEATURE_VECTOR_VERSION 3`)

Cannot be backfilled from the 06 endpoint-only cache — they need the raw signal history at the endpoint, which
the 07 build preserves. Each is a hypothesis; all land in the raw 07 cache and the ablation decides.

| Feature | Computation | Rationale | Expected outcome |
|---|---|---|---|
| `sp_accel_nested` | `sp_rate_3h − sp_rate_6h` | WMO tendency code 8 analog; rate-of-change of pressure slope catches frontal curvature before the slope steepens | Survive |
| `sp_accel_disjoint` | `trailing_slope(sp, 4)[t] − trailing_slope(sp, 4)[t−3]` | Purer 2nd derivative (non-overlapping 3h windows); less collinear with nested | Ablation picks one or both |
| `td_trend_3h` | OLS slope of Td = T−dewpoint_dep over 4 h | Alongside `rh_trend_3h` at 3h they're near-collinear; add both, CI decides | Coin flip vs rh_trend_3h |
| `td_trend_6h` | OLS slope of Td over 7 h | Diurnally stable (RH has a diurnal cycle; Td tracks actual moisture, not relative saturation); captures slow moisture advection | Survive |
| `t2m_trend_6h` | OLS slope of T over 7 h | Cold-front signal | Borderline; likely cut |
| `month_sin/cos` | `sin/cos(2π·month/12)` | Replaces raw `month` — removes the Dec→Jan discontinuity | Permanent encoding win |

**Ablation plan:** train full model once, then drop one feature at a time; bootstrap CI (200 iterations,
resample cells) on ΔCRPSS. Also drop the moisture group `{dewpoint_dep, td_trend_3h, td_trend_6h}` jointly to
separate within-group collinearity from total group contribution.

**Pre-stated keep criteria (fixed before the ablation runs — not post-hoc):**

| Feature | Keep if… | Notes |
|---|---|---|
| `sp_accel_nested` | CI clears baseline OR fast-front conditional positive | if both sp_accel flat: keep nested only (derivable from cache, zero pod cost) |
| `sp_accel_disjoint` | CI clears baseline OR fast-front conditional positive | same second path as nested |
| `td_trend_6h` | CI clears baseline OR moisture-advection conditional positive | primary moisture hypothesis |
| `td_trend_3h` | CI clears baseline only | redundant shorter window — no conditional path |
| `t2m_trend_6h` | CI clears baseline only | weakest prior — cut on flat |
| `dewpoint_dep` | CI clears on drop-one from full model | tests marginal level given td_trend_6h already present — the correct joint test v2 couldn't do |
| `moisture_group` | — (informational) | total group drop shows collinearity impact |

The drop-one for `dewpoint_dep` now tests the right question: does the *level* help given the *slope* is
already in the model? The v2 flat result was expected — the 06 binary model had no slope to condition on.

A feature that's flat on average can still earn its keep in the niche it was designed for — but the niche
criterion is stated above, not decided after seeing the result.

Backward compat: `sp_accel_nested` and `month_sin/cos` are backfillable from the 06 cache (derivable from
cached columns). The signal-history features (`sp_accel_disjoint`, `td_trend_*`, `t2m_trend_6h`) require the
07 cache.

**Parity:** all new features added to `build_features_endpoint` and `build_features_from_signals`. The existing
parity test (`build_features_endpoint` must match `build_features_from_signals().iloc[-1]`) guards all of them.

## 3. Probability = model blended with per-cell climatology

The displayed probability is a **trust-weighted blend**:

```
P_shown = w(cell) · P_model  +  (1 − w(cell)) · P_climatology(cell, month)
```

with `w(cell)` set by how much the model beats climatology *at that cell* on **validation** (never test). High
where the model earns its keep, low where it doesn't. Two payoffs:

- **Structurally fixes the negative-BSS cells** (the ~5% in the Mackenzie/Lindis lee, §6b of [06-feature-testing.md](06-feature-testing.md)):
  `w → 0` there, so the device falls back to local climate and **can never do worse than climatology anywhere**.
- **Guarantees a sensible probability everywhere** — even in barely-seen cells climatology supplies one.

Two baked per-cell lookups ship alongside the model (climatological distribution + trust weight) — both static,
pod-knowable, tens of KB.

### Provenance & validation — where every number on the graph comes from

The graph carries **two different "probabilities,"** and they have different sources. Keeping the data splits
straight is what stops leakage:

| Quantity | Source split | How validated |
|---|---|---|
| `P_model` and the quantile **band edges** (q10/q25/q75/q90) | **training** (the fitted models) | via the blended object below |
| `P_climatology` / the cell's climatological rain-amount distribution | **training** (each cell's own history) | it *is* the BSS baseline |
| `w(cell)` — model-vs-climatology trust | **validation** | BSS-beats-climatology per cell |
| interval **coverage** — are the bands honest? | — | **validation** (recalibrate here), reported on **test** |
| final reported skill & coverage | — | **test (2024)** — untouched until the end |

**The bands come from training, not validation.** The 25–75 / 10–90 edges are direct quantile-model outputs
(`objective='quantile'`, α = .10/.25/.75/.90), each predicting a rain *amount*. The probability is baked into
the **training loss** (the q90 model is penalised for being exceeded more than 10% of the time), so it is a
training-derived number — like `P_model`, *not* the validation-fit weight.

**Bands are validated by coverage, not BSS.** On validation: does the truth fall inside the 10–90 band ~90% of
the time, the 25–75 band ~50%? Check with a coverage/reliability diagram and a **PIT histogram** (Probability
Integral Transform — the quantile each observation lands at should be *uniform*; a U-shape = bands too narrow /
overconfident, a central hump = too wide). If coverage is off, recalibrate **on validation** (refit, or wrap in
**conformal prediction** to rescale interval widths to the nominal level with a finite-sample guarantee), then
report final coverage **once on test**. Caveat: the **upper** quantiles (q90+) carry the heavy tail, are
estimated from few events, and are the noisiest to validate per-cell — the incoming ~14 years matters most here;
the lower quantiles are pinned at 0 (the one-sided fan, §4) and are trivially covered.

**One blended distribution, two read-offs (the unification).** The banner probability and the bands are *not*
separate pipelines — blend the whole predictive distribution in **CDF space**:

```
F_shown(x) = w(cell) · F_model(x)  +  (1 − w(cell)) · F_climatology(x)
```

then read **both** off the single blended CDF: the **bands** are its inverse-CDF at 10/25/75/90, the **banner
probabilities** are `F_shown` evaluated at 0.5 / 2.5 / 7.6 mm/hr. The scalar blend at the top of §3 is just this
CDF blend evaluated at the banner thresholds. Two benefits: the bands inherit the **same climatology fallback**
(so a low-skill cell's *fan*, not just its banner number, retreats to climatology), and blending in CDF space is
**monotone** — it can never produce crossed quantiles.

## 4. The plume / fan visualisation

Rainfall on y, **fine lead time** on x, a centre line with nested **prediction-interval** bands (the
meteorological standard, ECMWF-style):

- centre line — **mean** for rain (see below), median for temperature
- inner band — **25th–75th percentile** (central 50% of outcomes)
- outer band — **10th–90th percentile** (central 80% of outcomes)

These are *prediction intervals* ("where the actual rain will land"), **not** confidence intervals — and so
they are **verifiable**: on validation a true 90% band should contain the observed rain ~90% of the time
(PIT / coverage check). We draw uncertainty we can prove.

**Rain is one-sided; temperature is symmetric — and that's correct, not a bug.** Rain is zero most of the time,
so for most hours `P(rain) < 50%` ⇒ the *median* rainfall is 0 mm and the 10th/25th percentiles are pinned at
zero too. The lower half of the fan collapses onto the floor; only the upper quantiles carry information. So
the rain plume is a **floor at 0 with an upward-ballooning envelope**, and we use the **mean** (always slightly
positive, "how much on average") as the centre line rather than a median stuck at zero. Temperature is smooth
and roughly symmetric, so it gives the textbook two-sided fan with median ≈ mean.

```
mm/hr  (RAIN — one-sided)            °C  (TEMP — symmetric, later)
 8│              ░░░░  10–90         14│        ░░░░
 4│        ░░▒▒▓▓▓▓                  12│    ░▒▒▓▓▓▒▒░
 2│    ░▒▒▓▓████  25–75              10│●━━●━━●━━●━━●  median≈mean
 0│●━━●━━●━━●━━●  mean (~floor)       8│    ░▒▒▓▓▓▒▒░
   now +6 +12 +24h                    6│        ░░░░
```

**4-colour e-ink maps onto the meaning for free:** red = heavy-rain zone fill, yellow = any-rain zone fill,
black = centre line + axes, white = paper / outer band. A filled fan reads well at ~200×200 px and slow
refresh. Snow rides the same machinery as a parallel series, later.

**Rendering is decoupled; only the forecast *contract* is shared.** Three contexts draw the plume and share
**no rendering code** — only the predicted-quantile/mean structure:

- **pod-ml reports** (this repo) — matplotlib figures for *model evaluation* (calibration, example
  plume-vs-truth), on a dev machine.
- **cyberdeck** (CM5, Python) — the rich *live* forecast for the hiker at camp.
- **pod** (RP2350, C / Adafruit GFX) — the compressed 4-colour e-ink fan.

Each renders at its own fidelity and stack from the same numbers. Bonus: pod-ml can render a **mock pod-plume**
(matplotlib mimicking the 4-colour fan) as a report figure, to validate the on-device design against real test
data *before any firmware exists*.

## 5. Evaluation changes

- **Primary metric → CRPS** (Continuous Ranked Probability Score — the proper score for a full predictive
  distribution; it is Brier integrated over all thresholds and reduces to Brier for one threshold).
- **Keep thresholded BSS** on the read-offs (`P(≥0.5/2.5/7.6)`) for continuity with all existing results.
- **Interval calibration** check (coverage / PIT histogram) to prove the bands are honest.

## 6. Pod replicability & deployment

The parity discipline from `features.py` ("the SPEC the C++ must reproduce bit-for-bit") extends cleanly:

- **Features** stay pod-replicable (cyclic hour from RTC; dewpoint depression from sensed RH+temp; horizon is
  just a number the pod plugs in). Add golden-vector tests for the two new features.
- **Models** export via the existing LightGBM path. Inference is identical regardless of training objective
  (sum leaf values over trees + link); quantiles are identity-link, the Tweedie mean uses `exp()` (one line if
  the exporter doesn't apply it). Add a Python-vs-C model-parity test.
- **Anti-crossing:** sort the 5 quantile outputs per lead (trivial).
- **Compute is a non-issue** — 5 models × ~24 leads × ~300 trees ≈ tens of thousands of tiny traversals per
  redraw, i.e. milliseconds on the 150 MHz dual core.
- **Flash is the watch-item, and the answer is a compact tree-array interpreter, not m2cgen.** m2cgen emits
  *unrolled `if/else` code* that must live in firmware flash; five 300-tree models could be several MB. A small
  fixed interpreter (in flash) walking **tree data** turns the model into *data* — which can live on the **SD
  card** the pod already has. Bonus: the model becomes a **swappable file** (retrain on the deck → copy to SD →
  no reflash). With ~520 KB RAM you **stream model-by-model from SD** (load one model's trees, run all its lead
  queries, move on) — fine at the redraw cadence, would only bite in a tight loop.
- **Recompute / redraw cadence ≈ every 30 min**, decoupled from the 5-min sensor-log cycle. The forecast
  doesn't change minute-to-minute, e-ink refreshes are slow and finite-lifetime, and 30 min matches GPM's
  half-hourly resolution. Each redraw rebuilds the whole fan from the latest pressure history, so the plume
  updates continuously through the trip.

## 7. Sequencing — permanent wins vs scarcity bridges vs re-tune

| Item | Survives more data? | Status |
|---|---|---|
| Cyclic hour, dewpoint depression | ✅ permanent (encoding / information) | ✅ Done — `FEATURE_VECTOR_VERSION 2` |
| v3 pressure acceleration + Td trends | ✅ permanent (physics signal) | ✅ Built — ablation decides which survive |
| Distributional model + horizon-as-feature | ✅ permanent (coherence + deployment) | ✅ Trainer written, cache building |
| Per-cell climatology blend | ✅ permanent | ✅ Implemented in `train_ensemble.py` |
| Training range 2014–2022 | ✅ more ENSO diversity | ✅ Confirmed — ERA5 + GPM both complete for 2014 |
| Monotonic constraints | ⚠️ fades (physics-for-data regulariser) | Measure after ablation |
| Statistical sharing for the rare tail | ⚠️ fades | Measure: *independent-heavy* vs *shared-heavy* — if they converge it was a scarcity bridge |
| Model capacity re-tune | 🔼 re-tune up (likely the biggest ceiling-lift) | After ablation settles feature set |
| Multi-year test set | ✅ better evaluation (tighter heavy CIs) | Revisit after 2025 data lands |

**Current trainer hyperparameters** (in `fit_ensemble`):
- `n_estimators=3000, learning_rate=0.02, num_leaves=127` — capacity matched to ~31 M long-format train rows
  (1.24 M train endpoints × 25 horizons)
- `min_child_samples=50` — prevents leaf-level overfit on the sparse heavy-rain tail
- `reg_lambda=0.5` — L2 regularisation; keeps quantile heads from crossing under extrapolation
- Early stopping patience=100 on the 2023 val set (one year, ~3.4 M long rows)
- Tweedie power=1.5 (compound Poisson-gamma midpoint for NZ hourly rain amounts)

**Data-quality note:** GPM IMERG before the core satellite era (Feb 2014) uses a sparser TRMM-era constellation.
Pre-2014 heavy-rain truth is weaker, exactly where we most care. 2014 is included (net win for ENSO diversity
and event count) but check heavy base rates pre/post-2014 per region before trusting the extra heavy events.

## 8. Open decisions (deferred)

- **Screen real-estate:** plume as a button-toggled view off the Nijntje colour screen, or dedicated space?
  (The 1.54" colour panel is currently Nijntje + warnings.)
- **Quantity reframe:** keep plain rain *amount*, or later fold in a **wet-cold hazard** target (rain × cold,
  both partly pod-sensible)? The *form* (distributional) is reusable for any quantity, so this can wait.
- **Flash budget:** size bytes/model at the chosen tree depth to confirm the interpreter + SD path. Early stopping
  means the actual tree count will be determined empirically (patience=100 on 2023 val); profile after the first
  training run.
- **Skill-vs-horizon smoothing:** check CRPSS by horizon after the first training run; smooth the 18–24 h tail
  with a 3-hour trailing mean only if data shows visible degradation (do not assume).
- **Memory scaling for a larger cache (revisit before growing the data):** the trainer builds one global
  long frame (~38 M rows at the current 1.5 M endpoints) then slices it into train/val/test. Fine at this size
  (~11 GB peak, leaning on swap), but the slice briefly holds the global frame **and** its three splits at once
  (~2×) — the tightest point of the run. Doubling the row count (higher `--k`, more cells, or a second variable
  like snow) roughly doubles that spike → won't fit. Fix when needed: go back to **per-split expansion**
  (`expand_split_long` — filter endpoints to one split *then* expand, so peak RAM tracks the largest single
  split, not the whole dataset ×2). Removed 2026-06-09 for simplicity; recover it from git history. Especially
  relevant if the first full-scale `--from-cache` run OOMs on the fit.
- Centre line confirmed: **mean for rain, median for temp.**

## 9. Run sequence

```bash
# Build the 07 dataset (complete on VM — 1,510,608 endpoints, 2861 cells):
python -m podml.train_ensemble --build-cache --all-cells --k 4 --years 2014-2024

# Train + evaluate (run once cache finishes):
python -m podml.train_ensemble --from-cache > ~/ensemble_train.log 2>&1

# v3 feature ablation (run after --from-cache completes):
python -m podml.train_ensemble --ablation > ~/ensemble_ablation.log 2>&1

# v2 feature ablation on 06 cache (can run independently now):
python -m podml.train_motion --v2-ablation
```

Key outputs in `outputs/ensemble/`:

| File | What it shows |
|---|---|
| `metrics_overall.csv` | CRPSS + coverage per horizon (the skill-vs-horizon curve) |
| `pit_histogram.csv` | PIT calibration check by horizon (uniform = honest bands) |
| `coverage.csv` | Empirical 10–90 and 25–75 coverage vs 80% / 50% targets |
| `cell_weights.json` | Per-cell trust weights (baked into device lookup) |
| `importance.csv` | Feature gain per model head |
| `v3_ablation.csv` | Per-feature ΔCRPSS + 95% CI + `ci_survives` + `has_conditional_path` + `verdict`; moisture_group row is informational |
| `v3_conditional.csv` | Feature skill on fast-front and moisture-advection subsets |
