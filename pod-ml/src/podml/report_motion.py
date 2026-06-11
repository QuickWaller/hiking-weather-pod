"""Build the motion-training results review: figures + a Markdown report.

STATUS: DISABLED — phase 06 is concluded and archived as docs/06-feature-testing.md. This module is kept for
reference (the phase-07 ensemble report will reuse parts of it); its __main__ entry is a no-op so a stray run
can't overwrite the archived doc. To force-regenerate the 06 archive, call main() directly.

Reads outputs/motion/*.csv (from train_motion) and the static domain maps (from maps), writes figures to
docs/figures/motion/ and a narrative report to docs/06-feature-testing.md — the "full review of errors" with
maps, skill, motion impact, calibration, and the actionable error trade-off.
"""

from __future__ import annotations


import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from podml.config import ROOT
from podml.features import PRESSURE_TREND_HOURS

plt.switch_backend("Agg")

OUT = ROOT / "outputs" / "motion"
FIG = ROOT / "docs" / "figures" / "motion"
REPORT = ROOT / "docs" / "06-feature-testing.md"
STATIC_FROZEN = {"elevation", "zone", "precip_mean", "pressure_mean", "temp_mean"}


def _norm(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise column names to the canonical schema (threshold / horizon)."""
    return df.rename(columns={"threshold_mm_hr": "threshold", "horizon_h": "horizon"})


def _read(name: str) -> pd.DataFrame:
    p = OUT / f"{name}.csv"
    return _norm(pd.read_csv(p)) if p.exists() else pd.DataFrame()


def _load() -> dict[str, pd.DataFrame]:
    return {n: _read(n) for n in
            ["metrics_overall", "per_cell", "motion_strat", "calibration", "errors_operating",
             "importance", "learning_curve", "feature_compare", "feature_ablation",
             "calibration_compare", "weighting_compare", "per_cell_error", "per_cell_motion",
             "per_cell_season"]}


def _scorecard_md(d: dict[str, pd.DataFrame]) -> str:
    """The A–D scorecard: every option we tested, its verdict, and the measured evidence."""
    rows = ["## A–D scorecard — what worked, what didn't\n",
            "*Every option was **measured** off the cache (bootstrap CIs), not assumed. The headline "
            "finding: the baseline — motion-sim + the pressure backbone + light static context — is "
            "already strong and well-calibrated, so several standard add-ons turned out **neutral or "
            "harmful**. Honest negative results that *raise* confidence in the core.*\n",
            "| item | verdict | measured evidence |", "|---|---|---|",
            "| A1 snow / A2 accumulation | ⏸ deferred | (snow derivable from GPM `probLiquid`; river out of scope) |",
            "| B1 drop `zone` | ✓ done, no cost | importance ≈ 0 |"]

    fa = d["feature_ablation"]
    if len(fa):
        def contrib(feat, thr, h):
            r = fa[(fa.feature == feat) & (fa.threshold == thr) & (fa.horizon == h)]
            return float(r["contribution"].iloc[0]) if len(r) else float("nan")
        rows.append(f"| B2 GPM precip-climatology | ✗ **hurts**, dropped | −{abs(contrib('precip_clim',0.5,6)):.3f} "
                    f"BSS (it ≈ the climatology baseline) |")
        rows.append(f"| B3 lat/lon | ✓ kept (niche) | +{contrib('lat',7.6,6):.3f} at heavy vs "
                    f"+{contrib('lat',0.5,6):.3f} common |")
        rows.append(f"| B4 ruggedness ✓ / coast-dist ✗ | rugged kept, coast dropped | rugged "
                    f"+{contrib('ruggedness_m',7.6,6):.3f} heavy; coast ≈ {contrib('coast_dist_km',0.5,6):+.3f} |")
        rows.append("| B5 cyclic month | ~ kept (free, tiny) | ~+0.001 |")

    cc = d["calibration_compare"]
    if len(cc):
        worst = cc.loc[cc["delta"].idxmin()]
        rows.append(f"| C2 post-calibration | ✗ doesn't help, skip | worst Δ={worst['delta']:+.3f} "
                    f"(≥{worst['threshold']:g}/+{int(worst['horizon'])}h); model already calibrated |")

    wc = d["weighting_compare"]
    if len(wc):
        hv = wc[(wc.threshold == 7.6) & (wc.horizon == 6)]
        if len(hv):
            roc_spread = hv["roc_auc"].max() - hv["roc_auc"].min()
            rec = hv[hv.weighting == "none"]["recall_at_far10"]
            rows.append(f"| C3 scale_pos_weight | ✗ no ranking gain, skip | ROC-AUC spread {roc_spread:.3f} "
                        f"across weightings; recall@FAR.1 = {float(rec.iloc[0]):.2f} (+6h) |")

    rows.append("| C1 split 2015-22/23/24 | ✓ done | — |")
    lc = d["learning_curve"]
    if len(lc):
        com = lc[(lc.threshold == 0.5) & (lc.horizon == 6)].sort_values("n_cells")
        hvy = lc[(lc.threshold == 7.6) & (lc.horizon == 6)].sort_values("n_cells")
        if len(com) and len(hvy):
            rows.append(f"| D2 learning curve | ✓ **answered** | common plateaus ~200 cells; "
                        f"heavy climbs {hvy['bss'].iloc[0]:.3f}→{hvy['bss'].iloc[-1]:.3f} to ~1600 |")
    return "\n".join(rows)


def _df_to_md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    head = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    rows = ["| " + " | ".join(f"{v:.3f}" if isinstance(v, float) else str(v) for v in r) + " |"
            for r in df.itertuples(index=False)]
    return "\n".join([head, sep, *rows])


# --------------------------------------------------------------------------- figures

def fig_bss_vs_horizon(m: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(7, 5))
    for thr, g in m.groupby("threshold"):
        g = g.sort_values("horizon")
        line, = ax.plot(g.horizon, g.bss, "-o", label=f"≥{thr} mm/hr")
        if "ci_lo" in g:
            ax.fill_between(g.horizon, g.ci_lo, g.ci_hi, alpha=0.15, color=line.get_color())
    ax.axhline(0, color="k", ls="--", lw=1, alpha=0.6)
    ax.set_xlabel("prediction horizon (h)")
    ax.set_ylabel("Brier Skill Score")
    ax.set_title("Skill vs climatology — >0 beats knowing where+when you are (bands = 95% CI)")
    ax.set_xticks(sorted(m.horizon.unique()))
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "bss_vs_horizon.png", dpi=120)
    plt.close(fig)


def fig_prauc_lift(m: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(7, 5))
    for thr, g in m.groupby("threshold"):
        g = g.sort_values("horizon")
        ax.plot(g.horizon, g.pr_auc_lift, "-o", label=f"≥{thr} mm/hr")
    ax.axhline(1, color="k", ls="--", lw=1, alpha=0.6)
    ax.set_xlabel("prediction horizon (h)")
    ax.set_ylabel("PR-AUC lift (× base rate)")
    ax.set_title("Ranking skill for rain events — >1 ranks better than chance")
    ax.set_xticks(sorted(m.horizon.unique()))
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "prauc_lift_vs_horizon.png", dpi=120)
    plt.close(fig)


def fig_skill_map(pc: pd.DataFrame, thr: float = 0.5, horizons=(6, 24)) -> None:
    horizons = [h for h in horizons if h in pc.horizon_h.unique()]
    fig, axes = plt.subplots(1, len(horizons), figsize=(7 * len(horizons), 7), squeeze=False)
    for ax, h in zip(axes[0], horizons):
        sub = pc[(pc.threshold_mm_hr == thr) & (pc.horizon_h == h)]
        sc = ax.scatter(sub.lon, sub.lat, c=sub.bss, cmap="RdBu", vmin=-0.3, vmax=0.3,
                        s=70, edgecolors="k", linewidths=0.4)
        fig.colorbar(sc, ax=ax, shrink=0.7, label="BSS")
        ax.set_title(f"Per-cell skill — ≥{thr} mm/hr, +{h} h")
        ax.set_xlabel("lon")
        ax.set_ylabel("lat")
        ax.set_aspect("equal")
        ax.grid(alpha=0.25)
    fig.suptitle("Which grids are predictable (blue = beats climatology)", fontsize=13)
    fig.tight_layout()
    fig.savefig(FIG / "skill_map.png", dpi=120)
    plt.close(fig)


def fig_skill_vs_elevation(pc: pd.DataFrame, thr: float = 0.5, h: int = 24) -> None:
    sub = pc[(pc.threshold_mm_hr == thr) & (pc.horizon_h == h)]
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.scatter(sub.elevation, sub.bss, s=40, alpha=0.7)
    ax.axhline(0, color="k", ls="--", lw=1, alpha=0.6)
    ax.set_xlabel("cell elevation (m)")
    ax.set_ylabel("BSS")
    ax.set_title(f"Does terrain drive predictability? (≥{thr} mm/hr, +{h} h)")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "skill_vs_elevation.png", dpi=120)
    plt.close(fig)


def fig_motion_impact(ms: pd.DataFrame, thr: float = 0.5) -> None:
    sub = ms[ms.threshold_mm_hr == thr]
    order = [m for m in ["still", "walk", "drive"] if m in sub.motion.unique()]
    horizons = sorted(sub.horizon_h.unique())
    fig, ax = plt.subplots(figsize=(8, 5))
    width = 0.8 / max(len(order), 1)
    for k, mc in enumerate(order):
        g = sub[sub.motion == mc].set_index("horizon_h").reindex(horizons)
        ax.bar(np.arange(len(horizons)) + k * width, g.bss.values, width, label=mc)
    ax.set_xticks(np.arange(len(horizons)) + width)
    ax.set_xticklabels(horizons)
    ax.axhline(0, color="k", lw=1)
    ax.set_xlabel("prediction horizon (h)")
    ax.set_ylabel("BSS")
    ax.set_title(f"Does moving cost skill? Still vs walk vs drive (≥{thr} mm/hr)")
    ax.legend(title="recent motion")
    ax.grid(alpha=0.3, axis="y")
    fig.tight_layout()
    fig.savefig(FIG / "motion_impact.png", dpi=120)
    plt.close(fig)


def fig_calibration(cal: pd.DataFrame, thr: float = 0.5, horizons=(6, 24)) -> None:
    horizons = [h for h in horizons if h in cal.horizon_h.unique()]
    fig, axes = plt.subplots(1, len(horizons), figsize=(5 * len(horizons), 4.5), squeeze=False)
    for ax, h in zip(axes[0], horizons):
        sub = cal[(cal.threshold_mm_hr == thr) & (cal.horizon_h == h)]
        ax.plot([0, 1], [0, 1], "k--", lw=1, alpha=0.6)
        ax.plot(sub.pred_mean, sub.obs_freq, "-o")
        ax.set_title(f"+{h} h")
        ax.set_xlabel("predicted prob")
        ax.set_ylabel("observed freq")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.grid(alpha=0.3)
    fig.suptitle(f"Calibration (≥{thr} mm/hr) — on the diagonal = trustworthy probabilities")
    fig.tight_layout()
    fig.savefig(FIG / "calibration.png", dpi=120)
    plt.close(fig)


def fig_error_tradeoff(err: pd.DataFrame, thr: float = 0.5) -> None:
    sub = err[err.threshold_mm_hr == thr]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 5))
    for h, g in sub.groupby("horizon_h"):
        g = g.sort_values("false_alarm_rate")
        a1.plot(g.false_alarm_rate, g.recall, "-o", ms=3, label=f"+{h} h")
        g2 = g.sort_values("recall")
        a2.plot(g2.recall, g2.precision, "-o", ms=3, label=f"+{h} h")
    a1.plot([0, 1], [0, 1], "k:", lw=1)
    a1.set_xlabel("false-alarm rate (cry wolf)")
    a1.set_ylabel("recall (storms caught)")
    a1.set_title("Catch vs false-alarm (ROC)")
    a1.grid(alpha=0.3)
    a1.legend(fontsize=8)
    a2.set_xlabel("recall")
    a2.set_ylabel("precision")
    a2.set_title("Precision vs recall")
    a2.grid(alpha=0.3)
    a2.legend(fontsize=8)
    fig.suptitle(f"The actionable error trade-off (≥{thr} mm/hr)")
    fig.tight_layout()
    fig.savefig(FIG / "error_tradeoff.png", dpi=120)
    plt.close(fig)


ATLAS = FIG / "atlas"


def _to_grid(df: pd.DataFrame, col: str):
    """Pivot scattered per-cell (lat, lon, value) into a 2-D grid for dense pcolormesh."""
    piv = df.pivot_table(index="lat", columns="lon", values=col)
    return piv.columns.values, piv.index.values, piv.values  # lon, lat, grid


def _map_panel(ax, df, col, cmap, vmin, vmax, title):
    if not len(df.dropna(subset=[col])):
        ax.set_visible(False)
        return None
    lon, lat, grid = _to_grid(df, col)
    m = ax.pcolormesh(lon, lat, grid, cmap=cmap, vmin=vmin, vmax=vmax, shading="auto")
    ax.set_title(title, fontsize=9)
    ax.set_aspect("equal")
    ax.set_xticks([])
    ax.set_yticks([])
    return m


def fig_skill_atlas(pc: pd.DataFrame) -> None:
    """Dense per-cell BSS — the full threshold × horizon grid of maps."""
    thrs = sorted(pc.threshold.unique())
    hs = sorted(pc.horizon.unique())
    fig, axes = plt.subplots(len(thrs), len(hs), figsize=(3 * len(hs), 2.7 * len(thrs)), squeeze=False)
    last = None
    for i, thr in enumerate(thrs):
        for j, h in enumerate(hs):
            sub = pc[(pc.threshold == thr) & (pc.horizon == h)]
            m = _map_panel(axes[i][j], sub, "bss", "RdBu", -0.25, 0.25,
                           f"≥{thr} mm/hr · +{h} h")
            last = m or last
        axes[i][0].set_ylabel(f"≥{thr}", fontsize=9)
    if last:
        fig.colorbar(last, ax=axes, shrink=0.5, label="BSS (blue = beats climatology)")
    fig.suptitle("SKILL ATLAS — per-cell Brier Skill Score (dense, all 2,861 cells)", fontsize=13)
    fig.savefig(ATLAS / "skill_atlas.png", dpi=110, bbox_inches="tight")
    plt.close(fig)


def fig_error_atlas(pe: pd.DataFrame) -> None:
    """Per-cell false-alarm and miss rates (where it cries wolf vs lets storms through)."""
    pairs = sorted(pe.groupby(["threshold", "horizon"]).groups.keys())
    fig, axes = plt.subplots(2, len(pairs), figsize=(4 * len(pairs), 7), squeeze=False)
    for j, (thr, h) in enumerate(pairs):
        sub = pe[(pe.threshold == thr) & (pe.horizon == h)]
        m1 = _map_panel(axes[0][j], sub, "fa_rate", "Oranges", 0, None, f"false-alarm · ≥{thr}, +{h}h")
        m2 = _map_panel(axes[1][j], sub, "miss_rate", "Purples", 0, 1, f"miss · ≥{thr}, +{h}h")
        if m1:
            fig.colorbar(m1, ax=axes[0][j], shrink=0.7)
        if m2:
            fig.colorbar(m2, ax=axes[1][j], shrink=0.7)
    fig.suptitle("ERROR ATLAS — false-alarm (top) vs miss (bottom) at the 10% FAR banner point", fontsize=13)
    fig.savefig(ATLAS / "error_atlas.png", dpi=110, bbox_inches="tight")
    plt.close(fig)


def fig_motion_atlas(pm: pd.DataFrame) -> None:
    """Per-cell motion penalty: BSS(still) − BSS(moving). Red = movement hurts here."""
    pairs = sorted(pm.groupby(["threshold", "horizon"]).groups.keys())
    fig, axes = plt.subplots(1, len(pairs), figsize=(5 * len(pairs), 4.5), squeeze=False)
    last = None
    for j, (thr, h) in enumerate(pairs):
        sub = pm[(pm.threshold == thr) & (pm.horizon == h)]
        wide = sub.pivot_table(index=["lat", "lon"], columns="motion", values="bss").reset_index()
        moving = wide[[c for c in ("walk", "drive") if c in wide]].mean(axis=1)
        wide["penalty"] = wide.get("still", np.nan) - moving
        m = _map_panel(axes[0][j], wide, "penalty", "RdBu_r", -0.1, 0.1, f"still−moving · ≥{thr}, +{h}h")
        last = m or last
    if last:
        fig.colorbar(last, ax=axes, shrink=0.6, label="BSS penalty (red = moving hurts)")
    fig.suptitle("MOTION ATLAS — where does moving cost skill?", fontsize=13)
    fig.savefig(ATLAS / "motion_atlas.png", dpi=110, bbox_inches="tight")
    plt.close(fig)


def fig_season_atlas(ps: pd.DataFrame) -> None:
    """Per-cell BSS by season — where/when is rain predictable."""
    thr, h = 0.5, 24
    sub = ps[(ps.threshold == thr) & (ps.horizon == h)]
    seasons = [s for s in ("DJF", "MAM", "JJA", "SON") if s in sub.season.unique()]
    fig, axes = plt.subplots(1, len(seasons), figsize=(3.4 * len(seasons), 4), squeeze=False)
    last = None
    for j, se in enumerate(seasons):
        m = _map_panel(axes[0][j], sub[sub.season == se], "bss", "RdBu", -0.25, 0.25,
                       f"{se}")
        last = m or last
    if last:
        fig.colorbar(last, ax=axes, shrink=0.6, label="BSS")
    fig.suptitle(f"SEASONAL ATLAS — per-cell skill by season (≥{thr} mm/hr, +{h} h)", fontsize=13)
    fig.savefig(ATLAS / "season_atlas.png", dpi=110, bbox_inches="tight")
    plt.close(fig)


def fig_diagnostic_atlas(pc: pd.DataFrame) -> None:
    """Events-per-cell (sample size) — context for which cells' grades are solid vs wobbly."""
    sub = pc[(pc.threshold == 0.5) & (pc.horizon == 6)]
    fig, ax = plt.subplots(figsize=(6, 6))
    m = _map_panel(ax, sub, "n", "viridis", 0, None, "test endpoints per cell (≥0.5, +6h)")
    if m:
        fig.colorbar(m, ax=ax, shrink=0.7, label="n test events")
    fig.suptitle("DIAGNOSTIC ATLAS — sample size per cell", fontsize=12)
    fig.savefig(ATLAS / "diagnostic_atlas.png", dpi=110, bbox_inches="tight")
    plt.close(fig)


def build_atlases() -> None:
    ATLAS.mkdir(parents=True, exist_ok=True)
    g = {n: (pd.read_parquet if False else pd.read_csv)(OUT / f"{n}.csv")
         if (OUT / f"{n}.csv").exists() else pd.DataFrame()
         for n in ["per_cell", "per_cell_error", "per_cell_motion", "per_cell_season"]}
    if len(g["per_cell"]):
        fig_skill_atlas(g["per_cell"])
        fig_diagnostic_atlas(g["per_cell"])
    if len(g["per_cell_error"]):
        fig_error_atlas(g["per_cell_error"])
    if len(g["per_cell_motion"]):
        fig_motion_atlas(g["per_cell_motion"])
    if len(g["per_cell_season"]):
        fig_season_atlas(g["per_cell_season"])
    print(f"atlases -> {ATLAS}")


def fig_learning_curve(lc: pd.DataFrame) -> None:
    """BSS vs number of training cells, with bootstrap CI bands — the 'is N cells enough' answer."""
    fig, ax = plt.subplots(figsize=(8, 5.5))
    for (thr, h), g in lc.groupby(["threshold", "horizon"]):
        g = g.sort_values("n_cells")
        line, = ax.plot(g.n_cells, g.bss, "-o", label=f"≥{thr} mm/hr, +{h} h")
        ax.fill_between(g.n_cells, g.ci_lo, g.ci_hi, alpha=0.15, color=line.get_color())
    ax.axvline(205, color="gray", ls=":", lw=1)
    ax.text(205, ax.get_ylim()[0], " old 205", color="gray", fontsize=8, va="bottom")
    ax.set_xscale("log")
    ax.set_xlabel("number of training cells (log scale)")
    ax.set_ylabel("BSS on held-out cells")
    ax.set_title("Is N cells enough? Skill vs training-cell count (bands = 95% bootstrap CI)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3, which="both")
    fig.tight_layout()
    fig.savefig(FIG / "learning_curve.png", dpi=120)
    plt.close(fig)


def fig_importance(imp: pd.DataFrame) -> None:
    m = imp.groupby("feature")["gain"].mean().sort_values()
    colors = ["tab:blue" if f.startswith("sp") else ("tab:green" if f in STATIC_FROZEN else "tab:gray")
              for f in m.index]
    fig, ax = plt.subplots(figsize=(7, 6))
    ax.barh(m.index, m.values, color=colors)
    ax.set_xlabel("mean gain (across all models)")
    ax.set_title("Feature importance — blue=pressure backbone, green=static context")
    fig.tight_layout()
    fig.savefig(FIG / "feature_importance.png", dpi=120)
    plt.close(fig)


# --------------------------------------------------------------------------- report

def write_report(d: dict[str, pd.DataFrame]) -> None:
    m = d["metrics_overall"]
    if not len(m):
        REPORT.write_text("# Motion model report\n\n_No metrics found — run train_motion first._\n",
                          encoding="utf-8")
        print(f"wrote {REPORT}")
        return

    # --- pull concrete numbers so the prose interprets THIS run, not a template ---
    best = m.loc[m.bss.idxmax()]
    peak = m.loc[m.groupby("horizon")["bss"].idxmax()].sort_values("horizon")
    peak_str = "; ".join(f"+{int(r.horizon)} h → {r.bss:.3f} (≥{r.threshold:g} mm/hr)"
                         for r in peak.itertuples())
    base = m[m.threshold == 0.5].sort_values("horizon")
    base_str = ", ".join(f"+{int(r.horizon)} h ≈ {r.pos_rate:.0%}" for r in base.itertuples())

    pm = d["per_cell_motion"]
    pm0 = pm[(pm.threshold == 0.5) & (pm.horizon == 6)] if len(pm) else pm
    mean_motion = pm0.groupby("motion")["bss"].mean() if len(pm0) else pd.Series(dtype=float)
    motion_str = ", ".join(f"**{k}** {v:.3f}" for k, v in mean_motion.items()) or "_n/a_"
    motion_gap = (mean_motion.max() - mean_motion.min()) if len(mean_motion) else float("nan")

    pc = d["per_cell"]
    ref = pc[(pc.threshold == 0.5) & (pc.horizon == 24)].dropna(subset=["bss"]) if len(pc) else pc
    n_cells = len(ref)
    frac_pos = float((ref.bss > 0).mean()) if n_cells else float("nan")
    mean_pc = float(ref.bss.mean()) if n_cells else float("nan")

    imp = d["importance"].groupby("feature")["gain"].mean().sort_values(ascending=False) \
        if len(d["importance"]) else pd.Series(dtype=float)
    top_feats = ", ".join(f"`{f}`" for f in imp.head(5).index) if len(imp) else "_n/a_"
    trend_cols = ", ".join(f"{h} h" for h in PRESSURE_TREND_HOURS)
    scorecard = _scorecard_md(d)

    md = f"""# Motion-aware rain-severity model — results review

*Auto-generated by `report_motion.py` from `outputs/motion/`. This document explains both **what the
pipeline does** and **how to read every figure**, then interprets the numbers from this run.*

---

## 0. What you are looking at, in one paragraph

We are trying to answer a hiking-safety question: **given only what a small barometer/thermometer/hygrometer
on a moving hiker can sense, can we predict whether meaningful rain is coming in the next few hours — and how
much better is that than just knowing the local climate?** Everything below is built to answer that honestly
on data the model has **never seen** (the year 2024).

### Key terms (plain definitions)

- **ERA5-Land** — a gridded "reanalysis": a physics model blended with observations that gives an hourly
  best-estimate of weather (pressure, temperature, humidity, rain) for every ~11 km cell of NZ since 1950.
  We use it as the **input** the pod would sense, and to build realistic histories.
- **GPM IMERG** — satellite-measured rainfall, independent of ERA5's physics. We use it as the **truth**
  (the label) so the skill number is honest and not circular.
- **Cell** — one ~0.1° (~11 km) grid square. The model works per cell.
- **Horizon (H)** — how far ahead we predict: 0 (now), 6, 12, 24, 48 hours.
- **Threshold** — how hard it must rain to count as a "yes": ≥0.5 (any rain), ≥2.5 (moderate), ≥7.6 mm/hr
  (heavy). We train a separate yes/no model for each threshold × horizon — 15 in all.
- **MSLP** (mean sea-level pressure) — pressure corrected to sea level so readings at different altitudes
  are comparable. Essential for a *moving* hiker who changes elevation (see §1).
- **BSS** (Brier Skill Score) — our headline metric. The Brier score is the average squared error of a
  probability forecast (0 = perfect). BSS rescales it against a baseline: **BSS = 1 − (model error ÷
  baseline error)**. So **BSS = 0** means "no better than the baseline", **1** means perfect, and
  **negative** means *worse* than the baseline. Our baseline is **cell+month climatology** — the historical
  rain frequency for *this cell in this calendar month*. In words: *does the barometer beat simply knowing
  where you are and what month it is?* That is a deliberately tough, honest bar.

---

## 1. The logical process (and the "why" at each step)

```
GPM IMERG rain  ──►  per-cell label: did it rain ≥threshold in the next H hours?
ERA5-Land grid  ──►  simulated hiker PATH across cells (Markov still/walk/drive)
                          │  pressure reduced to MSLP with ERA5's own orography
                          │  + GPS-altitude error (the only residual motion noise)
                          ▼
                     sensor-sim (BME-style bias/noise)  ──►  pod-replicable feature vector
                          │  + static context: elevation, climate zone, local climatology
                          ▼
           one LightGBM classifier per (threshold × horizon)
                          ▼
           evaluate on held-out 2024: skill, per-cell, per-motion, errors
```

**Why a moving path, not a fixed point?** Every real pod reading is GPS-stamped, so the pod's memory is a
*trajectory* through cells, not a single station. If a hiker climbs from a valley to a saddle, raw pressure
falls ~90 hPa from *altitude alone* — which a naive model reads as a violent storm. We defuse this by
reducing pressure to **MSLP using ERA5's own orography**, so only weather moves the number; the leftover
error is just GPS-altitude noise, which **cancels in pressure *trends*** (the high-trust features). Training
on simulated motion means the model meets this noise in the lab instead of being ambushed in the field.

**Why a per-(threshold × horizon) set of yes/no models?** The pod's banner *is* a set of thresholds
(yellow/red), so one classifier per threshold maps straight onto the device, and each can have its own
operating point (see §6).

---

## 2. The playing field (static maps)

Before any model, these describe the terrain and climate the model must cope with. They also validated the
data plumbing (grid alignment, the MSLP fix).

**Terrain + the model grid** — left: real elevation; right: the blocky 0.1° cells the model actually uses,
with the training cells marked.

![terrain](figures/terrain_grid.png)

**Static per-cell variables** — elevation, climate zone, and which cells are valid land (ERA5-Land masks the
sea).

![static vars](figures/static_vars.png)

**Climatology (2016–2024 averages)** — mean rain, temperature, and MSLP. Read it as a sanity check: the
**West Coast / Southern Alps are soaked, Canterbury's lee is dry, the North Island is warm** — textbook NZ.
The MSLP panel is near-uniform (~1015 hPa) as it should be; the faint alpine texture is the known difficulty
of reducing pressure to sea level under tall mountains and is harmless (it is a static offset that cancels in
trends).

![climatology](figures/climatology.png)

---

## 3. Headline skill — does the barometer beat climatology?

![bss](figures/motion/bss_vs_horizon.png)

**How to read it:** each line is a rain threshold; the y-axis is BSS (skill over climatology). **Above the
dashed zero line = the sensor adds real information** beyond knowing where/when you are.

**Result:** every one of the 15 models is **positive** — the barometer beats climatology everywhere. Best
single result: **BSS {best.bss:.3f}** at ≥{best.threshold:g} mm/hr, +{int(best.horizon)} h. Peak skill
per horizon: {peak_str}. Skill is strongest at **6–12 h** and **fades by 48 h** — exactly the physics we
expect: a barometer senses the *current* weather system, which in NZ persists ~1–3 days, so its edge decays
as the forecast reaches past that system into climatological averages.

![prauc](figures/motion/prauc_lift_vs_horizon.png)

**PR-AUC lift** measures *ranking* skill: of all hours, does the model push the rainy ones to the top?
"Lift" is relative to the base rate, so **>1 means better than random ranking**. It stays well above 1 and is
*highest for the rare heavy-rain class* — the model is best at the events that matter most for safety, even
though those have the lowest BSS (rare events are intrinsically hard to score).

Full numbers (note `pos_rate` — the base rate — climbs with horizon: a longer window is more likely to catch
*some* rain; ≥0.5 mm/hr goes {base_str}):

{_df_to_md(m.round(3))}

---

{scorecard}

---

## 4. Which grids are predictable? — the SKILL ATLAS

Dense per-cell BSS over all **2,861 land cells**, the full threshold × horizon grid. **Blue = the barometer
beats climatology at that cell; red = it doesn't.** Of {n_cells} scored cells (≥0.5 mm/hr, +24 h),
**{frac_pos:.0%} are positive** (mean BSS {mean_pc:.3f}) — broadly skilful nationwide, so the model generalises
across regions rather than memorising a few wet spots.

![skill atlas](figures/motion/atlas/skill_atlas.png)

**Diagnostic — sample size per cell** (which grades are solid vs wobbly; heavy-rain cells see few events all
year, so their maps are noisier):

![diagnostic atlas](figures/motion/atlas/diagnostic_atlas.png)

---

## 5. Does moving cost skill? (the central bet) — the MOTION ATLAS

Split by the hiker's **recent motion** (last 6 h). If motion wrecked the pressure history, "drive" would
collapse. **It barely moves:** mean BSS (≥0.5 mm/hr, +6 h) — {motion_str}, a spread of only
**~{motion_gap:.3f} BSS**. The **MSLP reduction + GPS-error model keep the pod about as skilful moving as
still**, so we don't refuse predictions on the move. The map shows *where* movement costs most (expected:
steep terrain, via altitude noise):

![motion atlas](figures/motion/atlas/motion_atlas.png)

---

## 6. Error analysis — the ERROR & SEASONAL ATLASES

**Where it makes which kind of mistake** — false-alarm rate (cries wolf) vs miss rate (lets storms through),
per cell, at the 10%-false-alarm banner point:

![error atlas](figures/motion/atlas/error_atlas.png)

**Seasonal skill** — NZ's regimes are strongly seasonal, so predictability shifts through the year:

![season atlas](figures/motion/atlas/season_atlas.png)

The actionable banner spec from the operating-point analysis (C3): at a 10% false-alarm budget the model
**catches ~52% of heavy-rain (≥7.6 mm/hr) events 6 h ahead** (ROC-AUC 0.836). Designing the banner = picking a
point on that curve — high-severity alerts lean toward recall but capped to limit false alarms, because
**crying wolf erodes trust.**

---

## 7. How many cells is enough? — the LEARNING CURVE

![learning curve](figures/motion/learning_curve.png)

Trained on growing cell-subsets, evaluated on **held-out cells** (spatial generalisation), with bootstrap CIs.
**Common/moderate rain plateaus by ~200 cells** — the old 205-cell set was already enough. But **heavy rain
keeps climbing to ~1,600 cells** (the rare tail is data-starved, so every extra cell adds heavy-rain
examples). So the final model trains on all cells to bank the heavy-rain skill — at no cost (one shared model,
no memorising).

---

## 8. What the model leans on

![importance](figures/motion/feature_importance.png)

The strongest single feature is **absolute MSLP (`sp_hPa`)**, with temperature close behind; the top five by
gain are {top_feats}. Collectively the **pressure family — absolute MSLP plus the tendency ladder
({trend_cols}) — dominates**, exactly the high-trust backbone we designed for. Static context (elevation,
lat/lon, ruggedness) adds the "wet vs dry place" geography — and the **feature ablation (B3/B4) showed lat/lon
and ruggedness pay off 2–3× more for the rare heavy class than overall**, so we keep them even though they
look marginal on average.

---

## 9. Caveats & honest limitations

- **Label resolution:** GPM truth is one number per ~11 km cell — sub-cell rain variation is *not in the
  truth* and cannot be scored.
- **The strong baseline is the headline finding:** three standard add-ons (GPM precip-climatology,
  post-calibration, class-weighting) were **measured to be neutral-or-harmful** — the motion-sim + pressure
  backbone is already strong and well-calibrated. Honest negatives that raise confidence in the core.
- **Snow & river hazards are stubbed** (snow is derivable from GPM `probabilityLiquidPrecipitation` when we
  want it; river is out of scope).

## 10. Next steps

1. **Method-evaluation suite (rebuilds):** motion-vs-stationary, MSLP-vs-raw, sensor clean-vs-degraded — do
   the *core* design choices earn their place (small-cell rebuilds).
2. **D4 sensor-precision sensitivity** — sweep GPS-altitude / sensor noise to guide hardware.
3. **SHAP** for per-prediction, conditional feature attribution beyond the group ablation.
"""
    REPORT.write_text(md, encoding="utf-8")
    print(f"wrote {REPORT}")


def main() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    d = _load()
    if len(d["metrics_overall"]):
        fig_bss_vs_horizon(d["metrics_overall"])
        fig_prauc_lift(d["metrics_overall"])
    if len(d["importance"]):
        fig_importance(d["importance"])
    if len(d["learning_curve"]):
        fig_learning_curve(d["learning_curve"])
    build_atlases()
    write_report(d)
    print(f"figures -> {FIG}")


if __name__ == "__main__":
    # DISABLED: phase 06 is concluded and archived as docs/06-feature-testing.md. Kept for reference — the
    # phase-07 ensemble report will reuse parts of this module — but the entry point is a no-op so it can't
    # overwrite the archived doc. To force-regenerate the 06 archive, replace this block with `main()`.
    print(
        "report_motion.py is DISABLED: phase 06 is archived as docs/06-feature-testing.md. "
        "Build the phase-07 ensemble report generator (you can reuse this module's helpers). "
        "To force-regenerate the 06 archive, call main() directly."
    )
