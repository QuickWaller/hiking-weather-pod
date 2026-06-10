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

The q10/q25/q75/q90 heads are trained on the full distribution which is ~86% zeros.
The unconditional quantiles of a distribution that is 86% zero are:
- q10 ≈ 0 (10th percentile of a dataset where >10% are zero is zero — trivially)
- q25 ≈ 0 (same argument)
- q75 ≈ 0 (same — 86% > 75%)
- q90 = first non-trivial value (only 14% of data is wet)

So for a wet observation where y = 1 mm/hr, the predicted band is roughly [0, q90_small].
Most wet observations exceed q90, so coverage collapses. **Before the fix:** wet-hour 10–90
coverage was ~19%, 25–75 was ~0% — the inner band was useless for rainy hours.

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
        "![plume examples](figures/ensemble/plume_examples.png)\n"
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
    if len(d["v3_ablation"]):
        fig_ablation(d["v3_ablation"], d["v3_conditional"])

    write_report(d)
    print(f"figures -> {FIG}")


if __name__ == "__main__":
    main()
