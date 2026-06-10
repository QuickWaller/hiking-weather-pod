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
from scipy.stats import gamma, poisson

from podml.config import ROOT
from podml.train_ensemble import (
    OUT, CACHE_DIR, ENSEMBLE_FEATURES, WET_THRESHOLD_MM,
    load_cache, to_long_format, predict, blend, load_ensemble_state,
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


def run_reliability(n_cells: int | None) -> float:
    """Load models + test split, read off exceedance probabilities, draw the gate. Returns phi."""
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
    p_bin_te = binary_head.predict(X_te[feats]) if binary_head is not None else None

    # exceedance probabilities on test, per threshold
    p_exc = {t: tweedie_sf(t, mu_te, phi) for t in THRESHOLDS}

    fig, axes = plt.subplots(1, len(THRESHOLDS), figsize=(4.4 * len(THRESHOLDS), 4.2))
    metric_rows = []
    for ax, t in zip(axes, THRESHOLDS):
        ax.plot([0, 1], [0, 1], "k--", lw=1, alpha=0.6, label="perfect")
        for h in DISPLAY_HORIZONS:
            hm = h_te == h
            if hm.sum() < 50:
                continue
            obs = (y_te[hm] > t).astype(float)
            # primary source: binary head for 0.5, Tweedie CDF otherwise
            if t == WET_THRESHOLD_MM and p_bin_te is not None:
                pred = p_bin_te[hm]
                src = "binary"
            else:
                pred = p_exc[t][hm]
                src = "tweedie"
            rows = reliability_curve(pred, obs)
            if rows:
                mp, mo, _ = zip(*rows)
                ax.plot(mp, mo, marker="o", ms=3, lw=1.2, label=f"+{h}h")
            bm, bss, base = brier_and_bss(pred, obs)
            metric_rows.append({"threshold": t, "horizon": h, "source": src,
                                "brier": bm, "bss": bss, "base_rate": base, "n": int(hm.sum())})
            # for 0.5, also overlay the Tweedie-CDF version when a binary head exists (dashed)
            if t == WET_THRESHOLD_MM and p_bin_te is not None:
                rows2 = reliability_curve(p_exc[t][hm], obs)
                if rows2:
                    mp2, mo2, _ = zip(*rows2)
                    ax.plot(mp2, mo2, ls=":", lw=1, alpha=0.5)
        ax.set_title(f"P(rain ≥ {t} mm/hr)")
        ax.set_xlabel("forecast probability")
        ax.set_ylabel("observed frequency")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.legend(fontsize=7)
    fig.suptitle("Phase-08 reliability gate — on-diagonal = calibrated (read-only check)", y=1.02)
    fig.tight_layout()
    fig.savefig(FIG_OUT / "reliability.png", dpi=130, bbox_inches="tight")
    plt.close(fig)

    pd.DataFrame(metric_rows).to_csv(DISPLAY_OUT / "reliability_metrics.csv", index=False)
    print(f"wrote {FIG_OUT / 'reliability.png'} and {DISPLAY_OUT / 'reliability_metrics.csv'}", flush=True)
    return phi


# ─────────────────────────── side-by-side plume comparison (cheap) ───────────────────────

def _load_phi() -> float:
    p = DISPLAY_OUT / "phi.json"
    if p.exists():
        return float(json.loads(p.read_text())["phi"])
    return None  # type: ignore[return-value]


def run_plume_compare(phi: float | None = None) -> None:
    """Old quantile fan vs new height+hue plume on the same endpoints, from plumes.json (cheap)."""
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
        p_rain = (np.asarray(e["p_rain"], float)[order] if "p_rain" in e
                  else tweedie_sf(WET_THRESHOLD_MM, mean, phi))
        p_mod = tweedie_sf(2.5, mean, phi)
        heaviness = np.clip(p_mod / np.maximum(p_rain, 1e-6), 0.0, 1.0)  # P(≥2.5 | rains)
        axR.bar(h, p_rain, width=0.9, color=cmap(0.25 + 0.75 * heaviness))
        # mark hours that actually rained
        rained = yobs > WET_THRESHOLD_MM
        if rained.any():
            axR.plot(h[rained], np.full(rained.sum(), 1.02), "v", color="crimson", ms=4)
        axR.set_ylim(0, 1.08)
        axR.set_ylabel("P(rain ≥ 0.5)")
        if r == 0:
            axR.set_title("NEW — height = P(rain), hue = severity if wet")
        for ax in (axL, axR):
            ax.set_xlabel("lead time (h)" if r == len(pick) - 1 else "")
    fig.suptitle("Phase-08 rain display — old fan vs new probability plume (same endpoints)", y=1.01)
    fig.tight_layout()
    fig.savefig(FIG_OUT / "plume_compare.png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote {FIG_OUT / 'plume_compare.png'} ({len(pick)} endpoints)", flush=True)


# ───────────────────────────────────────── CLI ───────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Phase-08 display calibration check (read-only, manual).")
    ap.add_argument("mode", choices=["reliability", "plumes"],
                    help="reliability = gate + comparison (needs cache+models); "
                         "plumes = cheap comparison only (needs plumes.json)")
    ap.add_argument("--n-cells", type=int, default=150,
                    help="subsample cells for a cheap reliability pass (default 150; None = all)")
    args = ap.parse_args()

    if args.mode == "reliability":
        phi = run_reliability(None if args.n_cells <= 0 else args.n_cells)
        run_plume_compare(phi)
    else:
        run_plume_compare()


if __name__ == "__main__":
    main()
