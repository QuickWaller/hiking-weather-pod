"""Figures for docs/coarse_model.md — production coarse model, scored on the TRUE/uniform 2024 test.

Read-only, non-destructive. Loads the saved coarse_production models and grades them on the uniform
(true-distribution) cache `outputs/ensemble/dataset` — NOT the enriched v2 test (see the v2 enrichment bug).

    python experiments/coarse_model_figs.py            # writes docs/figures/coarse_model/*.png + metrics csv

One model-prediction pass over the 3.4M-row test feeds every figure.
"""
from __future__ import annotations
import numpy as np, pandas as pd
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

import podml.display_check as dc
from podml.config import ROOT
from podml.train_ensemble import (
    load_ensemble_state, predict, blend, crps_from_quantiles, _clim_preds, WET_THRESHOLD_MM,
)

CP = Path("outputs/coarse_production"); dc.OUT = CP
FIG = ROOT / "docs" / "figures" / "coarse_model"; FIG.mkdir(parents=True, exist_ok=True)
THRESH = [0.5, 2.5, 7.6]   # mm/hr light / moderate / heavy

print("loading models + true/uniform 2024 test ...", flush=True)
models, clim_table, global_stats, weights = load_ensemble_state(CP)
Xl, yv, ml, feats = dc._load_test_long()        # CACHE_DIR = outputs/ensemble/dataset (uniform)
raw = predict(models, Xl, feats)
bl = blend(raw, clim_table, global_stats, weights, ml)
clim_mean = _clim_preds(clim_table, global_stats, ml)["mean"]
cb = crps_from_quantiles(yv, bl); cr = crps_from_quantiles(yv, raw); cc = np.abs(yv - clim_mean)
h = ml["horizon_h"].to_numpy().astype(int)
hs = sorted(set(h.tolist()))

# ── per-horizon metric table ───────────────────────────────────────────────────────────────
rows = []
for hh in hs:
    m = h == hh; yh = yv[m]; ccm = float(cc[m].mean()); wet = yh > WET_THRESHOLD_MM
    rows.append(dict(
        h=hh, crpss_blend=1 - cb[m].mean() / ccm, crpss_raw=1 - cr[m].mean() / ccm,
        cov_q50=float((yh <= bl["q50"][m]).mean()), cov_q75=float((yh <= bl["q75"][m]).mean()),
        cov_q90=float((yh <= bl["q90"][m]).mean()),
        width_all=float((bl["q90"][m] - bl["q50"][m]).mean()),
        width_wet=float((bl["q90"][m][wet] - bl["q50"][m][wet]).mean()) if wet.any() else np.nan,
        wet_rate=float(wet.mean()), n=int(m.sum())))
df = pd.DataFrame(rows); df.to_csv(FIG / "metrics_truedist.csv", index=False)
w = np.exp(-df.h / 6.0); w /= w.sum()
tb, tr = float((df.crpss_blend * w).sum()), float((df.crpss_raw * w).sum())
print(f"tau6 CRPSS blend={tb:.4f} raw={tr:.4f}", flush=True)

# ── fig 1: skill vs lead time ───────────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(7, 4.2))
ax.plot(df.h, df.crpss_blend, "-o", ms=3, color="#1f77b4", label=f"blended (τ6={tb:.3f})")
ax.plot(df.h, df.crpss_raw, "--s", ms=3, color="#d62728", label=f"raw model (τ6={tr:.3f})")
ax.axhline(0, color="k", lw=0.8, ls=":"); ax.set_ylim(0, 0.6)
ax.set_xlabel("lead time (h)"); ax.set_ylabel("CRPSS  (vs climatology)")
ax.set_title("Rain-amount skill by lead time — TRUE 2024 test\n0 = climatology, higher = better")
ax.legend(); ax.grid(alpha=0.3); fig.tight_layout(); fig.savefig(FIG / "fig1_skill.png", dpi=140); plt.close(fig)

# ── fig 2: calibration (coverage vs target) ─────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(7, 4.2))
for q, tgt, c in [("cov_q50", 0.50, "#2ca02c"), ("cov_q75", 0.75, "#ff7f0e"), ("cov_q90", 0.90, "#1f77b4")]:
    ax.plot(df.h, df[q], "-o", ms=3, color=c, label=f"{q[-3:]} observed")
    ax.axhline(tgt, color=c, lw=0.8, ls="--", alpha=0.7)
ax.set_xlabel("lead time (h)"); ax.set_ylabel("observed coverage  (fraction ≤ quantile)")
ax.set_title("Calibration — observed coverage vs target (dashed)\nall-hours; dry mass lifts q50 above 0.5")
ax.legend(); ax.grid(alpha=0.3); ax.set_ylim(0.4, 1.0); fig.tight_layout()
fig.savefig(FIG / "fig2_calibration.png", dpi=140); plt.close(fig)

# ── fig 3: sharpness (band width) ───────────────────────────────────────────────────────────
fig, ax = plt.subplots(figsize=(7, 4.2))
ax.plot(df.h, df.width_all, "-o", ms=3, color="#7f7f7f", label="all hours")
ax.plot(df.h, df.width_wet, "-o", ms=3, color="#1f77b4", label="wet hours (>0.5mm)")
ax.set_xlabel("lead time (h)"); ax.set_ylabel("mean band width q90−q50 (mm/hr)")
ax.set_title("Sharpness — predictive band width by lead time")
ax.legend(); ax.grid(alpha=0.3); fig.tight_layout(); fig.savefig(FIG / "fig3_sharpness.png", dpi=140); plt.close(fig)

# ── fig 4: per-cell geo skill map ───────────────────────────────────────────────────────────
g = (pd.DataFrame({"cell": ml["cell"].to_numpy(), "cm": cb, "cc": cc}).groupby("cell")
     .agg(cm=("cm", "mean"), cc=("cc", "mean"), n=("cm", "size")))
g["crpss"] = 1 - g.cm / g.cc.where(g.cc > 0); g = g.dropna(subset=["crpss"])
ll = [dc._cell_to_latlon(c) for c in g.index]; g["lat"] = [a for a, _ in ll]; g["lon"] = [b for _, b in ll]
g.to_csv(FIG / "geo_crpss.csv")
fig, ax = plt.subplots(figsize=(6.5, 8))
sc = ax.scatter(g.lon, g.lat, c=g.crpss.clip(0, 0.85), cmap="viridis", s=14)
ax.set_aspect(1 / np.cos(np.deg2rad(41))); ax.set_xlabel("longitude"); ax.set_ylabel("latitude")
ax.set_title(f"Per-cell CRPSS — TRUE 2024 test ({len(g)} cells)\nmedian {g.crpss.median():.2f}, "
             f"{(g.crpss>0).mean()*100:.0f}% positive")
fig.colorbar(sc, ax=ax, label="CRPSS", fraction=0.045); fig.tight_layout()
fig.savefig(FIG / "fig4_geo_skill.png", dpi=140); plt.close(fig)

# ── discrimination: wet-tail coverage (the heavy blind-spot) ─────────────────────────────────
print("\n=== wet-conditional q90 coverage by threshold (the heavy-tail story) ===", flush=True)
for thr in THRESH:
    sel = yv > thr
    if sel.sum() < 100:
        print(f"  >{thr}mm: n={int(sel.sum())} too few"); continue
    print(f"  obs >{thr}mm: n={int(sel.sum()):>7} | frac ≤ blended q90 = {(yv[sel] <= bl['q90'][sel]).mean():.3f}", flush=True)
print(f"\nwrote {FIG}/*.png + metrics_truedist.csv", flush=True)
