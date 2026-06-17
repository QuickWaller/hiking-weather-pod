"""4-way bake-off: Tweedie-CDF read-off vs trained quantile heads, × rain-emphasised vs not.

Given two saved model dirs (E = rain-emphasised/harvest, N = not-emphasised/no-harvest), score each on
the 2024 test BOTH ways — (a) the blended quantile heads, (b) q50/q75/q90 read analytically off the
blended Tweedie mean's predictive CDF (φ estimated on the validation year, no test leakage). Writes
comparison.csv (4 rows) and picks the winner → winner.json.

Pick rule: highest τ=6h-weighted CRPSS on 2024 test, gated on sane q90 coverage (0.85–0.96), tie-broken
toward the Tweedie read-off (simpler + faster: no quantile heads needed in production) when within 0.005.
Read-only on the models; writes only to --out.

Run: .venv/bin/python experiments/bakeoff_eval.py --e-dir <dirE> --n-dir <dirN> --cache-dir <cache> --out <dir>
"""
import sys, json, argparse
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, "src")
from podml.train_ensemble import (
    load_cache, load_ensemble_state, to_long_format, predict, blend, ensure_model_features,
    crps_from_quantiles, crpss, _clim_preds, ENSEMBLE_FEATURES, ENSEMBLE_HORIZONS,
    MODEL_NAMES, QUANTILE_LEVELS,
)
from podml.train_motion import VAL_YEAR, TEST_YEAR
from podml.tweedie_cdf import tweedie_quantiles
from podml.display_check import estimate_phi

EVAL_TAU = 6.0
QN = MODEL_NAMES[1:]   # ["q50","q75","q90"]


def load_splits(cache_dir, n_cells=None, seed=42):
    X, y, meta = load_cache(Path(cache_dir))
    ensure_model_features(X, y, meta)
    if n_cells:
        rng = np.random.default_rng(seed)
        keep = set(rng.choice(meta["cell"].unique(),
                              size=min(n_cells, meta["cell"].nunique()), replace=False))
        m = meta["cell"].isin(keep).to_numpy()
        X, y, meta = X[m].reset_index(drop=True), y[m].reset_index(drop=True), meta[m].reset_index(drop=True)
    feats = [f for f in ENSEMBLE_FEATURES if f == "horizon_h" or f in X.columns]
    Xl, yl, ml = to_long_format(X[[f for f in feats if f != "horizon_h"]], y, meta[["cell", "month", "year"]])
    return Xl, yl.to_numpy(), ml, feats, ml["year"].to_numpy()


def score(yte, h, preds, clim_mean):
    crps = crps_from_quantiles(yte, preds)
    rows = []
    for hh in ENSEMBLE_HORIZONS:
        hm = h == hh
        if hm.sum() < 50:
            continue
        rows.append({"h": hh, "crpss": crpss(crps[hm], yte[hm], clim_mean[hm]),
                     **{f"cov_{n}": float((yte[hm] <= preds[n][hm]).mean()) for n in QN}})
    df = pd.DataFrame(rows)
    w = np.exp(-df["h"].to_numpy() / EVAL_TAU); w /= w.sum()
    return {"wcrpss": float((df["crpss"] * w).sum()),
            **{f"cov_{n}": float(df[f"cov_{n}"].mean()) for n in QN}}


def eval_model(model_dir, Xl, yl, ml, feats, yrs):
    models, clim_table, global_stats, weights = load_ensemble_state(Path(model_dir))
    vl, te = yrs == VAL_YEAR, yrs == TEST_YEAR
    bv = blend(predict(models, Xl[vl], feats), clim_table, global_stats, weights, ml[vl])
    phi = estimate_phi(yl[vl], bv["mean"])
    mte = ml[te]; yte = yl[te]; h = mte["horizon_h"].to_numpy()
    bt = blend(predict(models, Xl[te], feats), clim_table, global_stats, weights, mte)
    clim_mean = _clim_preds(clim_table, global_stats, mte)["mean"]
    tq = tweedie_quantiles(bt["mean"], phi, QUANTILE_LEVELS)
    out = {
        "quantile_heads": score(yte, h, {"mean": bt["mean"], **{n: bt[n] for n in QN}}, clim_mean),
        "tweedie_cdf":    score(yte, h, {"mean": bt["mean"], **{n: tq[n] for n in QN}}, clim_mean),
    }
    return float(phi), out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--e-dir", required=True); ap.add_argument("--n-dir", required=True)
    ap.add_argument("--cache-dir", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--n-cells", type=int, default=None)
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    Xl, yl, ml, feats, yrs = load_splits(a.cache_dir, a.n_cells)

    rows = []
    for label, mdir in [("E_rain_emphasised", a.e_dir), ("N_not_emphasised", a.n_dir)]:
        if not (Path(mdir) / "models").exists():
            print(f"  skip {label}: no models at {mdir}", flush=True); continue
        phi, res = eval_model(mdir, Xl, yl, ml, feats, yrs)
        for method, m in res.items():
            rows.append({"data": label, "method": method, "phi": round(phi, 3), **m})
            print(f"  {label:18s} {method:14s} wCRPSS={m['wcrpss']:.4f} "
                  f"cov q50/q75/q90={m['cov_q50']:.2f}/{m['cov_q75']:.2f}/{m['cov_q90']:.2f}", flush=True)
    comp = pd.DataFrame(rows)
    comp.to_csv(out / "comparison.csv", index=False)

    # pick: best wCRPSS with q90 coverage in [0.85,0.96]; tie-break to tweedie within 0.005
    ok = comp[(comp["cov_q90"] >= 0.85) & (comp["cov_q90"] <= 0.96)]
    pool = (ok if len(ok) else comp).sort_values("wcrpss", ascending=False)
    best = pool.iloc[0]
    tw = pool[(pool["method"] == "tweedie_cdf") & (pool["wcrpss"] >= best["wcrpss"] - 0.005)]
    win = tw.iloc[0] if len(tw) else best
    winner = {"data": win["data"], "method": win["method"], "wcrpss": float(win["wcrpss"]),
              "model_dir": a.e_dir if win["data"].startswith("E") else a.n_dir}
    (out / "winner.json").write_text(json.dumps(winner, indent=2))
    print(f"\n  WINNER: {winner['data']} via {winner['method']}  (wCRPSS={winner['wcrpss']:.4f})", flush=True)


if __name__ == "__main__":
    main()
