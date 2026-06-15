"""v2 model assessment report — continuous-forecast verification graphs.

Re-runs inference on the 2024 test set (no retrain) from saved v2 models, then draws the
continuous-forecast verification graphs an assessor needs (docs/10 §1c). Two to start:

  conditional_quantile.png — conditional quantile diagram (the field-standard plot):
      bin by predicted mean, show the OBSERVED distribution (median + IQR + 10-90) per bin
      vs the 1:1 line. Median tracking the diagonal = accurate; box height = honest spread.
  density_obs_pred.png — 2-D log-density heatmap of observed × predicted (the continuous
      "confusion matrix"): bright ridge on the diagonal = accurate, off-diagonal = misses.

Both as 5-panel small multiples over lead times 0/3/6/12/24 h, so the diagonal fuzzing out
with lead time *is* the skill-decay story.

Usage:
  python -m podml.report_v2 --out-dir outputs/ensemble_v2_full \
      --cache-dir outputs/ensemble/dataset_v2 --fig-dir experiments/v2_report
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm

from podml.train_ensemble import (
    MODEL_NAMES, ENSEMBLE_FEATURES,
    load_cache, load_ensemble_state, to_long_format, predict, blend, ensure_model_features,
)
from podml.train_motion import TEST_YEAR

REPORT_LEADS = [0, 3, 6, 12, 24]
# Rain-rate bin edges (mm/hr): fine near 0 (where the mass is), coarsening into the tail.
RATE_EDGES = np.array([0.0, 0.1, 0.5, 1.0, 2.5, 5.0, 7.6, 12.0, 20.0, 40.0])
LMH = [(0.5, "L"), (2.5, "M"), (7.6, "H")]


# ─────────────────────────────────────────────── inference ──────────────────────────────────────

def build_test_inference(out_dir: Path, cache_dir: Path,
                         n_cells: int | None = None, seed: int = 42) -> dict:
    """Load saved v2 models + the test cache; blended prediction per 2024 endpoint."""
    models, clim_table, global_stats, weights = load_ensemble_state(out_dir)
    if not all(n in models for n in MODEL_NAMES):
        raise SystemExit(f"missing models in {out_dir}/models (have {sorted(models)}, need {MODEL_NAMES})")
    X, y, meta = load_cache(cache_dir)
    ensure_model_features(X, y, meta)
    if n_cells:
        rng = np.random.default_rng(seed)
        keep = set(rng.choice(meta["cell"].unique(),
                              size=min(n_cells, meta["cell"].nunique()), replace=False))
        m = meta["cell"].isin(keep).to_numpy()
        X, y, meta = X[m].reset_index(drop=True), y[m].reset_index(drop=True), meta[m].reset_index(drop=True)
    feats = [f for f in ENSEMBLE_FEATURES if f == "horizon_h" or f in X.columns]
    keep_meta = ["cell", "month", "year"] + [c for c in ("lat", "lon", "time") if c in meta.columns]
    Xl, yl, ml = to_long_format(X[[f for f in feats if f != "horizon_h"]], y, meta[keep_meta])
    te = ml["year"].to_numpy() == TEST_YEAR
    Xt, yt, mt = Xl[te].reset_index(drop=True), yl[te].to_numpy(), ml[te].reset_index(drop=True)
    preds = predict(models, Xt, feats)
    bl = blend(preds, clim_table, global_stats, weights, mt)
    out = {"obs": yt, "horizon": mt["horizon_h"].to_numpy(), "cell": mt["cell"].to_numpy()}
    out.update({n: bl[n] for n in MODEL_NAMES})
    for c in ("lat", "lon", "time"):
        if c in mt.columns:
            out[c] = mt[c].to_numpy()
    return out


def conditional_nonzero_table(inf: dict, wet_thr: float = 0.5, eps: float = 0.05,
                              max_lead: int = 6) -> pd.DataFrame:
    """The decisive 'is q50/q75 stunlocked to 0?' test: non-zero rate + magnitude of each
    quantile, stratified by rain proximity — dry / within 3h of rain / raining now.

    Rain proximity is per endpoint (cell, base time): a ±3h rolling-max over the forward
    timeline marks hours near a wet hour (obs ≥ wet_thr). Restricted to near-term leads
    (≤ max_lead h) where the lower bands matter for the display.
    """
    if "time" not in inf:
        raise SystemExit("conditional_nonzero_table needs 'time' in the inference (rebuild cache).")
    df = pd.DataFrame({"cell": inf["cell"], "time": inf["time"], "h": inf["horizon"],
                       "obs": inf["obs"], "q50": inf["q50"], "q75": inf["q75"], "q90": inf["q90"]})
    df["wet"] = df["obs"] >= wet_thr
    df = df.sort_values(["cell", "time", "h"])
    # ±3h window (7 hourly slots, centred) over each endpoint's forward timeline
    df["near"] = (df.groupby(["cell", "time"])["wet"]
                    .transform(lambda s: s.rolling(7, center=True, min_periods=1).max()) > 0)
    df = df[df["h"] <= max_lead]
    df["stratum"] = np.where(df["wet"], "raining now",
                             np.where(df["near"], "within 3h of rain", "dry (>3h away)"))
    rows = []
    for s in ["dry (>3h away)", "within 3h of rain", "raining now"]:
        g = df[df["stratum"] == s]
        if len(g) == 0:
            continue
        rows.append({
            "stratum": s, "n": len(g),
            "q50>0 %": 100 * (g["q50"] > eps).mean(), "q50_mean": g["q50"].mean(),
            "q75>0 %": 100 * (g["q75"] > eps).mean(), "q75_mean": g["q75"].mean(),
            "q90>0 %": 100 * (g["q90"] > eps).mean(), "q90_mean": g["q90"].mean(),
            "obs_mean": g["obs"].mean(),
        })
    return pd.DataFrame(rows)


def relaxation_table(inf: dict, leads: list[int] = REPORT_LEADS,
                     dry_thr: float = 0.1, wet_thr: float = 0.5) -> pd.DataFrame:
    """Honesty check #1 (the decisive one): does each quantile RELAX on dry hours and lift on wet?

    Split test hours into dry (obs < dry_thr) vs wet (obs ≥ wet_thr); report the MEDIAN of each
    blended quantile in each group, per lead. PASS = dry-hour median q90 ≲ 0.5 mm/hr (the all-clear
    works) AND wet-hour median q90 clearly higher (it discriminates). If dry-hour q90 doesn't relax,
    even q90 is acting as a constant → drop the top band to q75. The `q90_dry_med` column is also
    the empirical check on the 0.90 cap: a thin margin to 0.5 means q95 would be a permanent band.
    """
    obs, h = inf["obs"], inf["horizon"]
    rows = []
    for lead in leads:
        m = h == lead
        dry, wet = m & (obs < dry_thr), m & (obs >= wet_thr)
        if dry.sum() < 50 or wet.sum() < 20:
            continue
        r = {"lead_h": lead, "n_dry": int(dry.sum()), "n_wet": int(wet.sum())}
        for q in ("q50", "q75", "q90"):
            r[f"{q}_dry_med"] = float(np.median(inf[q][dry]))
            r[f"{q}_wet_med"] = float(np.median(inf[q][wet]))
        r["q90_relaxes"] = r["q90_dry_med"] <= 0.5 and r["q90_wet_med"] > r["q90_dry_med"] * 1.5
        rows.append(r)
    return pd.DataFrame(rows)


def monotonicity_rate(inf: dict, eps: float = 1e-9) -> float:
    """Honesty check #3: fraction of rows where the blended quantiles cross (q50>q75 or q75>q90).
    Must be 0; if not, the blend re-introduced crossings after predict()'s sort and we clip."""
    q50, q75, q90 = inf["q50"], inf["q75"], inf["q90"]
    cross = (q50 > q75 + eps) | (q75 > q90 + eps)
    return float(cross.mean())


# ─────────────────────────────────────────── graph builders ─────────────────────────────────────

def conditional_quantile_panel(ax, pred: np.ndarray, obs: np.ndarray, n_bins: int = 10) -> None:
    """Conditional quantile diagram on one axis: predicted (x) vs observed distribution (y).

    Equal-population bins of the forecast; each bin shows observed median (dot), IQR (thick
    bar) and 10-90 (thin whisker) at the bin's mean predicted value, against the 1:1 line.
    """
    edges = np.quantile(pred, np.linspace(0, 1, n_bins + 1))
    edges = np.unique(edges)
    xs, med, q25, q75, q10, q90 = [], [], [], [], [], []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (pred >= lo) & (pred <= hi) if hi == edges[-1] else (pred >= lo) & (pred < hi)
        if m.sum() < 30:
            continue
        o = obs[m]
        xs.append(float(pred[m].mean()))
        med.append(float(np.median(o)))
        q25.append(float(np.percentile(o, 25)))
        q75.append(float(np.percentile(o, 75)))
        q10.append(float(np.percentile(o, 10)))
        q90.append(float(np.percentile(o, 90)))
    xs = np.array(xs)
    hi = max(np.max(xs), np.max(q90), 1.0) * 1.05
    ax.plot([0, hi], [0, hi], color="#888", lw=1, ls="--", zorder=1)        # 1:1 ideal
    ax.vlines(xs, q10, q90, color="#9ecae1", lw=2, zorder=2)                  # 10-90 whisker
    ax.vlines(xs, q25, q75, color="#2166ac", lw=5, zorder=3)                  # IQR
    ax.plot(xs, med, "o-", color="#08306b", ms=4, lw=1.2, zorder=4)          # observed median
    ax.set_xlim(0, hi)
    ax.set_ylim(0, hi)
    ax.set_xlabel("predicted mean (mm/hr)")
    ax.set_ylabel("observed (mm/hr)")
    ax.grid(alpha=0.2)


def density_panel(ax, pred: np.ndarray, obs: np.ndarray, edges: np.ndarray = RATE_EDGES):
    """2-D log-density heatmap of observed × predicted — the continuous confusion matrix."""
    H, xe, ye = np.histogram2d(pred, obs, bins=[edges, edges])
    H = H.T  # rows = observed
    mesh = ax.pcolormesh(xe, ye, np.ma.masked_equal(H, 0),
                         norm=LogNorm(vmin=1, vmax=max(H.max(), 1)), cmap="magma")
    ax.plot([edges[0], edges[-1]], [edges[0], edges[-1]], color="#39ff14", lw=1, ls="--")
    ax.set_xscale("symlog", linthresh=0.5)
    ax.set_yscale("symlog", linthresh=0.5)
    ax.set_xlim(0, edges[-1])
    ax.set_ylim(0, edges[-1])
    ax.set_xlabel("predicted mean (mm/hr)")
    ax.set_ylabel("observed (mm/hr)")
    return mesh


def make_report(inf: dict, fig_dir: Path) -> None:
    fig_dir.mkdir(parents=True, exist_ok=True)
    pred, obs, h = inf["mean"], inf["obs"], inf["horizon"]

    # 1) conditional quantile diagram, 5 leads
    fig, axes = plt.subplots(1, len(REPORT_LEADS), figsize=(3.0 * len(REPORT_LEADS), 3.2))
    for i, (ax, lead) in enumerate(zip(axes, REPORT_LEADS)):
        m = h == lead
        if m.sum() < 100:
            ax.set_title(f"h={lead}h (n<100)")
            continue
        conditional_quantile_panel(ax, pred[m], obs[m])
        ax.set_title(f"lead = {lead} h")
        if i > 0:
            ax.set_ylabel("")
    fig.suptitle("Conditional quantile diagram — observed distribution given the forecast "
                 "(median dot · IQR thick · 10–90 thin · 1:1 dashed)", fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.94))
    fig.savefig(fig_dir / "conditional_quantile.png", dpi=130)
    plt.close(fig)

    # 2) 2-D log-density heatmap, 5 leads
    fig, axes = plt.subplots(1, len(REPORT_LEADS), figsize=(3.0 * len(REPORT_LEADS), 3.3))
    mesh = None
    for i, (ax, lead) in enumerate(zip(axes, REPORT_LEADS)):
        m = h == lead
        if m.sum() < 100:
            ax.set_title(f"h={lead}h (n<100)")
            continue
        mesh = density_panel(ax, pred[m], obs[m])
        ax.set_title(f"lead = {lead} h")
        if i > 0:
            ax.set_ylabel("")
    if mesh is not None:
        fig.colorbar(mesh, ax=axes, shrink=0.7, label="count (log)")
    fig.suptitle("Observed × predicted density — the continuous confusion matrix "
                 "(bright ridge on the green 1:1 line = accurate)", fontsize=10)
    fig.savefig(fig_dir / "density_obs_pred.png", dpi=130, bbox_inches="tight")
    plt.close(fig)
    print(f"wrote conditional_quantile.png + density_obs_pred.png -> {fig_dir}")

    # 3) the decisive q50/q75 'stunlocked to zero?' table, by rain proximity
    if "time" in inf:
        tbl = conditional_nonzero_table(inf)
        tbl.to_csv(fig_dir / "lower_band_nonzero.csv", index=False)
        print("\n  q50/q75/q90 non-zero rate + magnitude by rain proximity (leads <=6h):")
        print(tbl.to_string(index=False, float_format=lambda v: f"{v:.2f}"))

    # 4) honesty referee (your-other-Opus spec): #1 relaxation, #3 monotonicity. #2 coverage
    #    is already in metrics_overall.csv (cov_le_q50/q75/q90 per lead).
    relax = relaxation_table(inf)
    relax.to_csv(fig_dir / "relaxation.csv", index=False)
    print("\n  #1 RELAXATION — median quantile on dry (obs<0.1) vs wet (obs>=0.5) hours, per lead:")
    print(relax.to_string(index=False, float_format=lambda v: f"{v:.2f}"))
    mono = monotonicity_rate(inf)
    print(f"\n  #3 MONOTONICITY — blended quantile crossing rate: {mono:.6f} "
          f"({'PASS (0)' if mono == 0 else 'FAIL — clip needed'})")
    if not relax.empty:
        passes = relax["q90_relaxes"].all()
        print(f"  => q90 relaxes on dry hours at every lead: {passes} "
              f"(dry-hour median q90 range {relax['q90_dry_med'].min():.2f}-{relax['q90_dry_med'].max():.2f} mm/hr)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", type=str, default="outputs/ensemble_v2_full",
                    help="dir holding models/ + cell_weights.json (saved v2 state)")
    ap.add_argument("--cache-dir", type=str, default="outputs/ensemble/dataset_v2")
    ap.add_argument("--fig-dir", type=str, default="experiments/v2_report")
    ap.add_argument("--n-cells", type=int, default=None, help="subsample cells (faster smoke)")
    args = ap.parse_args()
    inf = build_test_inference(Path(args.out_dir), Path(args.cache_dir), n_cells=args.n_cells)
    print(f"test endpoints: {len(inf['obs']):,}")
    make_report(inf, Path(args.fig_dir))


if __name__ == "__main__":
    main()
