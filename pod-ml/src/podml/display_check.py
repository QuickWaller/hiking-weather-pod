"""Phase-08 display calibration check — READ-ONLY, MANUAL, NON-DESTRUCTIVE.

Answers the phase-08 go/no-go question (docs/08-rain-display.md §6): *are the trained
probabilities calibrated enough to drive a height+hue exceedance-probability rain plume?*
— without retraining, rebuilding the cache, editing the trainer, or overwriting any
phase-07 output.

What it does
------------
1. Loads the saved phase-07 boosters (`outputs/ensemble/models/*.txt`) read-only.
2. On the existing held-out test year, reads off exceedance probabilities:
     - P(rain >= 0.5)  — from the dedicated binary head if present, else the Tweedie CDF.
     - P(rain >= 2.5)  — from the Tweedie predictive CDF (the calibrated mean head).
     - P(rain >= 7.6)  — same.
3. Draws per-threshold **reliability curves** (predicted vs observed) — the go/no-go gate.
4. Draws a **side-by-side comparison**: the existing phase-07 quantile fan (left) next to the
   proposed height+hue plume (right), on the same endpoints — so the old way of doing things
   stays fully viewable.

It NEVER fires automatically and is not imported by the trainer. Run it by hand:

    python -m podml.display_check reliability [--n-cells 150]   # gate + comparison
    python -m podml.display_check plumes                        # cheap: comparison only

All new artifacts go to NEW paths and nothing existing is overwritten:
    outputs/ensemble/display_check/   (metrics csv, phi.json)
    docs/figures/display/             (reliability.png, plume_compare.png)

The Tweedie survival function below assumes the trainer's compound Poisson-gamma power
(p = 1.5); the dispersion phi is estimated once on the validation year (test labels are not
used to build the probabilities).
"""

from __future__ import annotations

import argparse
import json

import matplotlib
matplotlib.use("Agg")  # non-interactive: writes files, never opens a window
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import lightgbm as lgb
import joblib
from scipy.stats import gamma, poisson
from sklearn.isotonic import IsotonicRegression

from podml.config import ROOT
from podml.train_ensemble import (
    OUT, CACHE_DIR, ENSEMBLE_FEATURES, WET_THRESHOLD_MM,
    load_cache, to_long_format, predict, blend, load_ensemble_state,
    crps_from_quantiles, _clim_preds,
)
from podml.train_motion import VAL_YEAR, TEST_YEAR, ensure_model_features

DISPLAY_OUT = OUT / "display_check"
FIG_OUT = ROOT / "docs" / "figures" / "display"
PLUMES_JSON = OUT / "plumes.json"

THRESHOLDS = [0.5, 2.5, 7.6]          # mm/hr — light / moderate / heavy banner levels
DISPLAY_HORIZONS = [0, 6, 12, 24]     # leads to draw on the reliability curves
TWEEDIE_POWER = 1.5                   # must match fit_ensemble's tweedie_variance_power


# ───────────────────────────────── Tweedie predictive CDF ────────────────────────────────

def estimate_phi(y: np.ndarray, mu: np.ndarray, p: float = TWEEDIE_POWER) -> float:
    """Pearson method-of-moments dispersion: phi = mean[ (y-mu)^2 / mu^p ].

    Estimated on the validation year so the test labels never enter the probabilities.
    """
    mu = np.maximum(np.asarray(mu, float), 1e-6)
    phi = float(np.mean((np.asarray(y, float) - mu) ** 2 / mu ** p))
    return max(phi, 1e-3)


def tweedie_sf(x: float, mu: np.ndarray, phi: float, p: float = TWEEDIE_POWER) -> np.ndarray:
    """Survival function P(Y >= x), x > 0, for a Tweedie compound Poisson-gamma.

    Y = sum of N iid Gamma(shape=alpha, scale=theta), N ~ Poisson(lambda), N >= 1.
    P(Y >= x) = sum_{n>=1} Poisson(n; lambda) * GammaSF(x; n*alpha, theta).
    Vectorised over mu; the Poisson series is truncated well past lambda's tail.
    """
    mu = np.maximum(np.asarray(mu, float), 1e-6)
    lam = mu ** (2 - p) / (phi * (2 - p))
    alpha = (2 - p) / (p - 1)
    theta = phi * (p - 1) * mu ** (p - 1)
    lmax = float(np.max(lam))
    n_max = int(min(400, lmax + 10 * np.sqrt(lmax) + 20))
    sf = np.zeros_like(mu, dtype=float)
    for n in range(1, n_max + 1):
        sf += poisson.pmf(n, lam) * gamma.sf(x, a=n * alpha, scale=theta)
    return np.clip(sf, 0.0, 1.0)


def load_binary_head() -> lgb.Booster | None:
    """The dedicated P(rain>0.5) head, if this run trained it (`--binary`). Read-only."""
    p = OUT / "models" / "binary.txt"
    return lgb.Booster(model_file=str(p)) if p.exists() else None


def apply_iso(iso: dict, t: float, h_arr: np.ndarray, p_arr: np.ndarray) -> np.ndarray:
    """Apply the per-(threshold, horizon) isotonic recalibration map (§6a) to probabilities.

    Monotone, fitted on validation; preserves ranking and only stretches the probability
    axis onto the diagonal. Horizons with no fitted map (too little val data) pass through.
    """
    out = np.asarray(p_arr, float).copy()
    h_arr = np.asarray(h_arr)
    for h in np.unique(h_arr):
        ir = iso.get((float(t), int(h)))
        if ir is not None:
            mm = h_arr == h
            out[mm] = ir.transform(out[mm])
    return out


# ───────────────────────────────── reliability (the gate) ────────────────────────────────

def reliability_curve(pred: np.ndarray, obs: np.ndarray, n_bins: int = 10):
    """Return (mean_pred, mean_obs, count) per probability bin."""
    edges = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.clip(np.digitize(pred, edges) - 1, 0, n_bins - 1)
    rows = []
    for b in range(n_bins):
        m = idx == b
        if m.any():
            rows.append((float(pred[m].mean()), float(obs[m].mean()), int(m.sum())))
    return rows


def brier_and_bss(pred: np.ndarray, obs: np.ndarray):
    base = float(obs.mean())
    b_model = float(np.mean((pred - obs) ** 2))
    b_clim = float(np.mean((base - obs) ** 2))
    bss = 1.0 - b_model / b_clim if b_clim > 0 else float("nan")
    return b_model, bss, base


def run_reliability(n_cells: int | None) -> tuple[float, dict]:
    """Load models + test split, read off exceedance probabilities, draw the gate.

    Returns (phi, iso) where iso is the per-(threshold, horizon) isotonic recalibration map.
    """
    DISPLAY_OUT.mkdir(parents=True, exist_ok=True)
    FIG_OUT.mkdir(parents=True, exist_ok=True)

    models, clim_table, global_stats, weights = load_ensemble_state(OUT)
    if "mean" not in models:
        raise SystemExit("No 'mean' (Tweedie) booster in outputs/ensemble/models — "
                         "is the run finished and saved?")
    binary_head = load_binary_head()
    print(f"heads found: {sorted(models)}"
          f"{' + binary' if binary_head is not None else ' (no binary head this run)'}", flush=True)

    X, y, meta = load_cache(CACHE_DIR)
    ensure_model_features(X, y, meta)
    if n_cells is not None:
        rng = np.random.default_rng(0)
        keep = set(rng.choice(meta["cell"].unique(),
                              size=min(n_cells, meta["cell"].nunique()), replace=False))
        m = meta["cell"].isin(keep).to_numpy()
        X, y, meta = X[m].reset_index(drop=True), y[m].reset_index(drop=True), meta[m].reset_index(drop=True)

    feats = [f for f in ENSEMBLE_FEATURES if f == "horizon_h" or f in X.columns]
    meta_cols = ["cell", "month", "year"] + (["time"] if "time" in meta.columns else [])
    X_long, y_long, meta_long = to_long_format(
        X[[f for f in feats if f != "horizon_h"]], y, meta[meta_cols])
    del X, y, meta
    years = meta_long["year"].to_numpy()

    def split(mask):
        return (X_long[mask].reset_index(drop=True),
                y_long[mask].to_numpy(),
                meta_long[mask].reset_index(drop=True))

    X_vl, y_vl, meta_vl = split(years == VAL_YEAR)
    X_te, y_te, meta_te = split(years == TEST_YEAR)
    print(f"rows: val={len(X_vl):,} test={len(X_te):,}", flush=True)

    # Blended mean (what the device shows) on val → phi; on test → probabilities.
    mu_vl = blend(predict(models, X_vl, feats), clim_table, global_stats, weights, meta_vl)["mean"]
    mu_te = blend(predict(models, X_te, feats), clim_table, global_stats, weights, meta_te)["mean"]
    phi = estimate_phi(y_vl, mu_vl)
    print(f"Tweedie dispersion phi (estimated on val) = {phi:.3f}", flush=True)
    (DISPLAY_OUT / "phi.json").write_text(json.dumps({"phi": phi, "power": TWEEDIE_POWER}))

    h_te = meta_te["horizon_h"].to_numpy()

    h_vl = meta_vl["horizon_h"].to_numpy()

    # raw Tweedie-CDF exceedance probs on val (to fit recalibration) and test
    p_exc_te = {t: tweedie_sf(t, mu_te, phi) for t in THRESHOLDS}
    p_exc_vl = {t: tweedie_sf(t, mu_vl, phi) for t in THRESHOLDS}

    # §6a recalibration: per-(threshold, horizon) isotonic map fitted on VAL, applied to test.
    iso: dict[tuple[float, int], IsotonicRegression] = {}
    for t in THRESHOLDS:
        for h in np.unique(h_vl):
            m = h_vl == h
            if m.sum() < 100:
                continue
            ir = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            ir.fit(p_exc_vl[t][m], (y_vl[m] > t).astype(float))
            iso[(float(t), int(h))] = ir
    joblib.dump(iso, DISPLAY_OUT / "iso.joblib")   # so storm/geo modes can recalibrate too
    p_recal_te = {t: apply_iso(iso, t, h_te, p_exc_te[t]) for t in THRESHOLDS}

    fig, axes = plt.subplots(1, len(THRESHOLDS), figsize=(4.4 * len(THRESHOLDS), 4.2))
    metric_rows = []
    for ax, t in zip(axes, THRESHOLDS):
        ax.plot([0, 1], [0, 1], "k--", lw=1, alpha=0.6, label="perfect")
        for h in DISPLAY_HORIZONS:
            hm = h_te == h
            if hm.sum() < 50:
                continue
            obs = (y_te[hm] > t).astype(float)
            raw = p_exc_te[t][hm]      # naive Tweedie-CDF read-off
            rec = p_recal_te[t][hm]    # isotonic-recalibrated
            col = f"C{DISPLAY_HORIZONS.index(h)}"
            rr = reliability_curve(raw, obs)
            if rr:
                mp, mo, _ = zip(*rr)
                ax.plot(mp, mo, ls=":", lw=1, alpha=0.45, color=col)
            rc = reliability_curve(rec, obs)
            if rc:
                mp, mo, _ = zip(*rc)
                ax.plot(mp, mo, marker="o", ms=3, lw=1.3, color=col, label=f"+{h}h")
            for src, pred in (("tweedie_raw", raw), ("tweedie_isotonic", rec)):
                bm, bss, base = brier_and_bss(pred, obs)
                metric_rows.append({"threshold": t, "horizon": h, "source": src,
                                    "brier": bm, "bss": bss, "base_rate": base, "n": int(hm.sum())})
        ax.set_title(f"P(rain ≥ {t} mm/hr)")
        ax.set_xlabel("forecast probability")
        ax.set_ylabel("observed frequency")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.legend(fontsize=7, title="solid=recal · dotted=raw")
    fig.suptitle("Phase-08 reliability gate — raw (dotted) vs isotonic-recalibrated (solid)", y=1.02)
    fig.tight_layout()
    fig.savefig(FIG_OUT / "reliability.png", dpi=130, bbox_inches="tight")
    plt.close(fig)

    pd.DataFrame(metric_rows).to_csv(DISPLAY_OUT / "reliability_metrics.csv", index=False)
    print(f"wrote {FIG_OUT / 'reliability.png'} and {DISPLAY_OUT / 'reliability_metrics.csv'}", flush=True)
    return phi, iso


# ─────────────────────────── side-by-side plume comparison (cheap) ───────────────────────

def _load_phi() -> float:
    p = DISPLAY_OUT / "phi.json"
    if p.exists():
        return float(json.loads(p.read_text())["phi"])
    return None  # type: ignore[return-value]


def run_plume_compare(phi: float | None = None, iso: dict | None = None) -> None:
    """Old quantile fan vs new height+hue plume on the same endpoints, from plumes.json (cheap).

    If `iso` (the §6a recalibration map) is supplied, the new plume's probabilities are recalibrated.
    """
    FIG_OUT.mkdir(parents=True, exist_ok=True)
    if not PLUMES_JSON.exists():
        print(f"  {PLUMES_JSON} not found — re-run training with --save-plumes to get example "
              f"endpoints, or run the 'reliability' mode. Skipping comparison.", flush=True)
        return
    entries = json.loads(PLUMES_JSON.read_text())
    if not entries:
        print("  plumes.json empty — skipping.", flush=True)
        return

    if phi is None:
        phi = _load_phi()
    if phi is None:
        # crude fallback: estimate phi from the example endpoints themselves
        ys = np.concatenate([np.asarray(e["y_obs"], float) for e in entries])
        mus = np.concatenate([np.asarray(e["blended"]["mean"], float) for e in entries])
        phi = estimate_phi(ys, mus)
        print(f"  phi.json absent — estimated phi={phi:.3f} from example endpoints (rough)", flush=True)

    # pick 4 endpoints spanning dry→heavy by peak observed rain
    entries = sorted(entries, key=lambda e: max(e["y_obs"]))
    pick = [entries[int(q * (len(entries) - 1))] for q in (0.1, 0.5, 0.8, 0.99)]

    cmap = plt.get_cmap("YlOrRd")
    fig, axes = plt.subplots(len(pick), 2, figsize=(11, 2.6 * len(pick)), squeeze=False)
    for r, e in enumerate(pick):
        h = np.asarray(e["horizons"], float)
        yobs = np.asarray(e["y_obs"], float)
        b = e["blended"]
        order = np.argsort(h)
        h = h[order]
        yobs = yobs[order]
        q10, q25, q75, q90, mean = (np.asarray(b[k], float)[order]
                                    for k in ("q10", "q25", "q75", "q90", "mean"))

        # LEFT: the existing phase-07 quantile fan (amount on y)
        axL = axes[r][0]
        axL.fill_between(h, q10, q90, color="#cfe3f5", label="10–90%")
        axL.fill_between(h, q25, q75, color="#7fb3e0", label="25–75%")
        axL.plot(h, mean, "k-", lw=1.4, label="mean")
        axL.plot(h, yobs, "o", color="crimson", ms=3, label="observed")
        axL.set_ylabel("rain (mm/hr)")
        if r == 0:
            axL.set_title("OLD — quantile fan (phase 07)")
            axL.legend(fontsize=7)

        # RIGHT: the proposed height+hue plume (probability on y, hue = severity if wet)
        axR = axes[r][1]
        p_rain = tweedie_sf(WET_THRESHOLD_MM, mean, phi)
        p_mod = tweedie_sf(2.5, mean, phi)
        if iso is not None:
            p_rain = apply_iso(iso, WET_THRESHOLD_MM, h.astype(int), p_rain)
            p_mod = apply_iso(iso, 2.5, h.astype(int), p_mod)
        heaviness = np.clip(p_mod / np.maximum(p_rain, 1e-6), 0.0, 1.0)  # P(≥2.5 | rains)
        axR.bar(h, p_rain, width=0.9, color=cmap(0.25 + 0.75 * heaviness))
        # mark hours that actually rained
        rained = yobs > WET_THRESHOLD_MM
        if rained.any():
            axR.plot(h[rained], np.full(rained.sum(), 1.02), "v", color="crimson", ms=4)
        axR.set_ylim(0, 1.08)
        axR.set_ylabel("P(rain ≥ 0.5)")
        if r == 0:
            tag = "recalibrated" if iso is not None else "raw read-off"
            axR.set_title(f"NEW — height = P(rain), hue = severity if wet ({tag})")
        for ax in (axL, axR):
            ax.set_xlabel("lead time (h)" if r == len(pick) - 1 else "")
    fig.suptitle("Phase-08 rain display — old fan vs new probability plume (same endpoints)", y=1.01)
    fig.tight_layout()
    fig.savefig(FIG_OUT / "plume_compare.png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {FIG_OUT / 'plume_compare.png'} ({len(pick)} endpoints)", flush=True)


# ───────────────────────────────────────── CLI ───────────────────────────────────────────

def load_iso() -> dict | None:
    p = DISPLAY_OUT / "iso.joblib"
    return joblib.load(p) if p.exists() else None


def _cell_to_latlon(cell_id: str) -> tuple[float, float]:
    """'g-43p1_171p7' → (-43.1, 171.7)."""
    lat_s, lon_s = cell_id[1:].split("_")
    return float(lat_s.replace("p", ".")), float(lon_s.replace("p", "."))


def _season_of(m: int) -> str:
    return {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM",
            6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON"}[int(m)]


def _region_of(lat: float, lon: float) -> str:
    """Coarse NZ regions that capture the orographic story."""
    if lat > -41.5:
        return "North Is"
    return "SI West" if lon < 170.5 else "SI East (lee)"


def _load_test_long():
    """Load the 2024 test cache (only) and long-expand it. Returns (Xl, yv, ml, feats)."""
    X = pd.read_parquet(CACHE_DIR / "X_2024.parquet")
    y = pd.read_parquet(CACHE_DIR / "y_2024.parquet")
    meta = pd.read_parquet(CACHE_DIR / "meta_2024.parquet")
    ensure_model_features(X, y, meta)
    feats = [f for f in ENSEMBLE_FEATURES if f == "horizon_h" or f in X.columns]
    meta_cols = ["cell", "month", "year"] + (["time"] if "time" in meta.columns else [])
    Xl, yl, ml = to_long_format(X[[f for f in feats if f != "horizon_h"]], y, meta[meta_cols])
    return Xl, yl.to_numpy(), ml, feats


# ─────────────────────────── lead-time reliability (the set-wide story) ──────────────────

LEADS = [1, 2, 3, 4, 6, 8, 12, 24]
EVENT_THRESHOLDS = [0.5, 2.5, 7.6]
FIXED_FAR = 0.20   # hold false-alarm rate constant so leads/strata are comparable


def run_leadtime() -> None:
    """How far ahead does the model warn for real rain events — stratified by season/region/intensity?

    Probability of detection (POD = recall of rain events) at each lead, holding the false-alarm
    rate fixed at 10% so leads and strata are directly comparable. POD is rank-based, so the
    (monotone) recalibration does not affect it — this needs only the models + the 2024 test cache.
    """
    DISPLAY_OUT.mkdir(parents=True, exist_ok=True)
    FIG_OUT.mkdir(parents=True, exist_ok=True)
    models, clim_table, global_stats, weights = load_ensemble_state(OUT)
    Xl, yv, ml, feats = _load_test_long()
    print(f"leadtime: {len(yv):,} test rows, {ml['cell'].nunique()} cells", flush=True)

    score = blend(predict(models, Xl, feats), clim_table, global_stats, weights, ml)["mean"]
    h = ml["horizon_h"].to_numpy()
    if "time" in ml.columns:
        vt = pd.to_datetime(ml["time"].to_numpy()) + pd.to_timedelta(h, unit="h")
        vmonth = vt.month
    else:
        vmonth = ml["month"].to_numpy()
    season = np.array([_season_of(m) for m in np.asarray(vmonth)])
    cells = ml["cell"].to_numpy()
    reg_lut = {c: _region_of(*_cell_to_latlon(c)) for c in pd.unique(cells)}
    region = np.array([reg_lut[c] for c in cells])

    rows = []
    for t in EVENT_THRESHOLDS:
        ev_all = yv >= t
        dims = [("overall", np.full(len(yv), "all")), ("season", season), ("region", region)]
        for dim, labels in dims:
            for strat in np.unique(labels):
                sm = labels == strat
                for L in LEADS:
                    m = sm & (h == L)
                    ev = m & ev_all
                    nev = m & ~ev_all
                    ne, nn = int(ev.sum()), int(nev.sum())
                    if ne < 20 or nn < 50:
                        rows.append((t, dim, strat, L, np.nan, ne))
                        continue
                    s_star = np.quantile(score[nev], 1 - FIXED_FAR)   # FAR = 10%
                    pod = float(np.mean(score[ev] >= s_star))
                    rows.append((t, dim, strat, L, pod, ne))
    df = pd.DataFrame(rows, columns=["threshold", "dim", "stratum", "lead", "pod_at_far10", "n_events"])
    df.to_csv(DISPLAY_OUT / "leadtime.csv", index=False)

    def series(dim, strat, t):
        s = df[(df["dim"] == dim) & (df["stratum"] == strat) & (df["threshold"] == t)].sort_values("lead")
        return s["lead"].to_numpy(), s["pod_at_far10"].to_numpy()

    fig, axes = plt.subplots(1, 3, figsize=(15, 4.4), sharey=True)
    # (a) overall, by intensity threshold
    for t in EVENT_THRESHOLDS:
        x, p = series("overall", "all", t)
        axes[0].plot(x, p, "-o", ms=4, label=f"≥{t} mm/hr")
    axes[0].set_title("Overall — by rain intensity")
    axes[0].legend(fontsize=8, title="event")
    # (b) by season (any rain ≥0.5)
    for s in ["DJF", "MAM", "JJA", "SON"]:
        x, p = series("season", s, 0.5)
        if len(x):
            axes[1].plot(x, p, "-o", ms=4, label=s)
    axes[1].set_title("By season — any rain (≥0.5)")
    axes[1].legend(fontsize=8)
    # (c) by region (any rain ≥0.5)
    for rg in ["North Is", "SI West", "SI East (lee)"]:
        x, p = series("region", rg, 0.5)
        if len(x):
            axes[2].plot(x, p, "-o", ms=4, label=rg)
    axes[2].set_title("By region — any rain (≥0.5)")
    axes[2].legend(fontsize=8)
    for ax in axes:
        ax.axhline(0.5, color="grey", ls=":", lw=1)
        ax.set_xlabel("lead time (h before event)")
        ax.set_ylim(0, 1)
    axes[0].set_ylabel(f"POD (recall of events) at {int(FIXED_FAR*100)}% false-alarm rate")
    fig.suptitle("Lead-time reliability — fraction of real rain events the model flags X hours ahead", y=1.02)
    fig.tight_layout()
    fig.savefig(FIG_OUT / "leadtime.png", dpi=140, bbox_inches="tight")
    plt.close(fig)

    # printed summary
    print(f"\n=== POD at {int(FIXED_FAR*100)}% FAR — ANY RAIN (≥0.5), overall ===", flush=True)
    x, p = series("overall", "all", 0.5)
    for L, pp in zip(x, p):
        print(f"  {int(L):2d}h ahead: {pp*100:4.0f}% of events flagged", flush=True)
    print("\n=== POD at +6h by stratum (≥0.5) ===", flush=True)
    for dim in ("season", "region"):
        for strat in sorted(df[df["dim"] == dim]["stratum"].unique()):
            sub = df[(df["dim"] == dim) & (df["stratum"] == strat) &
                     (df["threshold"] == 0.5) & (df["lead"] == 6)]
            if len(sub) and np.isfinite(sub["pod_at_far10"].iloc[0]):
                print(f"  {dim:7s} {strat:15s}: {sub['pod_at_far10'].iloc[0]*100:4.0f}%", flush=True)
    print(f"\nwrote {FIG_OUT / 'leadtime.png'} and {DISPLAY_OUT / 'leadtime.csv'}", flush=True)


# ─────────────────────────── geography: per-cell skill map ───────────────────────────────

def run_geo() -> None:
    """Per-cell CRPSS over the 2024 test year — which regions are skilful vs worse-than-climatology."""
    DISPLAY_OUT.mkdir(parents=True, exist_ok=True)
    FIG_OUT.mkdir(parents=True, exist_ok=True)
    models, clim_table, global_stats, weights = load_ensemble_state(OUT)
    Xl, yv, ml, feats = _load_test_long()
    blended = blend(predict(models, Xl, feats), clim_table, global_stats, weights, ml)
    crps_m = crps_from_quantiles(yv, blended)
    crps_c = np.abs(yv - _clim_preds(clim_table, global_stats, ml)["mean"])
    g = (pd.DataFrame({"cell": ml["cell"].to_numpy(), "cm": crps_m, "cc": crps_c})
         .groupby("cell").agg(cm=("cm", "mean"), cc=("cc", "mean"), n=("cm", "size")))
    g["crpss"] = 1 - g["cm"] / g["cc"].where(g["cc"] > 0)
    g = g.dropna(subset=["crpss"])
    latlon = [_cell_to_latlon(c) for c in g.index]
    g["lat"] = [a for a, _ in latlon]
    g["lon"] = [b for _, b in latlon]
    g.to_csv(DISPLAY_OUT / "geo_crpss.csv")

    fig, ax = plt.subplots(figsize=(7, 8.5))
    sc = ax.scatter(g["lon"], g["lat"], c=g["crpss"].clip(-0.5, 0.5),
                    cmap="RdBu", s=16, vmin=-0.5, vmax=0.5)
    ax.set_aspect(1 / np.cos(np.deg2rad(41)))
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")
    ax.set_title(f"Per-cell CRPSS — 2024 test ({len(g)} cells)\nblue = beats climatology, red = worse")
    fig.colorbar(sc, ax=ax, label="CRPSS", fraction=0.04)
    fig.tight_layout()
    fig.savefig(FIG_OUT / "geo_skill.png", dpi=140, bbox_inches="tight")
    plt.close(fig)

    gs = g.sort_values("crpss")
    print(f"\nmedian per-cell CRPSS = {g['crpss'].median():.3f} | "
          f"{(g['crpss'] > 0).mean()*100:.0f}% of cells positive", flush=True)
    print("=== 8 WORST cells ===", flush=True)
    print(gs[["lat", "lon", "crpss", "n"]].head(8).round(3).to_string(), flush=True)
    print("=== 8 BEST cells ===", flush=True)
    print(gs[["lat", "lon", "crpss", "n"]].tail(8).round(3).to_string(), flush=True)
    print(f"wrote {FIG_OUT / 'geo_skill.png'} and {DISPLAY_OUT / 'geo_crpss.csv'}", flush=True)


# ─────────────────────────── storm-approach confidence (illustrative) ────────────────────

def run_storm() -> None:
    """Recalibrated P(rain) AT the storm hour vs forecast lead — confidence sharpening as it nears."""
    FIG_OUT.mkdir(parents=True, exist_ok=True)
    tf = OUT / "storm_trace" / "storm_traces.json"
    if not tf.exists():
        print("no storm_traces.json — run: python -m podml.storm_trace --all", flush=True)
        return
    traces = json.loads(tf.read_text())
    phi = _load_phi()
    iso = load_iso()
    if phi is None:
        print("no phi.json — run `display_check reliability` first (for phi + recalibration)", flush=True)
        return

    fig, axes = plt.subplots(len(traces), 1, figsize=(8.5, 3.0 * len(traces)), squeeze=False)
    for ax, st in zip(axes[:, 0], traces):
        recs = []
        for ep in st["endpoints"]:
            hb = ep["hours_before_storm"]
            hh = int(round(hb))
            if hh < 0 or hh > 24 or hh not in ep["horizons"]:
                continue
            mu = np.array([ep["mean"][ep["horizons"].index(hh)]])
            p05 = tweedie_sf(0.5, mu, phi)
            p25 = tweedie_sf(2.5, mu, phi)
            if iso is not None:
                p05 = apply_iso(iso, 0.5, np.array([hh]), p05)
                p25 = apply_iso(iso, 2.5, np.array([hh]), p25)
            recs.append((hb, float(p05[0]), float(p25[0])))
        if not recs:
            continue
        recs.sort()
        hb_a = [r[0] for r in recs]
        ax.plot(hb_a, [r[1] for r in recs], "-o", ms=3, color="tab:blue", label="P(rain ≥0.5)")
        ax.plot(hb_a, [r[2] for r in recs], "-o", ms=3, color="tab:red", label="P(rain ≥2.5)")
        ax.invert_xaxis()   # storm peak (0 h) on the right — time runs left→right toward the storm
        ax.set_ylim(0, 1)
        ax.set_xlabel("hours before storm peak  (→ approaching)")
        ax.set_ylabel("forecast probability")
        ax.set_title(f"{st['cell']} — observed peak {st['peak_rain_mm']:.1f} mm/hr")
        ax.legend(fontsize=8, loc="upper right")
    fig.suptitle("Storm-approach confidence — recalibrated P(rain) at the storm hour vs lead time", y=1.01)
    fig.tight_layout()
    fig.savefig(FIG_OUT / "storm_prob_trace.png", dpi=140, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {FIG_OUT / 'storm_prob_trace.png'}", flush=True)


# ─────────────────────────────────────────── CLI ─────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Phase-08 display calibration check (read-only, manual).")
    ap.add_argument("mode", choices=["reliability", "plumes", "leadtime", "geo", "storm"],
                    help="reliability = gate + comparison; plumes = comparison only; "
                         "leadtime = POD-vs-lead, stratified (the set-wide story); "
                         "geo = per-cell CRPSS map; storm = storm-approach confidence")
    ap.add_argument("--n-cells", type=int, default=150,
                    help="subsample cells for a cheap reliability pass (default 150; <=0 = all)")
    args = ap.parse_args()

    if args.mode == "reliability":
        phi, iso = run_reliability(None if args.n_cells <= 0 else args.n_cells)
        run_plume_compare(phi, iso)
    elif args.mode == "plumes":
        run_plume_compare()
    elif args.mode == "leadtime":
        run_leadtime()
    elif args.mode == "geo":
        run_geo()
    elif args.mode == "storm":
        run_storm()


if __name__ == "__main__":
    main()
