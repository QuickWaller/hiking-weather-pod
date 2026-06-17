"""Render the §1 rain-plume display from the CANONICAL production object: the
`blended` distribution in plumes.json (raw heads blended with per-cell climatology
+ trust weights). This is what the headline CRPSS is scored on (train_ensemble.py:816)
and what the display reads off ("CDF lookup on the blended distribution", line 11).

NOT the `conformal` field (wet-hour CQR-corrected — inflates bands by +1–2 mm/hr,
belongs to eval coverage, not the display) and NOT the wet-conditional heads.

The blended quantiles self-gate: they already fold in the dry point-mass via the
climatology blend, so dry hours sit near the floor and wet hours widen — no P(rain)
gate. Bands per spec: 0→q75 solid red, q75→q90 hatched red, mean = black line,
dotted L/M/H refs (0.5/2.5/7.6), observed truth = white dots, P(rain) = dashed blue."""
import json, numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.lines import Line2D

HERE = r"C:/website-projects/cyber-deck-and-weather-station/pod-ml/experiments/baseline_figs"
D = json.load(open(f"{HERE}/plumes.json"))
RED, BLK, BLU = "#d83020", "#111111", "#2166ac"
LMH = [(0.5, "L"), (2.5, "M"), (7.6, "H")]
PICKS = [
    (19, "Heavy event — 39.6 mm / 24 h (Taupō, 13 Jun)"),
    (12, "Moderate rain — 20.4 mm (Sthn Alps, 22 Jun)"),
    (7,  "Dry truth, P(rain) peaks 0.27 (Nelson, 13 Jul)"),
    (9,  "Dry, P(rain)≈0.05 (Mackenzie, 1 Jun)"),
]

def draw(ax, e):
    h = np.array(e["horizons"]); b = e["blended"]
    mean, q75, q90 = np.array(b["mean"]), np.array(b["q75"]), np.array(b["q90"])
    yobs, pr = np.array(e["y_obs"]), np.array(e["p_rain"])
    ytop = max(q90.max() * 1.4, yobs.max() * 1.1, 1.0)
    ax.fill_between(h, 0, q75, color=RED, alpha=0.95, lw=0, zorder=2)
    ax.fill_between(h, q75, q90, facecolor=RED, alpha=0.95, hatch="////", edgecolor="white", lw=0, zorder=2)
    ax.plot(h, mean, color=BLK, lw=2.2, zorder=4)
    ax.plot(h, yobs, "o", color=BLK, ms=4, mfc="white", mew=1.4, zorder=5)
    for lvl, lab in LMH:
        if lvl < ytop:
            ax.axhline(lvl, color=BLK, lw=0.8, ls=(0, (1, 2)), zorder=3)
            ax.text(24.4, lvl, lab, va="center", fontsize=8, color=BLK)
    ax2 = ax.twinx()
    ax2.plot(h, pr, color=BLU, lw=1.1, ls="--", zorder=3)
    ax2.set_ylim(0, 1); ax2.set_yticks([0, 0.5, 1])
    ax2.tick_params(axis="y", labelcolor=BLU, labelsize=7); ax2.set_ylabel("P(rain)", color=BLU, fontsize=8)
    ax.set_xlim(0, 24); ax.set_ylim(0, ytop)
    ax.set_xlabel("lead time (h)"); ax.set_ylabel("rain (mm/hr)")

fig, axes = plt.subplots(2, 2, figsize=(11, 7))
for ax, (idx, cap) in zip(axes.flat, PICKS):
    draw(ax, D[idx]); ax.set_title(cap, fontsize=8.5); ax.grid(alpha=0.15)
leg = [Patch(fc=RED, label="0–q75 (solid)"),
       Patch(fc=RED, hatch="////", ec="white", label="q75–q90 (hatch)"),
       Line2D([0], [0], color=BLK, lw=2.2, label="mean"),
       Line2D([0], [0], marker="o", color=BLK, mfc="white", lw=0, label="observed"),
       Line2D([0], [0], color=BLU, lw=1.1, ls="--", label="P(rain)")]
axes.flat[0].legend(handles=leg, loc="upper right", fontsize=6.8, framealpha=0.92)
fig.suptitle("Rain-plume display (§1) — BLENDED distribution (production object, = CRPSS source). "
             "Self-gating: dry cases sit near the floor, no P(rain) gate.", fontsize=9.5)
fig.tight_layout(rect=(0, 0, 1, 0.96))
fig.savefig(f"{HERE}/fig5_display_examples.png", dpi=130)
print("wrote fig5_display_examples.png (blended)")
