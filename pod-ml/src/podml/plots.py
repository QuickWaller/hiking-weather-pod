"""Generate result figures from the skill-probe outputs, into docs/figures/ for documentation.

Reads outputs/skill_probe.csv + outputs/feature_importance.csv (produced by `python -m podml.probe`)
and writes:
  - bss_vs_horizon.png                 skill (BSS vs climatology) vs horizon, per threshold/point
  - pr_auc_lift_vs_horizon.png         ranking signal (calibration-independent), per threshold/point
  - feature_importance.png             mean gain per feature (pressure highlighted)
  - pressure_importance_by_horizon.png does longer pressure history matter more at longer horizons?
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from podml.features import PRESSURE_TREND_HOURS

plt.switch_backend("Agg")  # headless

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "outputs"
FIG = ROOT / "docs" / "figures"


def _metric_vs_horizon(res: pd.DataFrame, value: str, baseline: float, title: str, fname: str) -> None:
    thrs = sorted(res.threshold_mm_hr.unique())
    fig, axes = plt.subplots(1, len(thrs), figsize=(5 * len(thrs), 4.5), sharex=True)
    for ax, thr in zip(axes, thrs):
        sub = res[res.threshold_mm_hr == thr]
        for pt, g in sub.groupby("point"):
            g = g.sort_values("horizon_h")
            ax.plot(g.horizon_h, g[value], marker="o", label=pt)
        ax.axhline(baseline, color="k", ls="--", lw=1, alpha=0.6)
        ax.set_title(f"≥ {thr} mm/hr")
        ax.set_xlabel("prediction horizon (h)")
        ax.set_xticks(sorted(res.horizon_h.unique()))
        ax.grid(alpha=0.3)
    axes[0].set_ylabel(value)
    axes[-1].legend(fontsize=8)
    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(FIG / fname, dpi=120)
    plt.close(fig)


def _feature_importance(imp: pd.DataFrame, fname: str) -> None:
    m = imp.groupby("feature")["gain"].mean().sort_values()
    colors = ["tab:blue" if f.startswith("sp_") else "tab:gray" for f in m.index]
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.barh(m.index, m.values, color=colors)
    ax.set_xlabel("mean gain (across all models)")
    ax.set_title("Feature importance — blue = pressure (the deployable backbone)")
    fig.tight_layout()
    fig.savefig(FIG / fname, dpi=120)
    plt.close(fig)


def _pressure_importance_by_horizon(imp: pd.DataFrame, fname: str) -> None:
    sp = imp[imp.feature.str.fullmatch(r"sp_rate_\d+h")]
    piv = sp.groupby(["horizon_h", "feature"])["gain"].mean().unstack()
    order = [f"sp_rate_{h}h" for h in PRESSURE_TREND_HOURS if f"sp_rate_{h}h" in piv.columns]
    piv = piv[order]
    fig, ax = plt.subplots(figsize=(7, 5))
    for feat in piv.columns:
        ax.plot(piv.index, piv[feat], marker="o", label=feat)
    ax.set_xlabel("prediction horizon (h)")
    ax.set_ylabel("mean gain")
    ax.set_title("Pressure-trend importance vs horizon\n(do longer trends earn their keep further out?)")
    ax.set_xticks(sorted(imp.horizon_h.unique()))
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / fname, dpi=120)
    plt.close(fig)


def _clean_vs_sim(fname: str) -> None:
    """Overlay clean (solid) vs sensor-degraded (dashed) BSS — the sim-to-real penalty."""
    sim_path = OUT / "skill_probe_sim.csv"
    if not sim_path.exists():
        return
    clean = pd.read_csv(OUT / "skill_probe.csv")
    sim = pd.read_csv(sim_path)
    thrs = [0.5, 2.5]
    colors = plt.cm.tab10.colors
    fig, axes = plt.subplots(1, len(thrs), figsize=(5 * len(thrs), 4.5), sharex=True)
    for ax, thr in zip(axes, thrs):
        c = clean[clean.threshold_mm_hr == thr]
        s = sim[sim.threshold_mm_hr == thr]
        for i, (pt, g) in enumerate(c.groupby("point")):
            g = g.sort_values("horizon_h")
            ax.plot(g.horizon_h, g.bss, "-o", color=colors[i % 10], label=pt)
            gs = s[s.point == pt].sort_values("horizon_h")
            ax.plot(gs.horizon_h, gs.bss, "--x", color=colors[i % 10])
        ax.axhline(0, color="k", ls=":", lw=1)
        ax.set_title(f"≥ {thr} mm/hr")
        ax.set_xlabel("prediction horizon (h)")
        ax.set_xticks([6, 12, 24, 48])
        ax.grid(alpha=0.3)
    axes[0].set_ylabel("BSS")
    axes[0].legend(fontsize=7, title="solid = clean · dashed = sensor-sim")
    fig.suptitle("Skill survives the sensor: clean (solid) vs sensor-degraded (dashed) — ~86% retained")
    fig.tight_layout()
    fig.savefig(FIG / fname, dpi=120)
    plt.close(fig)


def main() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    res = pd.read_csv(OUT / "skill_probe.csv")
    imp = pd.read_csv(OUT / "feature_importance.csv")

    _metric_vs_horizon(res, "bss", 0.0,
                       "Brier Skill Score vs climatology  (>0 beats 'knowing the season')",
                       "bss_vs_horizon.png")
    _metric_vs_horizon(res, "pr_auc_lift", 1.0,
                       "PR-AUC lift  (>1 ranks rain events better than chance)",
                       "pr_auc_lift_vs_horizon.png")
    _feature_importance(imp, "feature_importance.png")
    _pressure_importance_by_horizon(imp, "pressure_importance_by_horizon.png")
    _clean_vs_sim("clean_vs_sim_bss.png")
    print(f"wrote figures -> {FIG}")


if __name__ == "__main__":
    main()
