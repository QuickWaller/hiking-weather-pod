"""q90 rounds ablation — do the late trees matter, or has q90 flattened by ~400?

Trains q90 (quantile, α=0.90) to 1500 trees on a small cell subset (fast: ~1.6M rows), NO early
stopping, val pinball loss logged every 100 rounds. Then reports test pinball loss + coverage at
tree checkpoints. If val/test loss is flat after ~400 → the QUANTILE_ROUNDS=400 cap is free; if it
keeps dropping → read off how much the tail trees add and raise the production cap accordingly.

Same stratified cache + importance weights as production, just fewer cells, so the *relative*
convergence transfers. Read-only; writes a CSV to experiments/, nothing in outputs/ensemble.

Run:  .venv/bin/python experiments/q90_rounds_ablation.py
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd
import lightgbm as lgb

sys.path.insert(0, "src")
from podml.train_ensemble import (
    load_cache, to_long_format, horizon_weights, ENSEMBLE_FEATURES, ensure_model_features,
)
from podml.train_motion import VAL_YEAR, TEST_YEAR

N_CELLS = 150
CACHE = Path("outputs/ensemble/dataset_v2")
ALPHA = 0.90
SEED = 42
N_THREADS = 0  # solo run — use all cores (0 = LightGBM default = all)
CHECKPOINTS = [100, 200, 400, 800, 1200, 1500]


def pinball(y, q, a):
    e = y - q
    return float(np.mean(np.maximum(a * e, (a - 1.0) * e)))


def main():
    X, y, meta = load_cache(CACHE)
    ensure_model_features(X, y, meta)
    rng = np.random.default_rng(SEED)
    keep = set(rng.choice(meta["cell"].unique(),
                          size=min(N_CELLS, meta["cell"].nunique()), replace=False))
    m = meta["cell"].isin(keep).to_numpy()
    X, y, meta = X[m].reset_index(drop=True), y[m].reset_index(drop=True), meta[m].reset_index(drop=True)

    feats = [f for f in ENSEMBLE_FEATURES if f == "horizon_h" or f in X.columns]
    mcols = ["cell", "month", "year"] + (["weight"] if "weight" in meta.columns else [])
    Xl, yl, ml = to_long_format(X[[f for f in feats if f != "horizon_h"]], y, meta[mcols])
    yrs = ml["year"].to_numpy()
    tr, vl, te = yrs < VAL_YEAR, yrs == VAL_YEAR, yrs == TEST_YEAR
    Xtr, ytr = Xl[tr][feats].reset_index(drop=True), yl[tr].to_numpy()
    Xvl, yvl = Xl[vl][feats].reset_index(drop=True), yl[vl].to_numpy()
    Xte, yte = Xl[te][feats].reset_index(drop=True), yl[te].to_numpy()

    wtr = horizon_weights(Xtr["horizon_h"].to_numpy(), 6.0)
    wvl = horizon_weights(Xvl["horizon_h"].to_numpy(), 6.0)
    if "weight" in ml.columns:
        iwt = ml[tr]["weight"].to_numpy(); wtr = wtr * iwt if wtr is not None else iwt
        iwv = ml[vl]["weight"].to_numpy(); wvl = wvl * iwv if wvl is not None else iwv
    print(f"q90 ablation: {N_CELLS} cells | train={len(Xtr):,} val={len(Xvl):,} test={len(Xte):,}",
          flush=True)

    dtr = lgb.Dataset(Xtr, label=ytr, weight=wtr)
    dvl = lgb.Dataset(Xvl, label=yvl, weight=wvl, reference=dtr)
    evals: dict = {}
    bst = lgb.train(
        {"objective": "quantile", "alpha": ALPHA, "num_leaves": 127, "min_child_samples": 50,
         "reg_lambda": 0.5, "learning_rate": 0.05, "max_bin": 127, "verbose": -1,
         "seed": SEED, "num_threads": N_THREADS},
        dtr, num_boost_round=1500, valid_sets=[dvl], valid_names=["val"],
        callbacks=[lgb.log_evaluation(100), lgb.record_evaluation(evals)])

    curve = evals["val"]["quantile"]
    print("\n  trees | val_pinball | test_pinball | test_cov(y<=q90, target 0.90) | Δval vs prev", flush=True)
    rows, prev = [], None
    for n in CHECKPOINTS:
        q = bst.predict(Xte, num_iteration=n)
        vp = curve[min(n, len(curve)) - 1]
        tp = pinball(yte, q, ALPHA)
        cov = float(np.mean(yte <= q))
        dv = "" if prev is None else f"{vp - prev:+.5f}"
        print(f"  {n:5d} | {vp:.5f}     | {tp:.5f}     | {cov:.3f}                         | {dv}",
              flush=True)
        rows.append({"trees": n, "val_pinball": vp, "test_pinball": tp, "test_cov_q90": cov})
        prev = vp
    out = Path("experiments/q90_rounds_ablation.csv")
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"\n  wrote {out}", flush=True)


if __name__ == "__main__":
    main()
