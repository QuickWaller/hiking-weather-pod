"""Plume examples for docs/coarse_model.md — production coarse+climatology (blended), true 2024 test.

Two figures:
  fig5_plume_examples.png       — INTENSITY-SPANNING: 5 each of dry/light/moderate/heavy (shows the range,
                                  over-represents heavy on purpose to expose the wet-tail failure).
  fig6_plume_representative.png — REAL-FREQUENCY sample (mostly dry/light — what a typical day looks like).

Per-panel dynamic y-scale. Dotted intensity lines: Light/Medium black, Heavy/Storm red.
Random within each stratum (seed=0) — not cherry-picked. Read-only / non-destructive.

    python experiments/coarse_model_plumes.py
"""
from __future__ import annotations
import numpy as np, pandas as pd
from pathlib import Path
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt

import podml.display_check as dc
from podml.config import ROOT
from podml.train_ensemble import load_ensemble_state, predict, blend, to_long_format, ENSEMBLE_FEATURES
from podml.train_motion import ensure_model_features

CP = Path("outputs/coarse_production"); dc.OUT = CP
FIG = ROOT / "docs" / "figures" / "coarse_model"; FIG.mkdir(parents=True, exist_ok=True)
CACHE = dc.CACHE_DIR
L, M, H = 0.5, 2.5, 7.6
# dotted intensity reference lines (mm/hr): Light/Medium black, Heavy/Storm red
LINES = [(0.5, "L", "black"), (2.5, "M", "black"), (7.6, "H", "red"), (16.0, "S", "red")]

print("loading wide 2024 test ...", flush=True)
X = pd.read_parquet(CACHE / "X_2024.parquet")
y = pd.read_parquet(CACHE / "y_2024.parquet")
meta = pd.read_parquet(CACHE / "meta_2024.parquet")
ensure_model_features(X, y, meta)
amount_cols = [c for c in y.columns if c.startswith("amount_h")]
peak = y[amount_cols].max(axis=1).to_numpy()
feats = [f for f in ENSEMBLE_FEATURES if f == "horizon_h" or f in X.columns]
models, clim, gs, w = load_ensemble_state(CP)
rng = np.random.default_rng(0)


def plot_fan(ax, hh, obs, q50, q75, q90, mn, title):
    ax.fill_between(hh, 0, q50, color="#d62728", alpha=0.55, lw=0)
    ax.fill_between(hh, q50, q75, color="#d62728", alpha=0.28, lw=0)
    ax.fill_between(hh, q75, q90, color="gold", alpha=0.6, lw=0)
    ax.plot(hh, mn, "k-", lw=1.0)
    ax.plot(hh, obs, "o-", color="#1f77b4", ms=2.5, lw=0.9)
    # dynamic, but floor at 3 mm/hr so dry panels don't zoom in and make a sub-1mm band look like a deluge
    top = max(3.0, 1.15 * max(float(obs.max()), float(q90.max())))
    for lv, lab, col in LINES:
        if lv < top:
            ax.axhline(lv, color=col, ls=":", lw=0.8, alpha=0.7)
            ax.text(24.4, lv, lab, fontsize=6, va="center", color=col)
    ax.set_ylim(0, top); ax.set_xlim(0, 24)
    ax.set_title(title, fontsize=7); ax.tick_params(labelsize=6)


def render(idx, nrows, ncols, suptitle, outname, row_labels=None):
    Xs, ys, ms = X.iloc[idx].reset_index(drop=True), y.iloc[idx].reset_index(drop=True), meta.iloc[idx].reset_index(drop=True)
    ms = ms.assign(_eid=np.arange(len(ms)))
    Xl, yl, ml = to_long_format(Xs[[f for f in feats if f != "horizon_h"]], ys,
                                ms[["cell", "month", "_eid"] + (["time"] if "time" in ms.columns else [])])
    bl = blend(predict(models, Xl, feats), clim, gs, w, ml)
    yv = yl.to_numpy(); h = ml["horizon_h"].to_numpy(); eid = ml["_eid"].to_numpy()
    fig, axes = plt.subplots(nrows, ncols, figsize=(2.9 * ncols, 2.4 * nrows), squeeze=False)
    for k in range(nrows * ncols):
        r, c = divmod(k, ncols); ax = axes[r][c]
        if k >= len(idx):
            ax.axis("off"); continue
        m = eid == k; o = np.argsort(h[m]); hh = h[m][o]; obs = yv[m][o]
        plot_fan(ax, hh, obs, bl["q50"][m][o], bl["q75"][m][o], bl["q90"][m][o], bl["mean"][m][o],
                 f"{ms['cell'].iloc[k]} peak {obs.max():.1f}")
        if c == 0 and row_labels:
            ax.set_ylabel(f"{row_labels[r]}\nmm/hr", fontsize=8)
        elif c == 0:
            ax.set_ylabel("mm/hr", fontsize=8)
    fig.suptitle(suptitle, fontsize=10)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(FIG / outname, dpi=140, bbox_inches="tight"); plt.close(fig)
    print(f"wrote {FIG / outname}", flush=True)


# ── fig5: intensity-spanning ────────────────────────────────────────────────────────────────
bins = [("dry (<0.5)", peak < L), ("light (0.5–2.5)", (peak >= L) & (peak < M)),
        ("moderate (2.5–7.6)", (peak >= M) & (peak < H)), ("heavy (≥7.6)", peak >= H)]
print("\n=== test-set populations (peak rain over 0–24 h) ===")
sel = []
for name, mask in bins:
    ix = np.where(mask)[0]
    print(f"  {name:20s}: {len(ix):7d} ({len(ix)/len(peak)*100:4.1f}%)")
    sel += list(rng.choice(ix, size=min(5, len(ix)), replace=False))
render(np.array(sel), 4, 5,
       "INTENSITY-SPANNING (5 each dry/light/moderate/heavy — heavy over-shown on purpose)\n"
       "blended fan: 0–q50–q75 red / q75–q90 yellow · mean black · observed blue · L/M black, H/S red",
       "fig5_plume_examples.png", row_labels=[b[0] for b in bins])

# ── fig6: real-frequency sample ─────────────────────────────────────────────────────────────
rep = rng.choice(len(peak), size=12, replace=False)
print(f"\nrepresentative sample peaks: {np.round(np.sort(peak[rep]), 1)}")
render(rep, 2, 6,
       "REAL-FREQUENCY sample (12 random endpoints — ~the actual mix: mostly dry/light)\n"
       "same fan; this is what a typical day looks like — the model gets the common case right",
       "fig6_plume_representative.png")
