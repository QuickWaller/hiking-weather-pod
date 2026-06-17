"""Honest re-grade: score the saved production coarse model (bakeoff_N) on the TRUE-distribution
2024 test (uniform v1 cache `outputs/ensemble/dataset`), not the enriched v2 test. No retrain.

Fixes the contamination flagged in project memory: the v2 cache stratified every year incl. 2024,
so its test was 30% wet vs the true ~44% wet-endpoint / ~14% wet-row rate. This re-grades on the
uniform cache → comparable to the §1b baseline + real-world skill.

Writes outputs/coarse_truedist_metrics.csv and prints a summary. Run on the VM.
"""
import sys
from pathlib import Path
sys.path.insert(0, "src")
import numpy as np
import pandas as pd
from podml.train_ensemble import (
    load_cache, ensure_model_features, load_ensemble_state, to_long_format,
    predict, blend, crps_from_quantiles, crpss, _clim_preds,
    ENSEMBLE_FEATURES, ENSEMBLE_HORIZONS, MODEL_NAMES,
)
from podml.train_motion import TEST_YEAR

TAU = 6.0
QN = MODEL_NAMES[1:]   # ["q50","q75","q90"]
MODEL_DIR = sys.argv[1] if len(sys.argv) > 1 else "outputs/bakeoff_N"
CACHE = "outputs/ensemble/dataset"   # the uniform / true-distribution cache

X, y, meta = load_cache(Path(CACHE))
ensure_model_features(X, y, meta)
# subset to the TEST year BEFORE expanding to long (only ~137k endpoints → fast + light)
keep = (meta["year"] == TEST_YEAR).to_numpy()
X, y, meta = X[keep].reset_index(drop=True), y[keep].reset_index(drop=True), meta[keep].reset_index(drop=True)
feats = [f for f in ENSEMBLE_FEATURES if f == "horizon_h" or f in X.columns]
Xl, yl, ml = to_long_format(X[[f for f in feats if f != "horizon_h"]], y, meta[["cell", "month", "year"]])
yl = yl.to_numpy()

models, clim, gs, w = load_ensemble_state(Path(MODEL_DIR))
mte = ml; yte = yl; h = mte["horizon_h"].to_numpy()
raw = predict(models, Xl, feats)
bl = blend(raw, clim, gs, w, mte)
clim_mean = _clim_preds(clim, gs, mte)["mean"]

crps_bl = crps_from_quantiles(yte, {"mean": bl["mean"], **{n: bl[n] for n in QN}})
crps_raw = crps_from_quantiles(yte, {"mean": raw["mean"], **{n: raw[n] for n in QN}})

rows = []
for hh in ENSEMBLE_HORIZONS:
    m = h == hh
    if m.sum() < 50:
        continue
    rows.append(dict(
        horizon_h=hh, n_test=int(m.sum()), n_wet=int((yte[m] >= 0.5).sum()),
        crpss=crpss(crps_bl[m], yte[m], clim_mean[m]),
        crpss_raw=crpss(crps_raw[m], yte[m], clim_mean[m]),
        mean_crps=float(crps_bl[m].mean()),
        **{f"cov_le_{n}": float((yte[m] <= bl[n][m]).mean()) for n in QN},
    ))
df = pd.DataFrame(rows)
wt = np.exp(-df.horizon_h.to_numpy() / TAU); wt /= wt.sum()
wc = float((df.crpss * wt).sum()); wcr = float((df.crpss_raw * wt).sum())
df.to_csv("outputs/coarse_truedist_metrics.csv", index=False)

print(f"=== TRUE-DIST 2024 re-grade — model={MODEL_DIR} ===")
print(f"test wet-row frac = {(yte >= 0.5).mean():.3f}  (true distribution; the enriched v2 test was forced to 0.30)")
print(f"wCRPSS(tau=6h):  blend={wc:.4f}   raw={wcr:.4f}")
print(f"CRPSS  h0 blend={df.iloc[0].crpss:.3f}  h24 blend={df.iloc[-1].crpss:.3f}")
print(f"coverage mean  q50/q75/q90 = {df.cov_le_q50.mean():.2f}/{df.cov_le_q75.mean():.2f}/{df.cov_le_q90.mean():.2f}")
print("wrote outputs/coarse_truedist_metrics.csv")
