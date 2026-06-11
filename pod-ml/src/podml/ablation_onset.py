"""Phase-08 ablation: does knowing when rain last started help predict future rain?

Simulates the pod's rain-onset button press using ERA5 labels (amount_h0 > 0.5 mm/hr).
Adds `rain_onset_h` = hours since the last observed rain onset at this location, then
compares a retrain WITH vs WITHOUT the feature.

Non-destructive: reads from the existing cache, trains on a cell subset, writes only to
`outputs/ensemble/ablation_onset/` and `docs/figures/ablation/`. Existing models and
outputs are never touched.

Usage
-----
    python -m podml.ablation_onset [--n-cells 200] [--seed 42] [--n-boot 200]
"""

from __future__ import annotations

import argparse
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from podml.config import ROOT
from podml.train_ensemble import (
    OUT, CACHE_DIR, ENSEMBLE_FEATURES, WET_THRESHOLD_MM,
    load_cache, to_long_format,
    fit_ensemble, fit_cell_weights, predict, blend,
    build_clim_distribution, crps_from_quantiles,
)
from podml.train_motion import VAL_YEAR, TEST_YEAR, TRAIN_YEARS, ensure_model_features

ABLATION_OUT = OUT / "ablation_onset"
FIG_OUT = ROOT / "docs" / "figures" / "ablation"

ONSET_FEATURE = "rain_onset_h"
MAX_ONSET_H = 168.0   # cap at 1 week; beyond this, the signal is just "it's been dry"


# ──────────────────────────────── feature computation ────────────────────────────────────────────

def compute_hours_since_onset(
    y: pd.DataFrame,
    meta: pd.DataFrame,
    wet_threshold: float = WET_THRESHOLD_MM,
    max_h: float = MAX_ONSET_H,
) -> np.ndarray:
    """Hours since the most recent observed rain onset, per observation row.

    Simulates the pod button press: if it is raining at observation time (amount_h0 > threshold),
    feature = 0. Otherwise, time elapsed since the last wet observation for that cell, capped at
    max_h. Rows with no prior wet observation in the cache are assigned max_h.

    Causal: only past observations are used (last_wet is updated *after* reading the current row).
    Only amount_h0 (the observation-time rain amount) is read — no future label leakage.
    """
    result = np.full(len(meta), max_h, dtype="float32")
    times = pd.to_datetime(meta["time"].to_numpy())
    rain_now = (y["amount_h0"].to_numpy() > wet_threshold)

    for cell_id in meta["cell"].unique():
        cm = (meta["cell"] == cell_id).to_numpy()
        idx = np.where(cm)[0]
        t_cell = times[idx]
        r_cell = rain_now[idx]
        order = np.argsort(t_cell)
        t_sorted = t_cell[order]
        r_sorted = r_cell[order]
        orig_sorted = idx[order]

        last_wet: pd.Timestamp | None = None
        for t, r, orig in zip(t_sorted, r_sorted, orig_sorted):
            if r:
                result[orig] = 0.0
                last_wet = t
            elif last_wet is not None:
                delta_h = (t - last_wet).total_seconds() / 3600.0
                result[orig] = min(delta_h, max_h)
            # else: no prior wet → stays at max_h

    return result


# ──────────────────────────────── ablation core ──────────────────────────────────────────────────

def _crpss_vs_clim(crps_model: np.ndarray, y: np.ndarray,
                   clim_table: dict, global_stats: dict, meta: pd.DataFrame,
                   weights: dict) -> float:
    """CRPSS = 1 - mean(CRPS_model) / mean(CRPS_clim)."""
    from podml.train_ensemble import _clim_preds
    clim_p = _clim_preds(clim_table, global_stats, meta)
    crps_clim = crps_from_quantiles(y, clim_p)
    mc, cc = float(crps_model.mean()), float(crps_clim.mean())
    return 1.0 - mc / cc if cc > 0 else float("nan")


def _run_one(label: str, X_tr, y_tr, meta_tr,
             X_vl, y_vl, meta_vl,
             X_te, y_te, meta_te,
             feats: list[str],
             clim_table: dict, global_stats: dict,
             seed: int, n_boot: int) -> dict:
    """Train + evaluate one configuration. Returns metrics dict."""
    print(f"\n── {label} ──", flush=True)
    models = fit_ensemble(X_tr, y_tr, X_vl, y_vl, feats, seed=seed)
    weights = fit_cell_weights(models, X_vl, y_vl, meta_vl,
                               clim_table, global_stats, feats)
    blended = blend(predict(models, X_te, feats), clim_table, global_stats, weights, meta_te)
    crps_m = crps_from_quantiles(y_te, blended)

    from podml.train_ensemble import _clim_preds
    crps_c = crps_from_quantiles(y_te, _clim_preds(clim_table, global_stats, meta_te))
    crpss = float(1.0 - crps_m.mean() / crps_c.mean())

    rng = np.random.default_rng(seed)
    boot = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(crps_m), len(crps_m))
        cm_b, cc_b = crps_m[idx].mean(), crps_c[idx].mean()
        boot.append(1.0 - cm_b / cc_b if cc_b > 0 else np.nan)
    ci_lo, ci_hi = float(np.nanpercentile(boot, 2.5)), float(np.nanpercentile(boot, 97.5))

    print(f"  CRPSS = {crpss:.4f}  95% CI [{ci_lo:.4f}, {ci_hi:.4f}]", flush=True)
    return {"label": label, "crpss": crpss, "ci_lo": ci_lo, "ci_hi": ci_hi,
            "crps_model": crps_m, "crps_clim": crps_c}


def run_ablation(n_cells: int = 200, seed: int = 42, n_boot: int = 200) -> None:
    ABLATION_OUT.mkdir(parents=True, exist_ok=True)
    FIG_OUT.mkdir(parents=True, exist_ok=True)

    # ── load + subsample ──────────────────────────────────────────────────────────────────────────
    X, y, meta = load_cache(CACHE_DIR)
    ensure_model_features(X, y, meta)

    rng0 = np.random.default_rng(seed)
    keep = set(rng0.choice(meta["cell"].unique(),
                           size=min(n_cells, meta["cell"].nunique()), replace=False))
    m = meta["cell"].isin(keep).to_numpy()
    X = X[m].reset_index(drop=True)
    y = y[m].reset_index(drop=True)
    meta = meta[m].reset_index(drop=True)
    print(f"ablation_onset: {meta['cell'].nunique()} cells, {len(X):,} endpoints", flush=True)

    # ── compute onset feature ─────────────────────────────────────────────────────────────────────
    onset_h = compute_hours_since_onset(y, meta)
    print(f"  rain_onset_h: mean={onset_h.mean():.1f}h  "
          f"0h (raining now)={float((onset_h==0).mean())*100:.1f}%  "
          f"capped at {MAX_ONSET_H}h: {float((onset_h>=MAX_ONSET_H).mean())*100:.1f}%", flush=True)

    # ── baseline features (no onset) ──────────────────────────────────────────────────────────────
    base_feats = [f for f in ENSEMBLE_FEATURES if f == "horizon_h" or f in X.columns]

    # ── onset features (add rain_onset_h) ─────────────────────────────────────────────────────────
    X_onset = X.copy()
    X_onset[ONSET_FEATURE] = onset_h
    onset_feats = base_feats + [ONSET_FEATURE]  # horizon_h appended last by to_long_format

    # ── expand to long format for both ───────────────────────────────────────────────────────────
    meta_cols = ["cell", "month", "year"] + (["time"] if "time" in meta.columns else [])

    def _split(X_w, feats_no_h):
        Xl, yl, ml = to_long_format(X_w[[f for f in feats_no_h if f != "horizon_h"]],
                                    y, meta[meta_cols])
        yrs = ml["year"].to_numpy()
        tr = np.isin(yrs, list(TRAIN_YEARS))
        vl = yrs == VAL_YEAR
        te = yrs == TEST_YEAR
        return (Xl[tr].reset_index(drop=True), yl[tr].to_numpy(), ml[tr].reset_index(drop=True),
                Xl[vl].reset_index(drop=True), yl[vl].to_numpy(), ml[vl].reset_index(drop=True),
                Xl[te].reset_index(drop=True), yl[te].to_numpy(), ml[te].reset_index(drop=True))

    Btr, Btr_y, Btr_m, Bvl, Bvl_y, Bvl_m, Bte, Bte_y, Bte_m = _split(X, base_feats)
    Otr, Otr_y, Otr_m, Ovl, Ovl_y, Ovl_m, Ote, Ote_y, Ote_m = _split(X_onset, onset_feats)

    clim_table, global_stats = build_clim_distribution(
        pd.Series(Btr_y, name="amount"), Btr_m, np.ones(len(Btr_y), dtype=bool))

    # ── train + eval ──────────────────────────────────────────────────────────────────────────────
    res_base = _run_one("baseline (no onset)", Btr, Btr_y, Btr_m, Bvl, Bvl_y, Bvl_m,
                        Bte, Bte_y, Bte_m, base_feats, clim_table, global_stats, seed, n_boot)
    res_onset = _run_one("with rain_onset_h", Otr, Otr_y, Otr_m, Ovl, Ovl_y, Ovl_m,
                         Ote, Ote_y, Ote_m, onset_feats, clim_table, global_stats, seed, n_boot)

    delta = res_onset["crpss"] - res_base["crpss"]
    delta_lo = res_onset["ci_lo"] - res_base["ci_hi"]  # conservative: worst-case delta CI
    delta_hi = res_onset["ci_hi"] - res_base["ci_lo"]
    verdict = "POSITIVE" if delta_lo > 0 else ("MARGINAL" if delta > 0 else "NO SIGNAL")

    print("\n── verdict ──", flush=True)
    print(f"  ΔCRPSS = {delta:+.4f}  conservative CI [{delta_lo:+.4f}, {delta_hi:+.4f}]", flush=True)
    print(f"  → {verdict}", flush=True)

    # ── save results ──────────────────────────────────────────────────────────────────────────────
    rows = []
    for r in (res_base, res_onset):
        rows.append({"label": r["label"], "crpss": r["crpss"],
                     "ci_lo": r["ci_lo"], "ci_hi": r["ci_hi"]})
    rows.append({"label": "delta", "crpss": delta, "ci_lo": delta_lo, "ci_hi": delta_hi})
    pd.DataFrame(rows).to_csv(ABLATION_OUT / "results.csv", index=False)

    summary = {
        "n_cells": int(meta["cell"].nunique()),
        "seed": seed, "n_boot": n_boot,
        "baseline_crpss": res_base["crpss"],
        "onset_crpss": res_onset["crpss"],
        "delta_crpss": delta,
        "delta_ci_lo": delta_lo,
        "delta_ci_hi": delta_hi,
        "verdict": verdict,
    }
    (ABLATION_OUT / "summary.json").write_text(json.dumps(summary, indent=2))

    # ── figure: CRPSS bars with CI + onset feature distribution ──────────────────────────────────
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))

    ax = axes[0]
    labels = ["baseline", "with onset"]
    crpss_vals = [res_base["crpss"], res_onset["crpss"]]
    ci_lo_vals = [res_base["ci_lo"], res_onset["ci_lo"]]
    ci_hi_vals = [res_base["ci_hi"], res_onset["ci_hi"]]
    colors = ["#5b9bd5", "#ed7d31"]
    for i, (lbl, cv, lo, hi, col) in enumerate(zip(labels, crpss_vals, ci_lo_vals, ci_hi_vals, colors)):
        ax.bar(i, cv, color=col, alpha=0.8, label=lbl)
        ax.plot([i, i], [lo, hi], "k-", lw=2)
        ax.plot(i, lo, "k_", ms=8)
        ax.plot(i, hi, "k_", ms=8)
    ax.set_xticks([0, 1])
    ax.set_xticklabels(labels)
    ax.set_ylabel("CRPSS")
    ax.set_title(f"CRPSS comparison ({meta['cell'].nunique()} cells)\nΔ={delta:+.4f}  {verdict}")
    ax.axhline(0, color="grey", ls=":", lw=1)

    ax2 = axes[1]
    finite = onset_h[onset_h < MAX_ONSET_H]
    ax2.hist(finite, bins=40, color="#5b9bd5", alpha=0.8, edgecolor="white", lw=0.3)
    ax2.set_xlabel("hours since last rain onset (capped values excluded)")
    ax2.set_ylabel("count")
    ax2.set_title(f"rain_onset_h distribution\n"
                  f"0h (raining now): {float((onset_h==0).mean())*100:.1f}%  "
                  f"capped: {float((onset_h>=MAX_ONSET_H).mean())*100:.1f}%")

    fig.suptitle("Ablation: rain-onset button feature", y=1.02)
    fig.tight_layout()
    fig.savefig(FIG_OUT / "onset_ablation.png", dpi=130, bbox_inches="tight")
    plt.close(fig)

    print(f"\nwrote {ABLATION_OUT / 'results.csv'} and {FIG_OUT / 'onset_ablation.png'}", flush=True)


# ──────────────────────────────────────────────── CLI ────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description="Rain-onset button ablation (non-destructive).")
    ap.add_argument("--n-cells", type=int, default=200,
                    help="cells to subsample for speed (default 200; 0 = all)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--n-boot", type=int, default=200,
                    help="bootstrap samples for CI (default 200)")
    args = ap.parse_args()
    run_ablation(
        n_cells=args.n_cells if args.n_cells > 0 else None,
        seed=args.seed,
        n_boot=args.n_boot,
    )


if __name__ == "__main__":
    main()
