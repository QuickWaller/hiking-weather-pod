"""Natural-language stats for docs/coarse_model.md — occurrence skill, amount under-prediction,
short-vs-long horizon — production coarse+climatology (blended), true/uniform 2024 test.

    python experiments/coarse_model_nl.py     # prints; read-only.
"""
from __future__ import annotations
import numpy as np
from pathlib import Path
import podml.display_check as dc
from podml.train_ensemble import load_ensemble_state, predict, blend

CP = Path("outputs/coarse_production"); dc.OUT = CP
models, clim, gs, w = load_ensemble_state(CP)
Xl, yv, ml, feats = dc._load_test_long()
bl = blend(predict(models, Xl, feats), clim, gs, w, ml)
mean, q90 = bl["mean"], bl["q90"]
h = ml["horizon_h"].to_numpy(); cell = ml["cell"].to_numpy()
RAIN = 0.5  # mm/hr "it rained"


def stats(mask, label):
    y, mn, q9 = yv[mask], mean[mask], q90[mask]
    if len(y) < 40:
        print(f"{label:24s} n={len(y)} (too few)"); return
    rained, fc = y >= RAIN, mn >= RAIN
    prec = (rained & fc).sum() / max(fc.sum(), 1)
    rec = (rained & fc).sum() / max(rained.sum(), 1)
    if rained.any():
        over = float((y[rained] > q9[rained]).mean())           # under-covered fraction
        ratio = float(np.median(y[rained] / np.maximum(mn[rained], 0.05)))  # obs / predicted-mean
    else:
        over = ratio = float("nan")
    print(f"{label:24s} n={len(y):>7} rain={rained.mean():.3f} | predicts-rain: precision={prec:.2f} "
          f"recall={rec:.2f} | when-it-rains: obs>q90={over:.2f} median(obs/pred)={ratio:.1f}x")


cells = sorted(set(cell.tolist()))
ll = {c: dc._cell_to_latlon(c) for c in cells}
lb = min(cells, key=lambda c: (ll[c][0] + 36.66) ** 2 + (ll[c][1] - 174.73) ** 2)
print(f"Long Bay → nearest grid cell {lb} at {ll[lb]}\n")

print("=== OVERALL (all cells) ===")
stats(np.ones(len(yv), bool), "all horizons")
for hh in (0, 3, 6, 12, 24):
    stats(h == hh, f"h={hh}")
print("\n=== LONG BAY cell ===")
stats(cell == lb, "all horizons")
for hh in (0, 6, 12, 24):
    stats((cell == lb) & (h == hh), f"h={hh}")
