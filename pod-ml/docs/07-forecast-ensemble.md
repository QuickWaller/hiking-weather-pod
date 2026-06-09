# Forecast ensemble — from binary thresholds to a distributional plume

> **Living doc for the current design phase** — where the new approach is worked out, carrying the learnings
> from the concluded phase 06 ([06-feature-testing.md](06-feature-testing.md)): the motion-sim + pressure
> backbone is strong and well-calibrated, several standard add-ons proved neutral-or-harmful, and the
> binary-threshold framing has outlived its usefulness. **Status: proposed — not yet built or measured.** Every
> *model* change below is a **hypothesis** to validate with bootstrap-CI ablations (the same bar as 06's A–D
> scorecard) before it ships, and to re-check once the back-extension data (≈14 more years, toward GPM IMERG's
> 2000 floor) lands. The *visualisation* and *deployment* choices are firmer but still revisable. Updated as
> decisions and results land.

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
- **Feature additions:** **cyclic hour** (`sin/cos` of RTC hour — `hour_utc` is currently a top-5 feature but
  raw integer 0–23, with a discontinuity at the 23→0 wrap; `month` already gets the cyclic treatment) and
  **dewpoint depression** (`T − Td`, derived on-device by inverting Magnus from sensed RH+temp — a more
  physical saturation signal than raw RH). Both are cheap, parity-safe, and *permanent* wins (encoding /
  information, not data-scarcity patches).
- **No class weighting.** Measured neutral-or-harmful (C3): reweighting doesn't change ranking and *decalibrates*,
  which a Brier/CRPS-judged probabilistic model can't afford. Sensitivity belongs at the **decision threshold**
  on a calibrated model, not in the training loss.

### Immediate next steps (in flight): cyclic hour + dewpoint depression

These two land **first**. They are cheap, parity-safe, *permanent* wins, and they help the existing model too —
so they can be **measured now on the current cache** (a 06-style ablation with bootstrap CIs), without waiting
for the ensemble rebuild. Keep each only if the CI says so, and judge **conditionally** (a feature can be flat
on average yet matter in a niche).

**Cyclic hour.** Add `hour_sin = sin(2π·h/24)`, `hour_cos = cos(2π·h/24)`, mirroring the existing
`month_sin/cos` in `train_motion.add_derived_features`. `hour_utc` is currently a top-5 feature but a raw
integer 0–23 with a discontinuity at the 23→0 wrap; the cyclic pair removes that. Then **measure whether raw
`hour_utc` can be dropped** — today `month` is redundantly double-encoded raw+cyclic; don't repeat that for
hour. Refinement to test later: `hour_utc` is **UTC**, but the diurnal signal is local-solar-time, so a
local-hour version is marginally more physical (NZ's offset is near-constant, so a tree mostly absorbs it). Pod
side: `sin/cos` of the RTC hour — trivial.

**Dewpoint depression.** Add `dewpoint_dep = T − Td`, with `Td` derived by **inverting** the Magnus/Tetens
relation already in `features.rh_from_t_td` (forward = RH from T,Td; we need the inverse, Td from T,RH). It is a
more physical "how close to saturation" signal than raw RH, and fully pod-sensible (AHT10 gives RH+temp → invert
on-device). Start with the value alone; add a trend only if a CI earns it. It belongs in the pod-replicable
vector in `features.py` (alongside `rh`), not the off-cache derived block.

**Parity & tests (both).** As pod-replicable features they fall under the `features.py` parity contract: add
**golden-vector tests** (Python feature build == the eventual C compute, within tolerance), plus a round-trip
check for the dewpoint inverse (`rh_from_t_td(T, T − dewpoint_dep) ≈ RH`). Bump the feature-vector version when
the columns change.

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

The incoming ≈14 years of data reshapes priorities: some ideas only help *because data is scarce now* and will
fade; spend effort accordingly.

| Item | Survives more data? | When |
|---|---|---|
| Cyclic hour, dewpoint depression | ✅ permanent (encoding / information) | **now — in flight** (spec in §2); cheap, help at any size |
| Distributional model + horizon-as-feature | ✅ permanent (coherence + deployment) | design now, build/measure on full data |
| Per-cell climatology blend | ✅ permanent | with the model |
| Monotonic constraints | ⚠️ fades (physics-for-data regulariser) | quick measure now, don't over-tune |
| Statistical sharing for the rare tail | ⚠️ fades | measure: *independent-heavy* vs *shared-heavy* on 25 yr — if they converge it was a bridge |
| Train-on-all-cells | ⚠️ revisit (may plateau sooner in cells) | after data |
| Model capacity (`num_leaves`, `n_estimators`) | 🔼 re-tune up (likely the biggest ceiling-lift) | after data |
| Multi-year test set | ✅ better evaluation (tighter heavy CIs) | after data |

**Data-quality caveat:** the back-extension isn't uniform — GPM IMERG before the core satellite (Feb 2014)
leans on a sparser TRMM-era constellation, so pre-2014 *heavy*-rain truth is weaker, exactly the tail we most
want. Net win (regime/ENSO diversity + event count), but check heavy base rates pre/post-2014 per region before
trusting the extra heavy events.

## 8. Open decisions (deferred)

- **Screen real-estate:** plume as a button-toggled view off the Nijntje colour screen, or dedicated space?
  (The 1.54" colour panel is currently Nijntje + warnings.)
- **Quantity reframe:** keep plain rain *amount*, or later fold in a **wet-cold hazard** target (rain × cold,
  both partly pod-sensible)? The *form* (distributional) is reusable for any quantity, so this can wait.
- **Flash budget:** size bytes/model at a few tree-count/depth settings to confirm the interpreter + SD path
  (and whether `n_estimators` can drop from 300 at little skill cost).
- Centre line confirmed: **mean for rain, median for temp.**
