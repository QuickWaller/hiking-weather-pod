"""Production baseline (2026-06-12) — summary figures from outputs/ensemble CSVs."""
import pandas as pd, numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

HERE = __file__.rsplit("\\", 1)[0] if "\\" in __file__ else "."
m = pd.read_csv(f"{HERE}/metrics_overall.csv")
cov = pd.read_csv(f"{HERE}/coverage.csv")
pit = pd.read_csv(f"{HERE}/pit_histogram.csv")
imp = pd.read_csv(f"{HERE}/importance.csv")

plt.rcParams.update({"figure.dpi": 130, "font.size": 9, "axes.grid": True,
                     "grid.alpha": 0.3, "axes.spysine" if False else "axes.axisbelow": True})

# ---- Fig 1: CRPSS + AUC vs lead time --------------------------------------
fig, ax = plt.subplots(1, 2, figsize=(10, 3.6))
ax[0].plot(m.horizon_h, m.crpss, "o-", color="#1b7837", lw=2, ms=3, label="blend (clim-anchored)")
ax[0].plot(m.horizon_h, m.crpss_raw, "o-", color="#b2182b", lw=1.5, ms=3, label="raw heads")
ax[0].axhline(0, color="k", lw=0.8, ls="--")
ax[0].set_title("Rain-amount skill vs lead time (CRPSS)")
ax[0].set_xlabel("lead time (h)"); ax[0].set_ylabel("CRPSS  (1 = perfect, 0 = climatology)")
ax[0].legend(frameon=False)
ax[0].annotate(f"τ=6h weighted\nblend={0.2092:.3f}  raw={-0.3079:.3f}",
               (0.97, 0.96), xycoords="axes fraction", ha="right", va="top",
               fontsize=8, color="#444")

ax[1].plot(m.horizon_h, m.auc_binary, "o-", color="#2166ac", lw=2, ms=3, label="binary occurrence head")
ax[1].plot(m.horizon_h, m.auc_tweedie, "o-", color="#999999", lw=1.3, ms=3, label="tweedie-as-classifier")
ax[1].axhline(0.5, color="k", lw=0.8, ls="--")
ax[1].set_title("Rain occurrence discrimination (AUC)")
ax[1].set_xlabel("lead time (h)"); ax[1].set_ylabel("ROC AUC")
ax[1].set_ylim(0.5, 0.85); ax[1].legend(frameon=False)
fig.tight_layout(); fig.savefig(f"{HERE}/fig1_skill_vs_leadtime.png")

# ---- Fig 2: Coverage / calibration story ----------------------------------
fig, ax = plt.subplots(1, 2, figsize=(10, 3.6))
ax[0].axhline(0.5, color="k", lw=1, ls="--", label="target 0.50")
ax[0].plot(m.horizon_h, m.cov_25_75, "o-", color="#b2182b", lw=1.5, ms=3, label="blend, all rows (collapsed)")
ax[0].plot(m.horizon_h, m.cov_wet_25_75, "o-", color="#f4a582", lw=1.5, ms=3, label="blend, wet rows")
ax[0].plot(m.horizon_h, m.cov_conf_25_75, "o-", color="#1b7837", lw=2, ms=3, label="conformal-corrected")
ax[0].set_title("Central 25–75% interval coverage")
ax[0].set_xlabel("lead time (h)"); ax[0].set_ylabel("fraction of obs inside band")
ax[0].set_ylim(0, 0.75); ax[0].legend(frameon=False, fontsize=7.5)

ax[1].axhline(0.8, color="k", lw=1, ls="--", label="target 0.80")
ax[1].plot(m.horizon_h, m.cov_10_90, "o-", color="#b2182b", lw=1.5, ms=3, label="blend, all rows")
ax[1].plot(m.horizon_h, m.cov_wet_10_90, "o-", color="#f4a582", lw=1.5, ms=3, label="blend, wet rows")
ax[1].plot(m.horizon_h, m.cov_conf_10_90, "o-", color="#1b7837", lw=2, ms=3, label="conformal-corrected")
ax[1].set_title("Outer 10–90% interval coverage")
ax[1].set_xlabel("lead time (h)"); ax[1].set_ylabel("fraction of obs inside band")
ax[1].set_ylim(0, 1.0); ax[1].legend(frameon=False, fontsize=7.5)
fig.tight_layout(); fig.savefig(f"{HERE}/fig2_coverage.png")

# ---- Fig 3: PIT histograms at 3 horizons ----------------------------------
hsel = [0, 12, 24]
fig, ax = plt.subplots(1, 3, figsize=(11, 3.4), sharey=True)
order = ["<q10", "q10-q25", "q25-q75", "q75-q90", ">q90"]
for i, h in enumerate(hsel):
    d = pit[pit.horizon_h == h].set_index("band").reindex(order)
    x = np.arange(len(order))
    ax[i].bar(x - 0.2, d.observed, 0.4, color="#2166ac", label="observed")
    ax[i].bar(x + 0.2, d.expected, 0.4, color="#bbbbbb", label="expected (calibrated)")
    ax[i].set_xticks(x); ax[i].set_xticklabels(order, rotation=45, ha="right", fontsize=7)
    ax[i].set_title(f"PIT, lead = {h}h")
    if i == 0: ax[i].set_ylabel("probability mass"); ax[i].legend(frameon=False, fontsize=8)
fig.suptitle("Probability Integral Transform — bunching in <q10 = dry-mass dominance", fontsize=10)
fig.tight_layout(); fig.savefig(f"{HERE}/fig3_pit.png")

# ---- Fig 4: feature importance (mean model, top 15) -----------------------
mean_imp = imp[imp.model == "mean"].sort_values("gain", ascending=True).tail(15)
fig, ax = plt.subplots(figsize=(6.5, 5))
ax.barh(mean_imp.feature, mean_imp.gain, color="#542788")
ax.set_title("Top-15 feature gain — mean (Tweedie) head")
ax.set_xlabel("LightGBM total gain")
fig.tight_layout(); fig.savefig(f"{HERE}/fig4_importance.png")

print("wrote fig1..fig4")
print("conf cov 25-75 range:", round(m.cov_conf_25_75.min(),3), "-", round(m.cov_conf_25_75.max(),3))
print("conf cov 10-90 range:", round(m.cov_conf_10_90.min(),3), "-", round(m.cov_conf_10_90.max(),3))
