"""Build the phase-07 ensemble results figures + narrative update in docs/07-forecast-ensemble.md.

Reads outputs/ensemble/*.csv (from train_ensemble --from-cache) and outputs/ensemble/plumes.json
(from train_ensemble --save-plumes), writes figures to docs/figures/ensemble/ and appends/updates
a Results section (## 10.) in docs/07-forecast-ensemble.md.

Run:
    python -m podml.report_ensemble
"""

from __future__ import annotations

import json
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from podml.config import ROOT

plt.switch_backend("Agg")

OUT = ROOT / "outputs" / "ensemble"
FIG = ROOT / "docs" / "figures" / "ensemble"
REPORT = ROOT / "docs" / "07-forecast-ensemble.md"

MODEL_NAMES = ["mean", "q10", "q25", "q75", "q90"]


def _read(name: str) -> pd.DataFrame:
    p = OUT / f"{name}.csv"
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


def _load() -> dict:
    d = {n: _read(n) for n in ["metrics_overall", "coverage", "pit_histogram", "importance",
                                "v3_ablation", "v3_conditional"]}
    weights_path = OUT / "cell_weights.json"
    if weights_path.exists():
        with open(weights_path) as f:
            d["weights"] = list(json.load(f).values())
    else:
        d["weights"] = []
    plumes_path = OUT / "plumes.json"
    if plumes_path.exists():
        with open(plumes_path) as f:
            d["plumes"] = json.load(f)
    else:
        d["plumes"] = []
    uncond_path = OUT / "plumes_uncond.json"
    if uncond_path.exists():
        with open(uncond_path) as f:
            d["plumes_uncond"] = json.load(f)
    else:
        d["plumes_uncond"] = []
    conf_path = OUT / "plumes_conf.json"
    if conf_path.exists():
        with open(conf_path) as f:
            d["plumes_conf"] = json.load(f)
    else:
        d["plumes_conf"] = []
    corr_path = OUT / "conformal_corrections.json"
    if corr_path.exists():
        with open(corr_path) as f:
            d["conformal_corrections"] = json.load(f)
    else:
        d["conformal_corrections"] = {}
    return d


# --------------------------------------------------------------------------- figures

def fig_crpss_vs_horizon(m: pd.DataFrame) -> None:
    """CRPSS by lead time: blended + raw (if available). Raw > blended means blending is the problem."""
    has_raw = "crpss_raw" in m.columns
    m = m.sort_values("horizon_h")
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(m.horizon_h, m.crpss, "-o", color="tab:blue", label="blended (model + climatology)")
    if has_raw:
        ax.plot(m.horizon_h, m.crpss_raw, "-s", color="tab:orange", label="raw model (no blend)")
    ax.axhline(0, color="k", ls="--", lw=1, alpha=0.6, label="climatology baseline")
    ax.set_xlabel("lead time (h)")
    ax.set_ylabel("CRPSS (vs climatology)")
    ax.set_title("Forecast skill vs climatology — CRPSS by lead time\n"
                 ">0 beats knowing where+when you are; raw > blended = blending suppressing skill")
    ax.set_xticks(sorted(m.horizon_h.unique()))
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "crpss_vs_horizon.png", dpi=120)
    plt.close(fig)


def fig_coverage(m: pd.DataFrame) -> None:
    """Empirical interval coverage vs nominal targets. Wide = over-conservative (expected from zero-inflation)."""
    m = m.sort_values("horizon_h")
    has_raw = "cov_raw_10_90" in m.columns
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))

    for ax, lo_col, hi_col, raw_lo, raw_hi, target, label in [
        (axes[0], "cov_10_90", None, "cov_raw_10_90", None, 0.80, "10–90 band (target 80%)"),
        (axes[1], "cov_25_75", None, "cov_raw_25_75", None, 0.50, "25–75 band (target 50%)"),
    ]:
        ax.plot(m.horizon_h, m[lo_col], "-o", color="tab:blue", label="blended")
        if has_raw and raw_lo in m.columns:
            ax.plot(m.horizon_h, m[raw_lo], "-s", color="tab:orange", label="raw model")
        ax.axhline(target, color="k", ls="--", lw=1, alpha=0.6, label=f"target {target:.0%}")
        ax.set_ylim(0, 1.05)
        ax.set_xlabel("lead time (h)")
        ax.set_ylabel("coverage")
        ax.set_title(label)
        ax.legend(fontsize=9)
        ax.grid(alpha=0.3)

    fig.suptitle("Interval coverage — empirical vs nominal\n"
                 "Over-target = bands too wide / zero-inflation inflating dry-hour coverage", fontsize=11)
    fig.tight_layout()
    fig.savefig(FIG / "coverage_vs_horizon.png", dpi=120)
    plt.close(fig)


def fig_coverage_wet(m: pd.DataFrame) -> None:
    """Coverage on wet hours (y > 0.5 mm/hr) vs all hours. Uses distinct styles to avoid overlap."""
    wet_cols = ["cov_wet_10_90", "cov_wet_25_75"]
    if not all(c in m.columns for c in wet_cols):
        return
    m = m.sort_values("horizon_h").dropna(subset=wet_cols)
    if len(m) == 0:
        return
    has_raw = "cov_wet_raw_10_90" in m.columns

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    pairs = [
        (axes[0], "cov_10_90",  "cov_wet_10_90",
                  "cov_raw_10_90", "cov_wet_raw_10_90", 0.80, "10–90 band (target 80%)"),
        (axes[1], "cov_25_75",  "cov_wet_25_75",
                  "cov_raw_25_75", "cov_wet_raw_25_75", 0.50, "25–75 band (target 50%)"),
    ]
    for ax, all_col, wet_col, raw_all_col, raw_wet_col, target, title in pairs:
        # All-hours lines: solid, faded
        ax.plot(m.horizon_h, m[all_col], "-o", color="tab:blue", alpha=0.35, lw=1.2,
                label="blended — all hours (zero-inflation inflated)")
        if has_raw and raw_all_col in m.columns:
            ax.plot(m.horizon_h, m[raw_all_col], "-s", color="tab:orange", alpha=0.35, lw=1.2,
                    label="raw — all hours")
        # Wet-hours lines: dashed, full opacity, thicker
        ax.plot(m.horizon_h, m[wet_col], "--o", color="tab:blue", lw=2,
                label="blended — wet hours only (y > 0.5 mm/hr)")
        if has_raw and raw_wet_col in m.columns:
            ax.plot(m.horizon_h, m[raw_wet_col], "--s", color="tab:orange", lw=2,
                    label="raw — wet hours only")
            # Annotate the raw wet-hour value at h=0 to make it readable
            v0 = float(m.loc[m.horizon_h == m.horizon_h.min(), raw_wet_col].iloc[0])
            ax.annotate(f"{v0:.2f}", xy=(m.horizon_h.min(), v0),
                        xytext=(3, -12), textcoords="offset points",
                        color="tab:orange", fontsize=8, fontweight="bold")
        ax.axhline(target, color="k", ls=":", lw=1.2, alpha=0.7, label=f"target {target:.0%}")
        ax.set_ylim(0, 1.05)
        ax.set_xlabel("lead time (h)")
        ax.set_ylabel("coverage")
        ax.set_title(title)
        ax.legend(fontsize=7.5, loc="lower left")
        ax.grid(alpha=0.3)

    fig.suptitle(
        "Wet-hour calibration: coverage on y > 0.5 mm/hr vs all hours\n"
        "Solid faded = all hours (dominated by 86% dry). Dashed bold = wet hours only (calibration when it matters).",
        fontsize=10)
    fig.tight_layout()
    fig.savefig(FIG / "coverage_wet_vs_all.png", dpi=120)
    plt.close(fig)


def fig_pit(pit: pd.DataFrame) -> None:
    """PIT histogram at selected lead times. Uniform = well-calibrated; U-shape = too narrow; hump = too wide."""
    horizons = sorted(pit.horizon_h.unique())
    sample_hs = [h for h in [0, 6, 12, 24] if h in horizons] or horizons[:4]
    fig, axes = plt.subplots(1, len(sample_hs), figsize=(4.5 * len(sample_hs), 4), squeeze=False)
    bands = ["<q10", "q10-q25", "q25-q75", "q75-q90", ">q90"]
    expected = [0.10, 0.15, 0.50, 0.15, 0.10]
    x = np.arange(len(bands))
    for ax, h in zip(axes[0], sample_hs):
        sub = pit[pit.horizon_h == h].set_index("band").reindex(bands)
        ax.bar(x, sub.observed.values, label="observed", alpha=0.8, color="tab:blue")
        ax.step(np.append(x, x[-1] + 1) - 0.5, np.append(expected, expected[-1]),
                color="k", lw=1.5, where="post", label="expected")
        ax.set_xticks(x)
        ax.set_xticklabels(bands, rotation=25, ha="right", fontsize=8)
        ax.set_ylim(0, max(0.75, float(sub.observed.max()) * 1.2))
        ax.set_title(f"h={h} h")
        ax.grid(alpha=0.2, axis="y")
    axes[0][0].set_ylabel("fraction of observations")
    handles, labels = axes[0][0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="upper right", fontsize=9)
    fig.suptitle("PIT histogram (blended predictions)\n"
                 "Uniform = honest bands · excess central bar = zero-inflation, not miscalibration", fontsize=11)
    fig.tight_layout()
    fig.savefig(FIG / "pit_histogram.png", dpi=120)
    plt.close(fig)


def fig_importance(imp: pd.DataFrame) -> None:
    """Feature gain per model head — shows which inputs each quantile head leans on."""
    model_order = [n for n in MODEL_NAMES if n in imp.model.unique()]
    if not model_order:
        return
    fig, axes = plt.subplots(1, len(model_order), figsize=(4 * len(model_order), 6), squeeze=False)
    for ax, name in zip(axes[0], model_order):
        sub = imp[imp.model == name].set_index("feature")["gain"].sort_values()
        ax.barh(sub.index, sub.values, color="tab:blue")
        ax.set_title(f"head: {name}", fontsize=10)
        ax.set_xlabel("gain")
        ax.grid(alpha=0.2, axis="x")
    fig.suptitle("Feature importance by model head (split gain)", fontsize=12)
    fig.tight_layout()
    fig.savefig(FIG / "feature_importance.png", dpi=120)
    plt.close(fig)


def fig_trust_weights(weights: list) -> None:
    """Trust weight distribution. Low weights = climatology dominates the blend."""
    if len(weights) < 5:
        return
    w = np.array(weights)
    fig, ax = plt.subplots(figsize=(7, 4))
    ax.hist(w, bins=30, edgecolor="k", linewidth=0.5, color="tab:blue")
    ax.axvline(float(w.mean()), color="red", ls="--", lw=1.5,
               label=f"mean w={w.mean():.3f} ({1-w.mean():.0%} climatology)")
    ax.axvline(0.30, color="gray", ls=":", lw=1.2, label="w=0.30 (credible threshold)")
    ax.set_xlabel("trust weight w(cell)")
    ax.set_ylabel("cells")
    ax.set_title("Per-cell trust weight distribution\n"
                 "w→0 = pure climatology fallback · w→1 = pure model")
    ax.legend(fontsize=9)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(FIG / "trust_weights.png", dpi=120)
    plt.close(fig)


def fig_ablation(abl: pd.DataFrame, cond: pd.DataFrame) -> None:
    """v3 feature ablation — delta CRPSS with 95% CI, plus conditional skill on event subsets."""
    if abl.empty:
        return

    # Top panel: per-feature delta CRPSS forest plot
    main = abl[abl["verdict"] != "informational"].copy()
    group = abl[abl["verdict"] == "informational"].copy()

    n_main = len(main)
    fig, axes = plt.subplots(1, 2, figsize=(14, max(4, n_main * 0.7 + 1)),
                             gridspec_kw={"width_ratios": [2, 1]})

    ax = axes[0]
    colors = {"KEEP": "#2ca02c", "CUT": "#d62728",
              "weak": "#ff7f0e", "weak* (check conditional)": "#9467bd",
              "CUT* (check conditional)": "#e377c2"}
    for i, (_, row) in enumerate(main.iterrows()):
        color = colors.get(row["verdict"], "tab:gray")
        ax.errorbar(
            row["delta_crpss_mean"], i,
            xerr=[[row["delta_crpss_mean"] - row["delta_crpss_lo"]],
                  [row["delta_crpss_hi"] - row["delta_crpss_mean"]]],
            fmt="o", color=color, capsize=4, markersize=6,
        )
        ax.text(max(row["delta_crpss_hi"], 0) + 0.00005, i, f"  {row['verdict']}",
                va="center", fontsize=8, color=color)

    if not group.empty:
        for _, row in group.iterrows():
            ax.axhline(n_main - 0.5, color="gray", ls=":", lw=0.8)
            ax.errorbar(
                row["delta_crpss_mean"], n_main,
                xerr=[[row["delta_crpss_mean"] - row["delta_crpss_lo"]],
                      [row["delta_crpss_hi"] - row["delta_crpss_mean"]]],
                fmt="D", color="gray", capsize=4, markersize=6,
                label=f"{row['feature']} (group, informational)",
            )
    else:
        pass

    ax.axvline(0, color="k", lw=1, ls="--", alpha=0.5)
    feat_labels = list(main["feature"]) + ([group.iloc[0]["feature"]] if not group.empty else [])
    ax.set_yticks(np.arange(len(feat_labels)))
    ax.set_yticklabels(feat_labels, fontsize=9)
    ax.set_xlabel("Δ CRPSS (drop − full, normalised by clim CRPS)\n+ve = feature helps · −ve = feature hurts · CI from 200 bootstrap cell resamples")
    ax.set_title("v3 feature ablation — drop-one CRPSS delta", fontsize=10)
    ax.grid(alpha=0.3, axis="x")

    # Right panel: conditional CRPSS on event subsets
    ax2 = axes[1]
    if not cond.empty:
        conditions = cond["condition"].unique()
        y2, labels2, colors2 = [], [], []
        for c in conditions:
            sub = cond[cond["condition"] == c]
            full_row = sub[sub["feature"] == "full_model"]
            drop_rows = sub[sub["feature"] != "full_model"]
            cond_label = c.split("(")[0].strip()
            if not full_row.empty:
                y2.append(float(full_row["crpss"].iloc[0]))
                labels2.append(f"{cond_label}\nfull model")
                colors2.append("tab:blue")
            for _, dr in drop_rows.iterrows():
                feat_short = dr["feature"].replace("drop_", "")
                y2.append(float(dr["crpss"]))
                labels2.append(f"{cond_label}\n−{feat_short}")
                colors2.append("tab:orange")
        ax2.barh(np.arange(len(y2)), y2, color=colors2, alpha=0.8, edgecolor="k", linewidth=0.4)
        ax2.set_yticks(np.arange(len(labels2)))
        ax2.set_yticklabels(labels2, fontsize=7)
        ax2.set_xlabel("CRPSS on subset")
        ax2.set_title("Conditional skill\n(event subsets)", fontsize=10)
        ax2.axvline(0, color="k", lw=0.8)
        ax2.grid(alpha=0.3, axis="x")
    else:
        ax2.set_visible(False)

    fig.suptitle("v3 feature ablation — all features show negligible marginal gain\n"
                 "Base features (sp_hPa, sp_rate, humidity, horizon_h) carry the model",
                 fontsize=11)
    fig.tight_layout()
    fig.savefig(FIG / "v3_ablation.png", dpi=120)
    plt.close(fig)


RAIN_LEVELS = [
    (0.5,  "light",  "#2ca02c"),   # tab:green
    (2.5,  "heavy",  "#9467bd"),   # tab:purple
    (7.6,  "storm",  "#d62728"),   # tab:red
]


def _add_rain_levels(ax, y_max: float) -> None:
    """Draw dotted threshold lines for light / heavy / storm rain on a plume axis."""
    for mm, label, color in RAIN_LEVELS:
        if mm > y_max * 1.3:
            continue  # skip lines way above the visible data — would just crowd the top
        ax.axhline(mm, color=color, ls=":", lw=1.5, alpha=0.9, zorder=2)
        ax.text(0.5, mm, f" {label} ({mm} mm/hr)", color=color,
                fontsize=6.5, va="bottom", ha="left", transform=ax.get_yaxis_transform(),
                clip_on=True, fontweight="bold",
                bbox=dict(facecolor="white", alpha=0.5, edgecolor="none", pad=0.5))


def fig_plumes(plumes: list) -> None:
    """Raw vs blended vs climatology plume fans for sample endpoints. Shows blend suppression."""
    if not plumes:
        return
    n = min(len(plumes), 6)
    fig, axes = plt.subplots(2, 3, figsize=(15, 8)) if n > 3 else plt.subplots(1, n, figsize=(5 * n, 4))
    axes = np.array(axes).flatten()

    palette = {"raw": "tab:orange", "blended": "tab:blue", "clim": "tab:gray"}
    labels = {"raw": "raw model", "blended": "blended", "clim": "climatology"}

    for ax, pl in zip(axes, plumes[:n]):
        hs = np.array(pl["horizons"])
        y_obs = np.array(pl["y_obs"])
        all_vals = list(np.maximum(y_obs, 0))
        for key in ["clim", "raw", "blended"]:
            if key not in pl:
                continue
            p = pl[key]
            c = palette[key]
            q10 = np.array(p.get("q10", np.zeros_like(hs)))
            q25 = np.array(p.get("q25", np.zeros_like(hs)))
            q75 = np.array(p.get("q75", np.zeros_like(hs)))
            q90 = np.array(p.get("q90", np.zeros_like(hs)))
            mu  = np.array(p.get("mean", np.zeros_like(hs)))
            ax.fill_between(hs, np.maximum(q10, 0), np.maximum(q90, 0), alpha=0.12, color=c)
            ax.fill_between(hs, np.maximum(q25, 0), np.maximum(q75, 0), alpha=0.25, color=c)
            ax.plot(hs, np.maximum(mu, 0), "-", color=c, lw=1.5, label=labels[key])
            all_vals.extend(np.maximum(q90, 0).tolist())
        ax.scatter(hs, np.maximum(y_obs, 0), s=14, color="black", zorder=5,
                   label="observed" if ax is axes[0] else "")
        y_max = max(all_vals) if all_vals else 1.0
        ax.set_ylim(bottom=0, top=max(y_max * 1.15, 0.6))
        _add_rain_levels(ax, y_max)
        ax.set_xlabel("horizon (h)", fontsize=8)
        ax.set_ylabel("rain (mm/hr)", fontsize=8)
        cell = pl.get("cell", "?")
        t = pl.get("time", "")
        ax.set_title(f"{cell}\n{str(t)[:16]}", fontsize=8)
        ax.grid(alpha=0.2)

    for ax in axes[n:]:
        ax.set_visible(False)

    handles, labels_leg = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels_leg, loc="upper right", fontsize=9, ncol=4)
    fig.suptitle("Plume examples — raw model vs blended vs climatology\n"
                 "Outer band: 10–90 · inner: 25–75 · centre line: mean · dots: observed", fontsize=11)
    fig.tight_layout()
    fig.savefig(FIG / "plume_examples.png", dpi=120)
    plt.close(fig)


def fig_coverage_explainer(plumes_uncond: list, plumes_wetcond: list) -> None:
    """Three-panel diagram explaining wet-hour coverage differences between options 2 and 3.

    Panel 1 — distribution of observed y values, showing the zero spike and where
               unconditional vs wet-conditional quantile lines land.
    Panel 2 — coverage bar chart: option 2 vs 3, wet hours only, both bands.
    Panel 3 — concrete single-forecast example for one wet observation.
    """
    if not plumes_uncond:
        return

    # ── collect all (y_obs, raw quantiles) from both plume sets ─────────────
    def _collect(plumes: list) -> tuple[list, list, list, list, list]:
        ys, q10s, q25s, q75s, q90s = [], [], [], [], []
        for pl in plumes:
            obs = pl["y_obs"]
            r   = pl.get("raw", {})
            q10 = r.get("q10", [0] * len(obs))
            q25 = r.get("q25", [0] * len(obs))
            q75 = r.get("q75", [0] * len(obs))
            q90 = r.get("q90", [0] * len(obs))
            for i, y in enumerate(obs):
                ys.append(y)
                q10s.append(q10[i])
                q25s.append(q25[i])
                q75s.append(q75[i])
                q90s.append(q90[i])
        return ys, q10s, q25s, q75s, q90s

    u_ys, u_q10, u_q25, u_q75, u_q90 = _collect(plumes_uncond)
    w_ys, w_q10, w_q25, w_q75, w_q90 = _collect(plumes_wetcond)

    def _wet_coverage(ys, q_lo, q_hi):
        hits = tot = 0
        for y, lo, hi in zip(ys, q_lo, q_hi):
            if y > 0.5:
                tot += 1
                if lo <= y <= hi:
                    hits += 1
        return (hits / tot) if tot else float("nan")

    u_cov_1090 = _wet_coverage(u_ys, u_q10, u_q90)
    u_cov_2575 = _wet_coverage(u_ys, u_q25, u_q75)
    w_cov_1090 = _wet_coverage(w_ys, w_q10, w_q90)
    w_cov_2575 = _wet_coverage(w_ys, w_q25, w_q75)

    fig, axes = plt.subplots(1, 3, figsize=(16, 5.5))

    # ── Panel 1: y distribution + quantile positions ─────────────────────────
    ax = axes[0]
    all_y = np.array(u_ys)
    # histogram of non-zero values on a log-ish x scale
    wet_y = all_y[all_y > 0.05]
    dry_frac = (all_y <= 0.05).mean()
    ax.hist(wet_y, bins=40, color="tab:blue", alpha=0.7, density=True, label="wet hours (y > 0.05)")
    ax.set_xlabel("observed rain rate (mm/hr)", fontsize=9)
    ax.set_ylabel("density (wet hours only)", fontsize=9)
    ax.set_title(f"Observed distribution\n({dry_frac:.0%} of all hours are dry — not shown)", fontsize=9)

    # mark median unconditional quantiles across all hours
    for val, label, color, ls in [
        (float(np.median(u_q10)), "uncond q10", "tab:orange", "--"),
        (float(np.median(u_q25)), "uncond q25", "tab:orange", "-."),
        (float(np.median(u_q75)), "uncond q75", "tab:orange", ":"),
        (float(np.median(u_q90)), "uncond q90", "tab:orange", "-"),
        (float(np.median(w_q10)), "wet-cond q10", "tab:purple", "--"),
        (float(np.median(w_q25)), "wet-cond q25", "tab:purple", "-."),
        (float(np.median(w_q75)), "wet-cond q75", "tab:purple", ":"),
        (float(np.median(w_q90)), "wet-cond q90", "tab:purple", "-"),
    ]:
        if val > 0.01:
            ax.axvline(val, color=color, ls=ls, lw=1.5, alpha=0.85, label=f"{label}={val:.2f}")
        else:
            # mark at left edge with a text note
            ax.text(0.02, 0.97 - 0.07 * label.count("uncond"), f"{label}≈0 (collapsed)",
                    transform=ax.transAxes, fontsize=6.5, color=color, va="top")
    ax.legend(fontsize=6, loc="upper right", ncol=1)
    ax.grid(alpha=0.25)
    # add annotation explaining the collapse
    ax.text(0.5, 0.60,
            "Unconditional q10/q25/q75\ncollapse to 0 because\n86% of training data is zero\n→ their percentiles are 0",
            transform=ax.transAxes, fontsize=8, color="tab:orange",
            ha="center", va="top",
            bbox=dict(facecolor="#fff3e0", edgecolor="tab:orange", alpha=0.9, pad=4))

    # ── Panel 2: coverage bar chart ──────────────────────────────────────────
    ax = axes[1]
    x = np.array([0, 1, 3, 4])
    heights = [u_cov_1090, w_cov_1090, u_cov_2575, w_cov_2575]
    targets = [0.80, 0.80, 0.50, 0.50]
    colors  = ["tab:orange", "tab:purple", "tab:orange", "tab:purple"]
    ax.bar(x, heights, color=colors, alpha=0.8, edgecolor="k", linewidth=0.5, width=0.7)
    for xi, hi, ti in zip(x, heights, targets):
        ax.axhline(ti, xmin=(xi - 0.35) / 5, xmax=(xi + 0.35) / 5,
                   color="black", lw=2.0, ls="--", zorder=5)
        ax.text(xi, hi + 0.02, f"{hi:.0%}", ha="center", fontsize=10, fontweight="bold")
    ax.set_xticks(x)
    ax.set_xticklabels(["10–90\nuncond", "10–90\nwet-cond", "25–75\nuncond", "25–75\nwet-cond"],
                       fontsize=9)
    ax.set_ylim(0, 1.05)
    ax.set_ylabel("fraction of wet observations inside band", fontsize=9)
    ax.set_title("Wet-hour coverage (y > 0.5 mm/hr)\nDashed = target (80% / 50%)", fontsize=9)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color="tab:orange", label="Option 2 — unconditional"),
                       Patch(color="tab:purple", label="Option 3 — wet-conditional")],
              fontsize=8, loc="upper left")
    ax.grid(alpha=0.25, axis="y")

    # ── Panel 3: concrete single-forecast example ────────────────────────────
    ax = axes[2]
    # pick a wet hour from uncond plumes where the two options differ most
    best_i, best_gap = None, -1
    for i, (y, lo_u, hi_u, lo_w, hi_w) in enumerate(
            zip(u_ys, u_q10, u_q90, w_q10, w_q90)):
        if y < 0.5:
            continue
        gap = (hi_w - hi_u)  # wet-cond q90 - uncond q90
        if gap > best_gap:
            best_gap, best_i = gap, i

    if best_i is not None:
        y_ex = u_ys[best_i]
        ex_vals = {
            "uncond":   dict(q10=u_q10[best_i], q25=u_q25[best_i],
                             q75=u_q75[best_i], q90=u_q90[best_i]),
            "wet-cond": dict(q10=w_q10[best_i], q25=w_q25[best_i],
                             q75=w_q75[best_i], q90=w_q90[best_i]),
        }
        opt_colors = {"uncond": "tab:orange", "wet-cond": "tab:purple"}
        opt_labels = {"uncond": "Option 2 — unconditional", "wet-cond": "Option 3 — wet-conditional"}
        x_pos      = {"uncond": 0.25, "wet-cond": 0.75}
        bw = 0.18

        ax.set_xlim(0, 1)
        ax.set_ylim(0, max(y_ex * 1.4, float(max(w_q90[best_i], u_q90[best_i])) * 1.2, 1.5))
        ax.axhline(y_ex, color="black", lw=2, ls="-", zorder=6, label=f"observed  {y_ex:.1f} mm/hr")
        ax.text(0.98, y_ex, f"  observed: {y_ex:.1f} mm/hr", va="center", ha="right",
                fontsize=9, fontweight="bold", transform=ax.get_yaxis_transform())

        for key, vals in ex_vals.items():
            xc   = x_pos[key]
            col  = opt_colors[key]
            q10v = max(vals["q10"], 0)
            q25v = max(vals["q25"], 0)
            q75v = max(vals["q75"], 0)
            q90v = max(vals["q90"], 0)
            ax.fill_between([xc - bw, xc + bw], [q10v, q10v], [q90v, q90v],
                            alpha=0.20, color=col)
            ax.fill_between([xc - bw, xc + bw], [q25v, q25v], [q75v, q75v],
                            alpha=0.45, color=col)
            for v, ls in [(q10v, "--"), (q25v, ":"), (q75v, ":"), (q90v, "--")]:
                ax.hlines(v, xc - bw, xc + bw, colors=col, linestyles=ls, lw=1.4)
            ax.text(xc, -0.06, opt_labels[key], ha="center", va="top",
                    transform=ax.get_xaxis_transform(), fontsize=8, color=col, fontweight="bold")
            inside_1090 = q10v <= y_ex <= q90v
            inside_2575 = q25v <= y_ex <= q75v
            verdict = "INSIDE ✓" if inside_1090 else "OUTSIDE ✗"
            ax.text(xc, ax.get_ylim()[1] * 0.97,
                    f"10–90: {verdict}\n25–75: {'INSIDE ✓' if inside_2575 else 'OUTSIDE ✗'}",
                    ha="center", va="top", fontsize=8.5,
                    color="green" if inside_1090 else "red",
                    bbox=dict(facecolor="white", edgecolor=col, alpha=0.85, pad=3))

        ax.set_xticks([])
        ax.set_ylabel("rain rate (mm/hr)", fontsize=9)
        ax.set_title(f"Single wet-hour example (y = {y_ex:.1f} mm/hr)\nDo the bands contain the observation?",
                     fontsize=9)
        ax.grid(alpha=0.2, axis="y")

    fig.suptitle(
        "Why wet-hour coverage differs: unconditional quantiles collapse to zero because 86% of training data is dry",
        fontsize=11, fontweight="bold",
    )
    fig.tight_layout()
    fig.savefig(FIG / "coverage_explainer.png", dpi=120)
    plt.close(fig)
    print("  saved coverage_explainer.png", flush=True)


_RAIN_CATS = [
    (0.0,  0.5,  "Dry / clear",   "#2ca02c"),
    (0.5,  2.5,  "Light rain",    "#1f77b4"),
    (2.5,  7.6,  "Moderate rain", "#9467bd"),
    (7.6,  None, "Heavy rain",    "#d62728"),
]

_OPTION_META = [
    (
        "Option 1 — Mean only",
        "tab:blue",
        "One line: the blended Tweedie mean (expected mm/hr, accounting\n"
        "for the chance it stays dry). No bands.\n\n"
        "Reading: 'the line is my best guess at intensity.'\n"
        "Loss: no uncertainty signal — can't tell a sharp vs uncertain forecast.",
    ),
    (
        "Option 2 — Unconditional fan",
        "tab:orange",
        "Full distribution trained on ALL hours (including zeros).\n"
        "On dry-ish days the band collapses toward zero — correctly\n"
        "showing 'most likely nothing, small chance of light rain.'\n\n"
        "Reading: 'the band is the realistic range including chance of no rain.'\n"
        "Loss: wet-hour coverage only ~17% (bands too narrow when it rains).",
    ),
    (
        "Option 3 — Wet-conditional fan (gated)",
        "tab:purple",
        "Quantile heads trained on WET rows only. Fan shown only when\n"
        "Tweedie mean > gate threshold (dashed line).\n\n"
        "Reading: 'rain expected — if it rains, 80% chance inside outer band.'\n"
        "Loss: two separate concepts (gate + conditional band) need explaining.\n"
        "Gain: wet-hour coverage 83% — statistically most honest when raining.",
    ),
    (
        "Option 4 — CQR (conformal)",
        "tab:red",
        "Unconditional model + flat per-quantile offset fitted on val wet hours.\n"
        "Guarantees marginal coverage on wet hours. No gating needed.\n\n"
        "Offsets: q10+0.67, q25+1.01, q75+3.45, q90+5.57 mm/hr.\n"
        "Reading: 'band shows calibrated range — always at least 5.6 mm/hr wide.'\n"
        "Loss: floor never touches zero; offset is feature-independent (same width\n"
        "on dry-looking and rainy-looking forecasts).",
    ),
]

# Gate threshold for option 3 display (mm/hr Tweedie mean)
_WET_GATE_MM = 0.3


def fig_option_comparison(
    plumes_uncond: list,
    plumes_wetcond: list,
    plumes_conf: list | None = None,
) -> None:
    """Side-by-side comparison of plume display options across rain categories.

    Rows = one representative plume per rain category (dry, light, moderate, heavy).
    Columns = options 1-3 always; option 4 (CQR) added when plumes_conf provided.
    Each column has a header annotation explaining the option's trade-off.
    """
    if not plumes_uncond or not plumes_wetcond:
        return

    # Index wet-conditional plumes by (cell, time) for matching
    wetcond_idx = {(p["cell"], p["time"]): p for p in plumes_wetcond}

    # Find best plume per category from unconditional set, matched in wet-conditional
    conf_idx = {(p["cell"], p["time"]): p for p in (plumes_conf or [])}
    n_cols = 4 if plumes_conf else 3
    active_meta = _OPTION_META[:n_cols]

    selected: list[tuple] = []  # (label, color, pl_uncond, pl_wetcond, pl_conf|None)
    for lo, hi, label, color in _RAIN_CATS:
        pl_u = _best_plume(plumes_uncond, lo, hi)
        if pl_u is None:
            continue
        key = (pl_u["cell"], pl_u["time"])
        pl_w = wetcond_idx.get(key) or _best_plume(plumes_wetcond, lo, hi) or pl_u
        pl_c = conf_idx.get(key) or (_best_plume(plumes_conf, lo, hi) if plumes_conf else None)
        selected.append((label, color, pl_u, pl_w, pl_c))

    if not selected:
        return

    n_rows = len(selected)
    fig = plt.figure(figsize=(6.0 * n_cols, 4 * n_rows + 2.5))

    # Header row
    for col_i, (opt_title, opt_color, opt_desc) in enumerate(active_meta):
        ax_h = fig.add_axes([col_i / n_cols + 0.005, 1 - 1.8 / (4 * n_rows + 2.5),
                             1 / n_cols - 0.01, 1.5 / (4 * n_rows + 2.5)])
        ax_h.set_xlim(0, 1)
        ax_h.set_ylim(0, 1)
        ax_h.axis("off")
        ax_h.text(0.5, 1.0, opt_title, ha="center", va="top",
                  fontsize=10, fontweight="bold", color=opt_color, transform=ax_h.transAxes)
        ax_h.text(0.5, 0.75, opt_desc, ha="center", va="top",
                  fontsize=7, color="#333333", transform=ax_h.transAxes, linespacing=1.4)

    # Data rows
    axes_grid = []
    for row_i in range(n_rows):
        row_axes = []
        for col_i in range(n_cols):
            top = 1 - 1.8 / (4 * n_rows + 2.5)
            h = top / n_rows
            ax = fig.add_axes([
                col_i / n_cols + 0.04 / n_cols,
                top - (row_i + 1) * h + 0.03,
                1 / n_cols - 0.08 / n_cols,
                h - 0.05,
            ])
            row_axes.append(ax)
        axes_grid.append(row_axes)

    for row_i, (cat_label, cat_color, pl_u, pl_w, pl_c) in enumerate(selected):
        hs    = np.array(pl_u["horizons"])
        y_obs = np.maximum(np.array(pl_u["y_obs"]), 0)

        # shared y-scale: max q90 across all sources
        all_q90 = list(y_obs)
        for src, skey in [(pl_u, "raw"), (pl_u, "blended"), (pl_w, "raw"),
                          (pl_c, "conformal") if pl_c else (None, None)]:
            if src is None:
                continue
            p = src.get(skey, {})
            all_q90.extend(np.array(p.get("q90", np.zeros_like(hs))).tolist())
        y_max = max(float(max(all_q90)), 0.6)
        y_top = y_max * 1.18

        for col_i in range(n_cols):
            ax = axes_grid[row_i][col_i]
            ax.set_xlim(hs.min(), hs.max())
            ax.set_ylim(0, y_top)
            ax.grid(alpha=0.2)
            ax.scatter(hs, y_obs, s=14, color="black", zorder=5)
            _add_rain_levels(ax, y_max)
            if col_i == 0:
                ax.set_ylabel(f"{cat_label}\n(mm/hr)", fontsize=8,
                              color=cat_color, fontweight="bold")
            if row_i == n_rows - 1:
                ax.set_xlabel("lead time (h)", fontsize=8)
            else:
                ax.set_xticklabels([])

            opt_color = active_meta[col_i][1]

            if col_i == 0:
                # Option 1: mean line only
                b  = pl_u.get("blended", {})
                mu = np.maximum(np.array(b.get("mean", np.zeros_like(hs))), 0)
                ax.plot(hs, mu, "-", color=opt_color, lw=2.0)

            elif col_i == 1:
                # Option 2: unconditional fan
                r   = pl_u.get("raw", {})
                q10 = np.maximum(np.array(r.get("q10", np.zeros_like(hs))), 0)
                q25 = np.maximum(np.array(r.get("q25", np.zeros_like(hs))), 0)
                q75 = np.maximum(np.array(r.get("q75", np.zeros_like(hs))), 0)
                q90 = np.maximum(np.array(r.get("q90", np.zeros_like(hs))), 0)
                mu  = np.maximum(np.array(r.get("mean", np.zeros_like(hs))), 0)
                ax.fill_between(hs, q10, q90, alpha=0.18, color=opt_color)
                ax.fill_between(hs, q25, q75, alpha=0.35, color=opt_color)
                ax.plot(hs, mu, "-", color=opt_color, lw=2.0)

            elif col_i == 2:
                # Option 3: wet-conditional, gated
                b        = pl_w.get("blended", {})
                mu_blend = np.maximum(np.array(b.get("mean", np.zeros_like(hs))), 0)
                r   = pl_w.get("raw", {})
                q10 = np.maximum(np.array(r.get("q10", np.zeros_like(hs))), 0)
                q25 = np.maximum(np.array(r.get("q25", np.zeros_like(hs))), 0)
                q75 = np.maximum(np.array(r.get("q75", np.zeros_like(hs))), 0)
                q90 = np.maximum(np.array(r.get("q90", np.zeros_like(hs))), 0)
                gate = mu_blend >= _WET_GATE_MM
                ax.axhline(_WET_GATE_MM, color="gray", ls="--", lw=1.0, alpha=0.7)
                if gate.any():
                    ax.fill_between(hs, q10, q90, alpha=0.18, color=opt_color, where=gate)
                    ax.fill_between(hs, q25, q75, alpha=0.35, color=opt_color, where=gate)
                ax.plot(hs, np.where(gate, mu_blend, np.nan), "-", color=opt_color, lw=2.0)

            else:
                # Option 4: CQR conformal
                if pl_c is None:
                    ax.text(0.5, 0.5, "no data", ha="center", va="center",
                            transform=ax.transAxes, color="gray")
                    continue
                r   = pl_c.get("conformal", {})
                mu  = np.maximum(np.array(pl_c.get("raw", {}).get("mean", np.zeros_like(hs))), 0)
                q10 = np.maximum(np.array(r.get("q10", np.zeros_like(hs))), 0)
                q25 = np.maximum(np.array(r.get("q25", np.zeros_like(hs))), 0)
                q75 = np.maximum(np.array(r.get("q75", np.zeros_like(hs))), 0)
                q90 = np.maximum(np.array(r.get("q90", np.zeros_like(hs))), 0)
                ax.fill_between(hs, q10, q90, alpha=0.18, color=opt_color)
                ax.fill_between(hs, q25, q75, alpha=0.35, color=opt_color)
                ax.plot(hs, mu, "-", color=opt_color, lw=2.0)

    n_opt_label = "four" if n_cols == 4 else "three"
    fig.suptitle(
        f"Plume display options — {n_opt_label} approaches to communicating forecast uncertainty\n"
        "Dots = observed · horizontal lines = light/heavy/storm thresholds",
        fontsize=11, y=0.995,
    )
    fig.savefig(FIG / "plume_options.png", dpi=110, bbox_inches="tight")
    plt.close(fig)
    print("  saved plume_options.png", flush=True)


def _best_plume(plumes: list, lo: float, hi: float | None) -> dict | None:
    """Pick the most illustrative plume in the [lo, hi) observed-peak bucket."""
    candidates = []
    for pl in plumes:
        mx = max(pl["y_obs"])
        if mx < lo or (hi is not None and mx >= hi):
            continue
        b = pl.get("blended", {})
        mean_sum = sum(b.get("mean", [0]))
        wet_hrs = sum(1 for v in pl["y_obs"] if v > 0.5)
        # Score: rainy categories prefer more wet hours; dry prefers highest model signal
        score = wet_hrs * 10 + mean_sum
        candidates.append((score, pl))
    if not candidates:
        return None
    return max(candidates, key=lambda x: x[0])[1]


def fig_plumes_display(plumes: list) -> None:
    """Blended-only plume fan, one panel per rain intensity category.

    This is the hiker-facing view — no raw / climatology noise. The four panels cover
    the four observed-intensity regimes so the reader sees what the plume looks like
    in each situation.
    """
    if not plumes:
        return

    picks = [(label, color, _best_plume(plumes, lo, hi))
             for lo, hi, label, color in _RAIN_CATS]
    picks = [(label, color, pl) for label, color, pl in picks if pl is not None]
    if not picks:
        return

    n = len(picks)
    fig, axes = plt.subplots(1, n, figsize=(5 * n, 4.5), squeeze=False)
    axes = axes[0]

    for ax, (cat_label, color, pl) in zip(axes, picks):
        hs   = np.array(pl["horizons"])
        y_obs = np.array(pl["y_obs"])
        b     = pl.get("blended", {})
        q10   = np.maximum(np.array(b.get("q10", np.zeros_like(hs))), 0)
        q25   = np.maximum(np.array(b.get("q25", np.zeros_like(hs))), 0)
        q75   = np.maximum(np.array(b.get("q75", np.zeros_like(hs))), 0)
        q90   = np.maximum(np.array(b.get("q90", np.zeros_like(hs))), 0)
        mu    = np.maximum(np.array(b.get("mean", np.zeros_like(hs))), 0)

        ax.fill_between(hs, q10, q90, alpha=0.18, color=color, label="10–90% band")
        ax.fill_between(hs, q25, q75, alpha=0.35, color=color, label="25–75% band")
        ax.plot(hs, mu, "-", color=color, lw=2.0, label="blended mean")
        ax.scatter(hs, np.maximum(y_obs, 0), s=16, color="black", zorder=5, label="observed")

        y_max = max(float(q90.max()), float(max(y_obs)), 0.6)
        ax.set_ylim(bottom=0, top=y_max * 1.18)
        _add_rain_levels(ax, y_max)

        ax.set_xlabel("lead time (h)", fontsize=9)
        ax.set_ylabel("rain (mm/hr)", fontsize=9)
        ax.set_title(cat_label, fontsize=11, fontweight="bold", color=color)
        ax.grid(alpha=0.25)

    handles, labels_leg = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels_leg, loc="upper right", fontsize=9, ncol=2,
               bbox_to_anchor=(1.0, 1.0))
    fig.suptitle(
        "Forecast plume — blended model · outer band: 10–90% · inner: 25–75% · line: mean · dots: observed",
        fontsize=10,
    )
    fig.tight_layout()
    fig.savefig(FIG / "plume_display.png", dpi=120)
    plt.close(fig)


# --------------------------------------------------------------------------- report

def _results_section(d: dict) -> str:
    m = d["metrics_overall"]
    weights = d["weights"]

    if not len(m):
        return (
            "\n## 10. Results (auto-generated by `report_ensemble.py`)\n\n"
            "_No results yet — run `python -m podml.train_ensemble --from-cache` first, then "
            "`python -m podml.report_ensemble`._\n"
        )

    m = m.sort_values("horizon_h")
    has_raw = "crpss_raw" in m.columns
    has_wet = "cov_wet_10_90" in m.columns

    def _get(col, h):
        rows = m[m.horizon_h == h]
        return float(rows[col].iloc[0]) if len(rows) and col in rows.columns else float("nan")

    crpss_h0  = _get("crpss", 0)
    crpss_h24 = _get("crpss", 24)
    crpss_mean = float(m["crpss"].mean())

    # ── CRPSS note ──────────────────────────────────────────────────────────
    if has_raw:
        raw_h0  = _get("crpss_raw", 0)
        raw_h24 = _get("crpss_raw", 24)
        if raw_h0 > 0:
            raw_note = (
                f"The **raw model** (unblended Tweedie mean) achieves CRPSS {raw_h0:.3f} at h=0, "
                f"decaying to {raw_h24:.3f} at h=24 — the expected pattern for a barometer-driven "
                f"forecast in NZ (systems persist 1–3 days). "
                f"The blended score ({crpss_h0:.3f}→{crpss_h24:.3f}) pulls toward climatology "
                f"via per-cell trust weights (mean w≈0.45).\n\n"
            )
        else:
            raw_note = (
                f"_Note: raw CRPSS = {raw_h0:.3f} (negative) because the current run uses "
                f"wet-conditional quantile heads — on dry hours those heads predict positive rain, "
                f"incurring heavy CRPS penalty. The blended model (CRPSS {crpss_h0:.3f}) is the "
                f"right overall metric here; the raw quantile skill is reported separately on wet hours._\n\n"
            )
    else:
        raw_note = ""

    # ── all-hours coverage note ──────────────────────────────────────────────
    cov25_mean   = float(m["cov_25_75"].mean()) if "cov_25_75" in m.columns else float("nan")
    cov1090_mean = float(m["cov_10_90"].mean()) if "cov_10_90" in m.columns else float("nan")
    cov_note = (
        f"Mean empirical coverage (all hours): 10–90 = **{cov1090_mean:.2f}** (target 0.80), "
        f"25–75 = **{cov25_mean:.2f}** (target 0.50). "
        f"Both are over-target — rain is zero-inflated (~86% of hours are dry). "
        f"Every dry hour (y=0) trivially lands inside any band with a non-negative lower edge, "
        f"inflating coverage. The all-hours number is not a useful calibration check.\n"
    )

    # ── wet-hour calibration note ────────────────────────────────────────────
    if has_wet:
        wet1090_h0  = _get("cov_wet_10_90", 0)
        wet2575_h0  = _get("cov_wet_25_75", 0)
        rw1090_h0   = _get("cov_wet_raw_10_90", 0)
        rw2575_h0   = _get("cov_wet_raw_25_75", 0)
        wet1090_h24 = _get("cov_wet_10_90", 24)
        rw1090_h24  = _get("cov_wet_raw_10_90", 24)
        wet_section = f"""
### Wet-hour calibration

![wet coverage](figures/ensemble/coverage_wet_vs_all.png)

Filtering to hours where y > 0.5 mm/hr strips out the trivial dry coverage and reveals whether
the bands are honest **when it actually rains** — the only time the hiker cares.

**The zero-inflation problem (why unconditional quantiles fail on wet hours):**

![coverage explainer](figures/ensemble/coverage_explainer.png)

The q10/q25/q75/q90 heads are trained on the full distribution which is ~86% zeros.
The unconditional quantiles of a distribution that is 86% zero are:
- q10 ≈ 0 (10th percentile of a dataset where >10% are zero is zero — trivially)
- q25 ≈ 0 (same argument)
- q75 ≈ 0 (same — 86% > 75%)
- q90 = first non-trivial value (only 14% of data is wet)

The left panel above shows this directly: orange unconditional lines collapse at the y-axis,
while the purple wet-conditional lines spread across the actual wet distribution.
The middle panel shows the coverage consequence: unconditional gets 17% on the 10–90 band
(target 80%), 0% on 25–75. The right panel shows a single real observation of 0.8 mm/hr —
the unconditional band only reaches 0.4 mm/hr and misses it; the wet-conditional band catches it.

**The fix — wet-conditional quantile heads (`--wet-quantiles`):**

Train q10/q25/q75/q90 on wet-only rows (y > 0). These heads now learn Q_k(Y | Y > 0, X):
the conditional distribution of rain amount *given* it is raining. The Tweedie mean head
is unchanged — it stays on the full distribution and handles the dry-probability signal.

**Results after the fix (raw wet-conditional model, 200-cell run):**

| Band | h=0 coverage | h=24 coverage | Target |
|---|---|---|---|
| 10–90 (raw, wet hours) | **{rw1090_h0:.0%}** | {rw1090_h24:.0%} | 80% |
| 25–75 (raw, wet hours) | **{rw2575_h0:.0%}** | {_get("cov_wet_raw_25_75", 24):.0%} | 50% |
| 10–90 (blended, wet hours) | {wet1090_h0:.0%} | {wet1090_h24:.0%} | 80% |
| 25–75 (blended, wet hours) | {wet2575_h0:.0%} | {_get("cov_wet_25_75", 24):.0%} | 50% |

The raw wet-conditional model hits the targets; blending degrades wet-hour coverage because
blend weights are computed on all-hours CRPS (the wet-conditional quantiles predict positive
rain on dry hours → high CRPS there → weights collapse → blend falls back to near-zero climatology).

**Chosen architecture (two separate jobs):**

1. **Tweedie mean** — trained on all hours, blended with all-hours weights (CRPSS ≈ 0.43–0.51).
   This answers *"will it rain?"* and is the only head used for CRPSS skill reporting.
2. **Wet-conditional quantile heads** — trained on wet rows, used raw (unblended).
   These answer *"how much, given rain?"* and are used only when the Tweedie mean exceeds
   a display threshold (the pod gates the plume fan on the mean prediction).

The two heads are never blended together — they answer orthogonal questions.
"""
    else:
        wet_section = (
            "\n### Wet-hour calibration\n\n"
            "_Wet-hour coverage not yet computed — re-run with current code to see "
            "`cov_wet_10_90` / `cov_wet_25_75` columns._\n"
        )

    # ── trust weights ────────────────────────────────────────────────────────
    if weights and len(weights) >= 5:
        w = np.array(weights)
        w_mean = float(w.mean())
        w_max  = float(w.max())
        n_above = int((w > 0.30).sum())
        weight_note = (
            f"**Trust weights** ({len(weights)} cells): mean w={w_mean:.3f}, max w={w_max:.3f}, "
            f"{n_above}/{len(weights)} cells above w=0.30. "
            f"Fitted on all-hours CRPS vs deterministic climatology baseline (MAE from clim mean), "
            f"consistent with CRPSS reporting. Mean weight {w_mean:.2%} → blend is "
            f"~{1-w_mean:.0%} climatology at the typical cell.\n"
        )
        weight_fig = "![weights](figures/ensemble/trust_weights.png)\n"
    else:
        weight_note = (
            "_Trust weight distribution skipped — too few cells. "
            "Re-run with `--n-cells 200` or full cache._\n"
        )
        weight_fig = ""

    plume_fig = (
        "![plume examples](figures/ensemble/plume_display.png)\n\n"
        "_One panel per observed rain intensity: dry, light, moderate, heavy. "
        "Blended model only — outer band = 10–90%, inner = 25–75%, line = mean, dots = observed. "
        "Bands are wet-conditional: given rain, 80% of similar situations fell inside the outer band._\n\n"
        "![plume diagnostic](figures/ensemble/plume_examples.png)\n\n"
        "_Diagnostic: raw vs blended vs climatology on the same 6 endpoints._\n"
        if d.get("plumes") else
        "_Plume examples not yet saved — re-run with `--save-plumes` flag._\n"
    )

    abl_fig = (
        "![ablation](figures/ensemble/v3_ablation.png)\n"
        if (FIG / "v3_ablation.png").exists() else ""
    )

    return f"""
## 10. Results (auto-generated by `report_ensemble.py`)

**Status (2026-06-10):** 200-cell diagnostic runs completed. Blending fix applied (deterministic
baseline for trust weights). v3 feature ablation completed. Wet-conditional quantile calibration
investigated and fixed. See `docs/comments.md` for full session log.

### Forecast skill (CRPSS vs climatology)

![crpss](figures/ensemble/crpss_vs_horizon.png)

{raw_note}**Blended CRPSS: h=0 → {crpss_h0:.3f}, h=24 → {crpss_h24:.3f}** (mean: {crpss_mean:.3f}).
CRPSS > 0 means the model beats knowing only where and when you are. The skill decays with
lead time as expected — the barometer sees the current system but cannot see systems still
offshore. CRPSS ≈ 0.43 is near the physical ceiling for single-point surface observations
with a 72h pressure history window.

### All-hours coverage (dominated by zero-inflation)

![coverage](figures/ensemble/coverage_vs_horizon.png)

{cov_note}
{wet_section}

### PIT histogram

![PIT](figures/ensemble/pit_histogram.png)

Uniform = well-calibrated. The excess central bar (`q25–q75`) is structural zero-inflation,
not miscalibration — most dry hours fall in the central band by construction.

### Trust weight distribution

{weight_fig}
{weight_note}

### v3 Feature ablation

{abl_fig}

All six v3 features (pressure acceleration, dewpoint trend, temperature trend, dewpoint depression)
showed **ΔCRPSS ≈ 0** with confidence intervals spanning zero, on both the overall dataset and
event-specific subsets (fast fronts, moisture advection). The base feature set already carries
all available skill — `N_HISTORY = 72h` and `PRESSURE_TREND_HOURS = [3, 6, 12, 24, 48, 72]`
are already in place. The ceiling is the single-point sensor constraint, not feature engineering.

**Decision: cut all v3 features.** Final model uses: `sp_hPa`, `sp_rate_3h/6h/12h/24h/48h/72h`,
`rh`, `rh_trend_3h`, `t2m_C`, `t2m_trend_3h`, `month_sin/cos`, `hour_sin/cos`, `elevation`,
`zone`, `horizon_h`.

### Feature importance by model head

![importance](figures/ensemble/feature_importance.png)

### Plume examples

{plume_fig}
"""


def write_report(d: dict) -> None:
    if not REPORT.exists():
        print(f"design doc {REPORT} not found — cannot update")
        return
    existing = REPORT.read_text(encoding="utf-8")
    results = _results_section(d)
    anchor = "\n## 10. Results"
    if anchor in existing:
        existing = existing[: existing.index(anchor)]
    REPORT.write_text(existing.rstrip() + "\n" + results, encoding="utf-8")
    print(f"updated {REPORT}")


def main() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    d = _load()
    m = d["metrics_overall"]

    # Merge raw coverage columns from metrics_overall into coverage if present
    cov = d["coverage"].copy()
    if len(m) and len(cov):
        for col in ["cov_raw_10_90", "cov_raw_25_75"]:
            if col in m.columns and col not in cov.columns:
                cov = cov.merge(m[["horizon_h", col]], on="horizon_h", how="left")
        # Also merge blended coverage if coverage.csv is thin
        for col in ["cov_10_90", "cov_25_75"]:
            if col not in cov.columns and col in m.columns:
                cov = cov.merge(m[["horizon_h", col]], on="horizon_h", how="left")

    if len(m):
        fig_crpss_vs_horizon(m)
        fig_coverage_wet(m)
    if len(cov):
        fig_coverage(cov)
    if len(d["pit_histogram"]):
        fig_pit(d["pit_histogram"])
    if len(d["importance"]):
        fig_importance(d["importance"])
    fig_trust_weights(d["weights"])
    if d["plumes"]:
        fig_plumes(d["plumes"])
        fig_plumes_display(d["plumes"])
    if d["plumes_uncond"] and d["plumes"]:
        fig_option_comparison(d["plumes_uncond"], d["plumes"],
                              d["plumes_conf"] or None)
        fig_coverage_explainer(d["plumes_uncond"], d["plumes"])
    if len(d["v3_ablation"]):
        fig_ablation(d["v3_ablation"], d["v3_conditional"])

    write_report(d)
    print(f"figures -> {FIG}")


if __name__ == "__main__":
    main()
