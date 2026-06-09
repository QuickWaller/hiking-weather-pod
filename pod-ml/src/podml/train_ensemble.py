"""Phase-07 distributional rain model — the forecast ensemble.

Replaces the 15 independent binary classifiers from the concluded phase-06 model with five
LightGBM models (Tweedie mean + q10/q25/q75/q90) that share a single training objective:
predict the *distribution* of rain amount (mm/hr) over the next H hours, where H is an input
feature (not a separate model per lead). Horizons cover every integer hour 0–24, producing the
full plume x-axis in one forward pass.

Key differences from phase 06:
  - Target is rain AMOUNT (mm/hr instantaneous rate at T+h), not binary yes/no per threshold.
  - Thresholds become a *display* decision (CDF lookup on the blended distribution), not a
    training decision — this eliminates the coherence bug where P(≥7.6) > P(≥0.5) was possible.
  - 5 models total (vs 15); one forward pass per horizon point on the pod.
  - Calibration check: PIT histogram + interval coverage on validation, then reported on test.
  - Per-cell climatology blend ensures the device never does worse than knowing where/when you are.

Dataset (separate from the phase-06 cache):
  X:  v3 feature vector (includes sp_accel, td_trend_6h, month_sin/cos) + horizon_h feature
  y:  rain amount — instantaneous rate mm/hr at T+h for h=0..24 (one column per hour)

Build the dataset once, then train from it:
  python -m podml.train_ensemble --build-cache [--all-cells] [--k 4] [--years 2014-2024]
  python -m podml.train_ensemble --from-cache  [--n-cells N] [--seed S]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

from podml.config import CONFIG_PATH, ROOT
from podml.features import build_features_endpoint
from podml.labels_gpm import load_gpm_cells_hourly
from podml.motionsim import MotionSimParams, sample_path_backward, signals_along_path
from podml.sensorsim import SensorSimParams, degrade_signals
from podml.static_features import elevation_to_zones
from podml.train_motion import (
    ENSEMBLE_AMOUNT_HORIZONS, TRAIN_YEARS, VAL_YEAR, TEST_YEAR,
    MODEL_FEATURES, N_HISTORY,
    ensure_model_features,
    _load_window, _cell_grid_index, _orog_on,
)

SAMPLED_CSV = CONFIG_PATH.parent / "sampled_points.csv"
OUT = ROOT / "outputs" / "ensemble"
CACHE_DIR = OUT / "dataset"

# Every integer hour 0-24: the full plume x-axis.
ENSEMBLE_HORIZONS = ENSEMBLE_AMOUNT_HORIZONS  # [0, 1, 2, ..., 24]

# Quantile levels: inner 50% + outer 80% prediction-interval bands (the e-ink fan).
QUANTILE_LEVELS = [0.10, 0.25, 0.75, 0.90]
MODEL_NAMES = ["mean"] + [f"q{int(a*100):02d}" for a in QUANTILE_LEVELS]
# → ["mean", "q10", "q25", "q75", "q90"]

# Model feature list: same as the phase-06 binary model + horizon_h (the key new input).
ENSEMBLE_FEATURES = MODEL_FEATURES + ["horizon_h"]


# ─────────────────────────────────────────────── dataset build ──────────────────────────────────

def _flush_year(flush_dir: Path, year: int, rows_X: list, rows_y: list, rows_meta: list) -> None:
    flush_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows_X).to_parquet(flush_dir / f"X_{year}.parquet")
    pd.DataFrame(rows_y).to_parquet(flush_dir / f"y_{year}.parquet")
    pd.DataFrame(rows_meta).to_parquet(flush_dir / f"meta_{year}.parquet")


def build_ensemble_dataset(
    cells: pd.DataFrame,
    gpm_times: pd.DatetimeIndex,
    precip: np.ndarray,          # (n_gpm_time, n_cells) mm/hr
    k_per_cell_month: int,
    years: list[int],
    params: MotionSimParams,
    seed: int = 0,
    flush_dir: Path | None = None,
) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None]:
    """Build the 07 dataset: one feature row per endpoint, amount labels for every hour 0-24.

    Structurally the same as train_motion.build_dataset but:
      - y contains amount_h0 .. amount_h24 (instantaneous mm/hr at T+h) — no binary labels.
      - Uses the v3 feature vector (sp_accel, td_trend_6h, month_sin/cos from build_features_endpoint).
    """
    rng = np.random.default_rng(seed)
    sensor = SensorSimParams()
    gpm_pos = {t: k for k, t in enumerate(gpm_times)}
    lats = cells["lat"].to_numpy()
    lons = cells["lon"].to_numpy()

    rows_X, rows_y, rows_meta = [], [], []
    grid_idx: tuple[np.ndarray, np.ndarray] | None = None
    orog: np.ndarray | None = None
    land: np.ndarray | None = None

    for year in years:
        for month in range(1, 13):
            ds = _load_window(year, month)
            if ds is None:
                continue
            if grid_idx is None:
                grid_idx = _cell_grid_index(ds, lats, lons)
                orog = _orog_on(ds)
                land = ~np.isnan(ds["sp"].isel(valid_time=0).values)
            ci, cj = grid_idx
            wtimes = pd.to_datetime(ds["valid_time"].values)
            in_month = np.where((wtimes.year == year) & (wtimes.month == month))[0]
            valid_pos = in_month[in_month >= N_HISTORY]
            if valid_pos.size == 0:
                continue

            for c in range(len(cells)):
                i0, j0 = int(ci[c]), int(cj[c])
                if not land[i0, j0]:
                    continue
                chosen = rng.choice(valid_pos, size=min(k_per_cell_month, valid_pos.size), replace=False)
                for t0 in chosen:
                    ts = wtimes[t0]
                    gp = gpm_pos.get(ts)
                    if gp is None:
                        continue

                    # Amount labels: instantaneous rain rate (mm/hr) at T+h for h=0..24.
                    # h=0 = nowcast (current-hour GPM rate); h>0 = the 1-hour ERA5 accumulation
                    # ending at T+h. NaN where the horizon extends past the GPM array.
                    labels: dict[str, float] = {}
                    for h in ENSEMBLE_HORIZONS:
                        labels[f"amount_h{h}"] = (
                            float(precip[gp + h, c]) if gp + h < precip.shape[0] else np.nan
                        )

                    path = sample_path_backward((int(t0), i0, j0), N_HISTORY, land, params, rng)
                    sig = signals_along_path(path, ds, orog, params, rng)
                    sig = degrade_signals(sig, sensor, rng)
                    xrow = build_features_endpoint(sig)
                    if any(np.isnan(v) for v in xrow.values()):
                        continue
                    elev_c = float(cells["elevation_m"].iloc[c])
                    xrow["elevation"] = elev_c
                    xrow["zone"] = float(elevation_to_zones(np.array([elev_c]))[0])

                    di = abs(path.i[-1] - path.i[-7]) + abs(path.j[-1] - path.j[-7])
                    speed = di * params.cell_km / 6.0
                    mclass = "still" if speed < 0.3 else ("walk" if speed < 8.0 else "drive")

                    rows_X.append(xrow)
                    rows_y.append(labels)
                    rows_meta.append({
                        "cell": cells["name"].iloc[c], "lat": lats[c], "lon": lons[c],
                        "elevation": elev_c, "zone": xrow["zone"],
                        "time": ts, "year": year, "month": month, "motion": mclass,
                    })
            ds.close()
        print(f"  year {year}: {len(rows_X)} rows", flush=True)
        if flush_dir is not None:
            _flush_year(flush_dir, year, rows_X, rows_y, rows_meta)
            rows_X, rows_y, rows_meta = [], [], []

    if flush_dir is not None:
        return None, None, None
    return pd.DataFrame(rows_X), pd.DataFrame(rows_y), pd.DataFrame(rows_meta)


def build_cache(years: list[int], k_per_cell_month: int = 4, all_cells: bool = False,
                n_cells: int | None = None, seed: int = 0, cache_dir: Path = CACHE_DIR) -> dict:
    """Build the 07 dataset once and write to parquet (the expensive step).

    Separate from the phase-06 cache (outputs/motion/dataset). Produces amount_h0..amount_h24
    (instantaneous rate at T+h) with the v3 feature vector. Everything downstream reads from this cache.
    """
    from podml.train_motion import all_land_cells
    cells = all_land_cells() if all_cells else pd.read_csv(SAMPLED_CSV)
    if n_cells is not None:
        cells = cells.iloc[:n_cells].reset_index(drop=True)
    print(f"build_cache (ensemble): {len(cells)} cells, years {min(years)}-{max(years)}, "
          f"k={k_per_cell_month}", flush=True)
    gpm_times, precip = load_gpm_cells_hourly(
        cells["lat"].to_numpy(), cells["lon"].to_numpy(), min(years), max(years)
    )
    precip = precip.astype("float32")
    print(f"  GPM hours: {len(gpm_times)}; precip {precip.nbytes/1e9:.2f} GB", flush=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cells.to_parquet(cache_dir / "cells.parquet")
    build_ensemble_dataset(cells, gpm_times, precip, k_per_cell_month, years,
                           MotionSimParams(), seed=seed, flush_dir=cache_dir)
    parts = sorted(cache_dir.glob("X_*.parquet"))
    n = sum(len(pd.read_parquet(p, columns=["sp_hPa"])) for p in parts)
    print(f"build_cache DONE: {n} rows across {len(parts)} year-parts → {cache_dir}", flush=True)
    return {"rows": n, "cells": len(cells), "cache": str(cache_dir)}


def load_cache(cache_dir: Path = CACHE_DIR) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Reassemble the 07 cached dataset (X, y, meta) from its per-year parquet parts."""
    X = pd.concat([pd.read_parquet(p) for p in sorted(cache_dir.glob("X_*.parquet"))], ignore_index=True)
    y = pd.concat([pd.read_parquet(p) for p in sorted(cache_dir.glob("y_*.parquet"))], ignore_index=True)
    meta = pd.concat([pd.read_parquet(p) for p in sorted(cache_dir.glob("meta_*.parquet"))],
                     ignore_index=True)
    return X, y, meta


# ─────────────────────────────────────────────── long format ────────────────────────────────────

def to_long_format(
    X: pd.DataFrame,
    y: pd.DataFrame,
    meta: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """Reshape endpoint×horizon wide → long format (one row per endpoint × hour).

    Each endpoint appears once per horizon, with horizon_h added as a feature column. Rows whose
    amount is NaN (the horizon extends past the GPM array) are dropped. Output is stacked
    horizon-major: all rows for h=0, then h=1, … — callers split it afterwards by the year column.

    Features are emitted as float32 (LightGBM bins them anyway, so this is lossless to the model) and
    filled into a preallocated array per horizon. That keeps the 38M-row frame at ~1× its size: a
    pd.concat of 25 slices, or a single X[ep_idx] fancy-index, would hold a second full-size copy.
    Pass meta pre-sliced to the columns you actually need downstream — every column is replicated 25×.
    """
    missing = [f"amount_h{h}" for h in ENSEMBLE_HORIZONS if f"amount_h{h}" not in y.columns]
    if missing:
        raise ValueError(
            f"Cache is missing amount columns {missing}. "
            "Rebuild with: python -m podml.train_ensemble --build-cache"
        )
    H, n_ep, feat_cols = len(ENSEMBLE_HORIZONS), len(X), list(X.columns)

    # Valid (non-NaN amount) endpoints per horizon. np.where scans horizon-major, so the long rows
    # come out grouped by horizon — horizon hi owns the contiguous slice [bounds[hi]:bounds[hi+1]).
    valid = np.empty((H, n_ep), dtype=bool)
    for hi, h in enumerate(ENSEMBLE_HORIZONS):
        valid[hi] = y[f"amount_h{h}"].notna().to_numpy()
    h_idx, ep_idx = np.where(valid)
    n_long = len(ep_idx)
    bounds = np.concatenate(([0], np.cumsum(valid.sum(axis=1))))

    X_src = X.to_numpy(dtype="float32")
    X_arr = np.empty((n_long, len(feat_cols) + 1), dtype="float32")
    y_arr = np.empty(n_long, dtype="float32")
    for hi, h in enumerate(ENSEMBLE_HORIZONS):
        s, e = int(bounds[hi]), int(bounds[hi + 1])
        if s == e:
            continue
        eps = ep_idx[s:e]                       # endpoints valid at this horizon (≤ n_ep rows)
        X_arr[s:e, :-1] = X_src[eps]
        X_arr[s:e, -1] = h
        y_arr[s:e] = y[f"amount_h{h}"].to_numpy(dtype="float32")[eps]

    X_long = pd.DataFrame(X_arr, columns=feat_cols + ["horizon_h"])
    y_long = pd.Series(y_arr, name="amount")
    meta_long = meta.iloc[ep_idx].reset_index(drop=True)
    meta_long["horizon_h"] = np.asarray(ENSEMBLE_HORIZONS, dtype="float32")[h_idx]
    return X_long, y_long, meta_long


# ─────────────────────────────────────────────── metrics ────────────────────────────────────────

def crps_from_quantiles(y_true: np.ndarray, preds: dict[str, np.ndarray]) -> np.ndarray:
    """CRPS approximated as a pinball-loss sum over the four quantile bands.

    CRPS = 2/K * Σ_k [ α_k*(y-q_k)₊ + (1-α_k)*(q_k-y)₊ ]
    This is the standard energy-score approximation for a discrete quantile ensemble.
    """
    total = np.zeros(len(y_true))
    for alpha, name in zip(QUANTILE_LEVELS, MODEL_NAMES[1:]):
        q = preds[name]
        e = y_true - q
        total += alpha * np.maximum(e, 0.0) + (1.0 - alpha) * np.maximum(-e, 0.0)
    return 2.0 * total / len(QUANTILE_LEVELS)


def crpss(crps_model: np.ndarray, y_true: np.ndarray, clim_mean: np.ndarray) -> float:
    """CRPSS vs a climatological-mean deterministic baseline (CRPS_clim = MAE from clim mean)."""
    crps_clim = np.abs(y_true - clim_mean)
    mc = float(np.mean(crps_clim))
    return 1.0 - float(np.mean(crps_model)) / mc if mc > 0 else np.nan


def coverage(y_true: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    return float(np.mean((y_true >= lo) & (y_true <= hi)))


def pit_histogram(y_true: np.ndarray, preds: dict[str, np.ndarray]) -> pd.DataFrame:
    """PIT histogram: which quantile band does each observation fall into?

    Uniform → well-calibrated. U-shape → bands too narrow. Central hump → too wide.
    """
    q10, q25, q75, q90 = preds["q10"], preds["q25"], preds["q75"], preds["q90"]
    obs = np.array([
        (y_true < q10).mean(),
        ((y_true >= q10) & (y_true < q25)).mean(),
        ((y_true >= q25) & (y_true < q75)).mean(),
        ((y_true >= q75) & (y_true < q90)).mean(),
        (y_true >= q90).mean(),
    ])
    return pd.DataFrame({
        "band": ["<q10", "q10-q25", "q25-q75", "q75-q90", ">q90"],
        "observed": obs,
        "expected": [0.10, 0.15, 0.50, 0.15, 0.10],
    })


# ─────────────────────────────────────────────── training ───────────────────────────────────────

def fit_ensemble(
    X_tr: pd.DataFrame,
    y_tr: np.ndarray,
    X_val: pd.DataFrame,
    y_val: np.ndarray,
    feats: list[str],
    seed: int = 42,
) -> dict[str, LGBMRegressor]:
    """Train the five-model ensemble on rain amount (mm/hr) with early stopping on the val set.

    Hyperparameter choices:
      n_estimators=1500 / lr=0.05 / num_leaves=127 — lr raised + cap lowered from the first full run,
      where q90 ran the full 3000 trees at lr=0.02 but its val loss had flattened by ~1500 (each extra
      500 trees bought ~half the previous block — diminishing returns). 0.05 reaches the same plateau
      in far fewer rounds, so the run (and especially the 8×-heavier ablation) is much faster.
      min_child_samples=50 — prevents leaf-level overfit on the sparse high-rain tail.
      reg_lambda=0.5 — L2 regularisation; keeps quantile heads from crossing under extrapolation.
      Tweedie power=1.5 — midpoint of compound Poisson-gamma, well-matched to hourly rain amounts.
      Early stopping patience=100 — stops if val loss doesn't improve for 100 rounds.
    """
    lgb_common = dict(
        n_estimators=1500, learning_rate=0.05, num_leaves=127,
        min_child_samples=50, reg_lambda=0.5,
        verbose=-1, random_state=seed,
    )
    callbacks = [lgb.early_stopping(100, verbose=False), lgb.log_evaluation(500)]
    # Select the model feature columns once (shared across all five heads). When the caller already
    # passes exactly `feats` (the train path does), this is a no-op — avoiding a full copy of the
    # multi-GB train matrix on top of the original. Ablation passes a subset, so it does copy.
    Xtr_f = X_tr if list(X_tr.columns) == list(feats) else X_tr[feats]
    Xval_f = X_val if list(X_val.columns) == list(feats) else X_val[feats]
    models: dict[str, LGBMRegressor] = {}
    print("  fitting mean (Tweedie)…", flush=True)
    models["mean"] = LGBMRegressor(
        objective="tweedie", tweedie_variance_power=1.5, **lgb_common
    ).fit(Xtr_f, y_tr, eval_set=[(Xval_f, y_val)], callbacks=callbacks)
    print(f"    mean: {models['mean'].best_iteration_} trees", flush=True)
    for alpha, name in zip(QUANTILE_LEVELS, MODEL_NAMES[1:]):
        print(f"  fitting {name} (α={alpha})…", flush=True)
        models[name] = LGBMRegressor(
            objective="quantile", alpha=alpha, **lgb_common
        ).fit(Xtr_f, y_tr, eval_set=[(Xval_f, y_val)], callbacks=callbacks)
        print(f"    {name}: {models[name].best_iteration_} trees", flush=True)
    return models


def predict(
    models: dict[str, LGBMRegressor],
    X: pd.DataFrame,
    feats: list[str],
) -> dict[str, np.ndarray]:
    """Run all five models and sort quantile outputs to prevent crossings."""
    preds = {name: models[name].predict(X[feats]) for name in MODEL_NAMES}
    q_mat = np.column_stack([preds[n] for n in MODEL_NAMES[1:]])
    q_mat = np.sort(q_mat, axis=1)
    for i, name in enumerate(MODEL_NAMES[1:]):
        preds[name] = q_mat[:, i]
    return preds


# ─────────────────────────────────────────────── climatology blend ──────────────────────────────

def build_clim_distribution(
    y_amount: pd.Series,
    meta: pd.DataFrame,
    train_mask: np.ndarray,
) -> tuple[dict, dict]:
    """Per-(cell, month) climatological rain-amount distribution from training data.

    Returns (table, global_stats) where table maps (cell, month) → {"mean", "q10", …}
    and global_stats is the fallback for unseen (cell, month) pairs.
    """
    df = pd.DataFrame({
        "cell": meta["cell"].to_numpy(),
        "month": meta["month"].to_numpy(),
        "amount": y_amount.to_numpy(),
    })[train_mask].dropna()

    global_stats: dict = {
        "mean": float(df["amount"].mean()),
        **{f"q{int(a*100):02d}": float(np.quantile(df["amount"], a)) for a in QUANTILE_LEVELS},
    }
    table: dict = {}
    for (cell, month), g in df.groupby(["cell", "month"]):
        if len(g) >= 20:
            table[(cell, int(month))] = {
                "mean": float(g["amount"].mean()),
                **{f"q{int(a*100):02d}": float(np.quantile(g["amount"], a))
                   for a in QUANTILE_LEVELS},
            }
    return table, global_stats


def _clim_preds(clim_table: dict, global_stats: dict,
                meta_rows: pd.DataFrame) -> dict[str, np.ndarray]:
    """Climatological predictions (per cell+month) for every model name."""
    cells = meta_rows["cell"].to_numpy()
    months = meta_rows["month"].to_numpy()
    out: dict[str, np.ndarray] = {}
    for name in MODEL_NAMES:
        out[name] = np.array([
            clim_table.get((c, int(m)), global_stats).get(name, global_stats["mean"])
            for c, m in zip(cells, months)
        ])
    return out


def fit_cell_weights(
    models: dict[str, LGBMRegressor],
    X_val: pd.DataFrame,
    y_val: np.ndarray,
    meta_val: pd.DataFrame,
    clim_table: dict,
    global_stats: dict,
    feats: list[str],
) -> dict[str, float]:
    """Per-cell trust weight w(cell) = per-cell CRPSS vs deterministic climatological mean.

    Uses the deterministic climatological mean (MAE from mean) as the baseline, not the full
    distributional climatology. The distributional climatology is already a hard bar — a
    well-fitted rain distribution closes most of the gap and leaves tiny per-cell weights that
    collapse the blend to near-pure climatology everywhere. The deterministic baseline is the
    same bar used in CRPSS reporting, so the weights stay consistent with the reported skill:
    cells with CRPSS ≈ 0.45 get w ≈ 0.45, genuinely negative-skill cells still get w = 0
    (fallback to climatology, never worse).
    """
    preds_val = predict(models, X_val, feats)
    crps_val = crps_from_quantiles(y_val, preds_val)
    clim_mean_val = _clim_preds(clim_table, global_stats, meta_val)["mean"]
    # Deterministic baseline: CRPS of a point forecast at the climatological mean = MAE.
    crps_clim_det = np.abs(y_val - clim_mean_val)

    weights: dict[str, float] = {}
    df = pd.DataFrame({
        "cell": meta_val["cell"].to_numpy(),
        "crps_model": crps_val,
        "crps_clim": crps_clim_det,
    })
    for cell, g in df.groupby("cell"):
        mc = float(g["crps_clim"].mean())
        mm = float(g["crps_model"].mean())
        w = 1.0 - mm / mc if mc > 0 else 0.0
        weights[cell] = float(np.clip(w, 0.0, 1.0))
    return weights


def blend(
    preds: dict[str, np.ndarray],
    clim_table: dict,
    global_stats: dict,
    cell_weights: dict[str, float],
    meta_rows: pd.DataFrame,
) -> dict[str, np.ndarray]:
    """Trust-weighted CDF blend: F_shown = w * F_model + (1-w) * F_clim.

    Blending in distribution space keeps quantiles monotone and makes the fallback
    automatic — low-skill cells retreat to climatology rather than to a bad model.
    """
    clim = _clim_preds(clim_table, global_stats, meta_rows)
    cells = meta_rows["cell"].to_numpy()
    w = np.array([cell_weights.get(c, 0.5) for c in cells])
    return {name: w * preds[name] + (1.0 - w) * clim[name] for name in MODEL_NAMES}


# ─────────────────────────────────────────────── main train + eval ──────────────────────────────

def _save_plume_examples(
    preds_te: dict[str, np.ndarray],
    blended_te: dict[str, np.ndarray],
    y_te: np.ndarray,
    meta_te: pd.DataFrame,
    clim_table: dict,
    global_stats: dict,
    n_examples: int = 20,
) -> None:
    """Save N plume examples (raw / blended / climatology quantiles + y_obs) to plumes.json.

    Requires 'time' in meta_te (populated when the cache was built with build_ensemble_dataset).
    Each plume covers all horizons for one (cell, time) endpoint, sorted by horizon.
    """
    if "time" not in meta_te.columns:
        print("  _save_plume_examples: 'time' column absent — skipping (re-build cache)", flush=True)
        return
    meta_te = meta_te.reset_index(drop=True)
    unique_eps = meta_te.drop_duplicates(subset=["cell", "time"])[["cell", "time"]].reset_index(drop=True)
    if len(unique_eps) > n_examples:
        unique_eps = unique_eps.sample(n=n_examples, random_state=42).reset_index(drop=True)
    examples = []
    for _, row in unique_eps.iterrows():
        cell, t = row["cell"], row["time"]
        mask = ((meta_te["cell"] == cell) & (meta_te["time"] == t)).to_numpy()
        if not mask.any():
            continue
        sub = meta_te[mask].sort_values("horizon_h").reset_index()
        pos = sub["index"].to_numpy()   # positions in preds_te / y_te
        clim_p = _clim_preds(clim_table, global_stats, sub)
        examples.append({
            "cell": str(cell),
            "time": str(t),
            "horizons": [float(h) for h in sub["horizon_h"].tolist()],
            "y_obs": [float(y_te[i]) for i in pos],
            "raw":     {n: [float(preds_te[n][i])   for i in pos] for n in MODEL_NAMES},
            "blended": {n: [float(blended_te[n][i]) for i in pos] for n in MODEL_NAMES},
            "clim":    {n: clim_p[n].tolist()                      for n in MODEL_NAMES},
        })
    out_path = OUT / "plumes.json"
    with open(out_path, "w") as f:
        json.dump(examples, f, indent=2)
    print(f"  saved {len(examples)} plume examples → {out_path}", flush=True)


def train_ensemble(
    cache_dir: Path = CACHE_DIR,
    n_cells: int | None = None,
    seed: int = 42,
    n_boot: int = 200,
    save_plumes: bool = False,
) -> dict:
    """Train the phase-07 distributional ensemble and evaluate on the 2024 test set.

    Outputs to outputs/ensemble/:
      metrics_overall.csv  — CRPSS per horizon (model vs climatology)
      pit_histogram.csv    — PIT calibration check (are the bands honest?)
      coverage.csv         — empirical 10-90 and 25-75 band coverage per horizon
      cell_weights.json    — per-cell trust weights (for on-device lookup table)
      importance.csv       — feature gain per model name
    """
    X, y, meta = load_cache(cache_dir)
    ensure_model_features(X, y, meta)

    if n_cells is not None:
        rng0 = np.random.default_rng(seed)
        keep = set(rng0.choice(meta["cell"].unique(),
                               size=min(n_cells, meta["cell"].nunique()), replace=False))
        mask = meta["cell"].isin(keep).to_numpy()
        X, y, meta = (X[mask].reset_index(drop=True), y[mask].reset_index(drop=True),
                      meta[mask].reset_index(drop=True))

    print(f"train_ensemble: X={X.shape}, cells={meta['cell'].nunique()}", flush=True)

    # Features present in this cache (v3 features absent from old caches). horizon_h is appended by
    # the long expansion, so it is always available.
    avail_feats = [f for f in ENSEMBLE_FEATURES if f == "horizon_h" or f in X.columns]
    if len(avail_feats) < len(ENSEMBLE_FEATURES):
        missing = set(ENSEMBLE_FEATURES) - set(avail_feats)
        print(f"  WARNING: {len(missing)} features absent from cache (rebuild for v3): {missing}",
              flush=True)

    # Expand to long (one row per endpoint × horizon, horizon_h as a feature), then split by year.
    # Carry only the model-feature columns (so the fit's X[feats] is a no-op, not a 3.5 GB copy of
    # the 38M-row matrix) and only the meta columns read downstream. "time" is included so that
    # --save-plumes can reconstruct per-endpoint plumes from the long-format test set.
    meta_cols = ["cell", "month", "year"] + (["time"] if "time" in meta.columns else [])
    X_long, y_long, meta_long = to_long_format(
        X[[f for f in avail_feats if f != "horizon_h"]], y, meta[meta_cols])
    del X, y, meta
    years = meta_long["year"].to_numpy()
    tr, vl, te = np.isin(years, list(TRAIN_YEARS)), years == VAL_YEAR, years == TEST_YEAR

    X_tr, y_tr, meta_tr = X_long[tr].reset_index(drop=True), y_long[tr].to_numpy(), meta_long[tr].reset_index(drop=True)
    X_vl, y_vl, meta_vl = X_long[vl].reset_index(drop=True), y_long[vl].to_numpy(), meta_long[vl].reset_index(drop=True)
    X_te, y_te, meta_te = X_long[te].reset_index(drop=True), y_long[te].to_numpy(), meta_long[te].reset_index(drop=True)
    del X_long, y_long, meta_long
    print(f"  long rows: train={len(X_tr):,} val={len(X_vl):,} test={len(X_te):,}", flush=True)

    # Climatology distribution (per-cell rain amount) from the training split only.
    clim_table, global_stats = build_clim_distribution(
        pd.Series(y_tr, name="amount"), meta_tr, np.ones(len(y_tr), dtype=bool))

    # 1. Train (val set used for early stopping only — not for weight fitting)
    models = fit_ensemble(X_tr, y_tr, X_vl, y_vl, avail_feats, seed=seed)

    # 2. Per-cell trust weights (fitted on validation only)
    weights = fit_cell_weights(models, X_vl, y_vl,
                               meta_vl, clim_table, global_stats, avail_feats)
    print(f"  cell weights: {len(weights)} cells, mean w={np.mean(list(weights.values())):.3f}",
          flush=True)

    # 3. Test evaluation (2024 held-out)
    preds_te   = predict(models, X_te, avail_feats)
    blended_te = blend(preds_te, clim_table, global_stats, weights, meta_te)

    crps_te = crps_from_quantiles(y_te, blended_te)
    # Diagnostic: score the RAW (unblended) model too. If raw CRPSS shows horizon decay / beats
    # climatology while the blended score is flat, the trust-weight blend is strangling a useful
    # model (fixable); if raw is also ~climatology, the signal/target is the problem.
    crps_te_raw = crps_from_quantiles(y_te, preds_te)

    overall, cov_rows, pit_rows, imp_rows = [], [], [], []
    for h in ENSEMBLE_HORIZONS:
        h_mask = meta_te["horizon_h"].to_numpy() == h
        if h_mask.sum() < 50:
            continue
        y_h  = y_te[h_mask]
        cr_h = crps_te[h_mask]
        pb   = {n: blended_te[n][h_mask] for n in MODEL_NAMES}
        pr   = {n: preds_te[n][h_mask] for n in MODEL_NAMES}   # raw, unblended

        clim_mean_h = _clim_preds(clim_table, global_stats, meta_te[h_mask])["mean"]
        cs = crpss(cr_h, y_h, clim_mean_h)
        cs_raw = crpss(crps_te_raw[h_mask], y_h, clim_mean_h)   # raw-model skill

        cov_10_90 = coverage(y_h, pb["q10"], pb["q90"])
        cov_25_75 = coverage(y_h, pb["q25"], pb["q75"])
        cov_raw_10_90 = coverage(y_h, pr["q10"], pr["q90"])
        cov_raw_25_75 = coverage(y_h, pr["q25"], pr["q75"])

        overall.append({
            "horizon_h": h, "crpss": cs, "crpss_raw": cs_raw,
            "mean_crps": float(np.mean(cr_h)),
            "cov_10_90": cov_10_90, "cov_25_75": cov_25_75,
            "cov_raw_10_90": cov_raw_10_90, "cov_raw_25_75": cov_raw_25_75,
            "n_test": int(h_mask.sum()),
        })
        pit = pit_histogram(y_h, pb)
        pit["horizon_h"] = h
        pit_rows.append(pit)

        cov_rows.append({
            "horizon_h": h,
            "cov_10_90": cov_10_90, "cov_25_75": cov_25_75,
            "target_10_90": 0.80, "target_25_75": 0.50,
        })
        print(f"  h={h:2d}h: CRPSS blend={cs:.3f} raw={cs_raw:.3f} | "
              f"cov25-75 blend={cov_25_75:.2f} raw={cov_raw_25_75:.2f} (target 0.50)", flush=True)

    for name, model in models.items():
        for feat, gain in zip(avail_feats, model.feature_importances_):
            imp_rows.append({"model": name, "feature": feat, "gain": float(gain)})

    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(overall).to_csv(OUT / "metrics_overall.csv", index=False)
    pd.concat(pit_rows, ignore_index=True).to_csv(OUT / "pit_histogram.csv", index=False)
    pd.DataFrame(cov_rows).to_csv(OUT / "coverage.csv", index=False)
    pd.DataFrame(imp_rows).to_csv(OUT / "importance.csv", index=False)
    with open(OUT / "cell_weights.json", "w") as f:
        json.dump({str(k): v for k, v in weights.items()}, f, indent=2)

    if save_plumes:
        _save_plume_examples(preds_te, blended_te, y_te, meta_te, clim_table, global_stats)

    print(f"ensemble results → {OUT}", flush=True)
    return {"models": len(MODEL_NAMES), "horizons": len(ENSEMBLE_HORIZONS), "out": str(OUT)}


# ─────────────────────────────────────────────── feature ablation ───────────────────────────────

# The v3 features being evaluated — all require the 07 cache (raw signal history at endpoint).
V3_ABLATION_FEATURES = [
    "sp_accel_nested", "sp_accel_disjoint",
    "td_trend_3h", "td_trend_6h", "t2m_trend_6h",
    "dewpoint_dep",
]

# Pre-stated keep criteria — fixed before running, not post-hoc.
# A feature survives if it meets the criterion for its row.
KEEP_CRITERIA = {
    # Second-derivative of pressure — value is on fast-moving fronts, not average.
    "sp_accel_nested":   "lo_ci > 0 OR fast-front conditional positive",
    "sp_accel_disjoint": "lo_ci > 0 OR fast-front conditional positive; if both flat keep nested only (derivable from cache, zero pod cost)",
    # Moisture: td_trend_6h is the primary signal; dewpoint_dep tested for marginal gain *given trend present*.
    "td_trend_6h":       "lo_ci > 0 OR moisture-advection conditional positive",
    "td_trend_3h":       "lo_ci > 0 only (redundant shorter window — no conditional path)",
    "t2m_trend_6h":      "lo_ci > 0 only (weakest prior — cut on flat)",
    # dewpoint_dep drop-one tests marginal level contribution given td_trend_6h is already in the full model.
    # This is the correct test (not the v2 standalone — collinearity only matters when both are absent).
    "dewpoint_dep":      "lo_ci > 0 from drop-one (marginal gain given td_trend_6h present in full model)",
    "moisture_group":    "informational — total moisture group contribution vs individual drop-ones",
}

# Group ablations: drop a semantic cluster to measure joint contribution.
# Separates collinearity within the group from the group's total value.
V3_GROUP_ABLATIONS = {
    "moisture_group": ["dewpoint_dep", "td_trend_3h", "td_trend_6h"],
}


def ensemble_feature_ablation(
    cache_dir: Path = CACHE_DIR,
    n_cells: int | None = None,
    seed: int = 42,
    n_boot: int = 200,
) -> dict:
    """Measure per-feature CRPSS gain for v3 features from the 07 cache.

    For each feature in V3_ABLATION_FEATURES:
      - Train full model and model with that feature dropped (both with early stopping).
      - Bootstrap CI on delta CRPSS (full minus drop), resampling cells on the validation set.
      - Conditional analysis on fast-front events (sp_accel) and moisture-advection events (td_trend_6h).

    Keep criteria are pre-stated in KEEP_CRITERIA above. Individual features with a conditional path
    (sp_accel_nested, sp_accel_disjoint, td_trend_6h) are tagged "check conditional" rather than
    auto-cut when the CI misses — read v3_conditional.csv before finalising those decisions.
    The moisture_group drop (dewpoint_dep + td_trend_3h + td_trend_6h together) is informational:
    it separates within-group collinearity from the group's total value.

    Saved to outputs/ensemble/:
      v3_ablation.csv    — per-feature delta CRPSS + CI + ci_survives + has_conditional_path + verdict
      v3_conditional.csv — feature skill on conditioned subsets (fast fronts, moisture advection)
    """
    X, y, meta = load_cache(cache_dir)
    ensure_model_features(X, y, meta)
    if n_cells is not None:
        rng0 = np.random.default_rng(seed)
        keep = set(rng0.choice(meta["cell"].unique(),
                               size=min(n_cells, meta["cell"].nunique()), replace=False))
        mask = meta["cell"].isin(keep).to_numpy()
        X = X[mask].reset_index(drop=True)
        y = y[mask].reset_index(drop=True)
        meta = meta[mask].reset_index(drop=True)
    # Only ablate features that are actually in the cache. horizon_h is appended by the long
    # expansion, so it is always available.
    full_feats = [f for f in ENSEMBLE_FEATURES if f == "horizon_h" or f in X.columns]
    ablate = [f for f in V3_ABLATION_FEATURES if f in X.columns]
    if not ablate:
        print("No v3 ablation features found in cache — rebuild with --build-cache first.",
              flush=True)
        return {}

    # Expand once and split by year. Every fit below selects its own feature columns from these
    # frames, so the full model and all drop-one variants share identical rows (only the feature set
    # differs) — that keeps the drop-one deltas aligned with the full-model labels. Carry only the
    # ablatable feature set (so the full-model fit's X[feats] is a no-op) and only cell/month/year.
    X_long, y_long, meta_long = to_long_format(
        X[[f for f in full_feats if f != "horizon_h"]], y, meta[["cell", "month", "year"]])
    del X, y, meta
    years = meta_long["year"].to_numpy()
    tr, vl = np.isin(years, list(TRAIN_YEARS)), years == VAL_YEAR
    X_tr, y_tr, meta_tr = X_long[tr].reset_index(drop=True), y_long[tr].to_numpy(), meta_long[tr].reset_index(drop=True)
    X_vl_full, y_vl, meta_vl = X_long[vl].reset_index(drop=True), y_long[vl].to_numpy(), meta_long[vl].reset_index(drop=True)
    del X_long, y_long, meta_long

    print(f"ensemble_feature_ablation: {len(ablate)} features to ablate, val={len(y_vl):,}",
          flush=True)

    rng = np.random.default_rng(seed + 1)

    def _bootstrap_delta(crps_a: np.ndarray, crps_b: np.ndarray,
                         meta_rows: pd.DataFrame) -> tuple[float, float, float]:
        """Bootstrap CI on mean(crps_a - crps_b) / mean(crps_clim), resampling cells."""
        crps_clim = np.abs(y_vl - clim_mean_vl) if len(crps_a) == len(y_vl) else None
        cells = meta_rows["cell"].to_numpy()
        uniq = np.unique(cells)
        boots = []
        for _ in range(n_boot):
            bc = rng.choice(uniq, size=len(uniq), replace=True)
            idx = np.where(np.isin(cells, bc))[0]
            if len(idx) < 10:
                continue
            denom = float(np.mean(np.abs(y_vl[idx] - clim_mean_vl[idx]))) if crps_clim is not None \
                else float(np.mean(np.abs(y_vl - clim_mean_vl)))
            if denom > 0:
                boots.append(float(np.mean(crps_a[idx] - crps_b[idx])) / denom)
        if not boots:
            return np.nan, np.nan, np.nan
        return float(np.mean(boots)), *np.percentile(boots, [2.5, 97.5])

    # --- Train full model once ---
    print("Training FULL model…", flush=True)
    clim_table, global_stats = build_clim_distribution(
        pd.Series(y_tr, name="amount"), meta_tr, np.ones(len(y_tr), dtype=bool))
    clim_mean_vl = _clim_preds(clim_table, global_stats, meta_vl)["mean"]
    models_full = fit_ensemble(X_tr, y_tr, X_vl_full, y_vl, full_feats, seed)
    weights_full = fit_cell_weights(models_full, X_vl_full, y_vl,
                                    meta_vl, clim_table, global_stats, full_feats)
    preds_full = predict(models_full, X_vl_full, full_feats)
    blended_full = blend(preds_full, clim_table, global_stats, weights_full, meta_vl)
    crps_full = crps_from_quantiles(y_vl, blended_full)
    crpss_full_overall = crpss(crps_full, y_vl, clim_mean_vl)
    print(f"  Full model CRPSS={crpss_full_overall:.3f}", flush=True)

    # --- Per-feature drop-one ---
    rows, cond_rows = [], []
    saved_crps_drop: dict[str, np.ndarray] = {}

    # Features with a conditional path to survival (conditional analysis below may flip the verdict).
    _CONDITIONAL_PATH = {"sp_accel_nested", "sp_accel_disjoint", "td_trend_6h"}

    for feat in ablate:
        drop_feats = [f for f in full_feats if f != feat]
        print(f"  drop {feat} → training…", flush=True)
        models_drop = fit_ensemble(X_tr, y_tr, X_vl_full, y_vl, drop_feats, seed)
        preds_drop = predict(models_drop, X_vl_full, drop_feats)
        blended_drop = blend(preds_drop, clim_table, global_stats, weights_full, meta_vl)
        crps_drop = crps_from_quantiles(y_vl, blended_drop)
        saved_crps_drop[feat] = crps_drop

        # delta = crps_drop - crps_full (positive means full is better, i.e. feature helps)
        mean_d, lo, hi = _bootstrap_delta(crps_drop, crps_full, meta_vl)
        ci_survives = bool(lo > 0)
        has_conditional_path = feat in _CONDITIONAL_PATH
        # "weak*" = CI misses but feature has a conditional path — read conditional before cutting.
        if ci_survives:
            tag = "KEEP"
        elif has_conditional_path:
            tag = "weak* (check conditional)" if hi > 0 else "CUT* (check conditional)"
        else:
            tag = "weak" if hi > 0 else "CUT"
        rows.append({
            "feature": feat,
            "crpss_full": crpss_full_overall,
            "crpss_drop": crpss(crps_drop, y_vl, clim_mean_vl),
            "delta_crpss_mean": mean_d,
            "delta_crpss_lo": float(lo),
            "delta_crpss_hi": float(hi),
            "ci_survives": ci_survives,
            "has_conditional_path": has_conditional_path,
            "verdict": tag,
        })
        print(f"  {feat}: Δ CRPSS={mean_d:.3f} [{lo:.3f}, {hi:.3f}]  → {tag}", flush=True)

    # --- Group ablations (moisture group: joint contribution vs individual drop-ones) ---
    print("Group ablations…", flush=True)
    for group_name, group_feats in V3_GROUP_ABLATIONS.items():
        group_present = [f for f in group_feats if f in full_feats]
        if not group_present:
            continue
        drop_feats = [f for f in full_feats if f not in group_present]
        print(f"  drop {group_name} {group_present} → training…", flush=True)
        models_gd = fit_ensemble(X_tr, y_tr, X_vl_full, y_vl, drop_feats, seed)
        preds_gd = predict(models_gd, X_vl_full, drop_feats)
        blended_gd = blend(preds_gd, clim_table, global_stats, weights_full, meta_vl)
        crps_gd = crps_from_quantiles(y_vl, blended_gd)
        mean_d, lo, hi = _bootstrap_delta(crps_gd, crps_full, meta_vl)
        rows.append({
            "feature": group_name,
            "crpss_full": crpss_full_overall,
            "crpss_drop": crpss(crps_gd, y_vl, clim_mean_vl),
            "delta_crpss_mean": mean_d,
            "delta_crpss_lo": float(lo),
            "delta_crpss_hi": float(hi),
            "ci_survives": None,
            "has_conditional_path": False,
            "verdict": "informational",
        })
        print(f"  {group_name}: Δ CRPSS={mean_d:.3f} [{lo:.3f}, {hi:.3f}]  (informational)",
              flush=True)

    # --- Conditional analysis on event subsets (val rows; X_vl_full is the full-feature val frame,
    # so subset masks are computed directly on it and align with the val-length saved CRPS arrays). ---
    sp3 = X_vl_full["sp_rate_3h"].to_numpy()

    # Fast fronts: rapid pressure drop at the endpoint (sp_rate_3h < -1.5 hPa/hr)
    fast = sp3 < -1.5
    if fast.sum() >= 200:
        y_ff = y_vl[fast]
        m_ff = meta_vl[fast]
        clim_ff = _clim_preds(clim_table, global_stats, m_ff)["mean"]
        p_ff = predict(models_full, X_vl_full[fast], full_feats)
        b_ff = blend(p_ff, clim_table, global_stats, weights_full, m_ff)
        cs_ff = crps_from_quantiles(y_ff, b_ff)
        cond_rows.append({
            "condition": "fast_front (sp_rate_3h < -1.5 hPa/hr)",
            "feature": "full_model",
            "n": int(fast.sum()),
            "crpss": crpss(cs_ff, y_ff, clim_ff),
        })
        for feat in ["sp_accel_nested", "sp_accel_disjoint"]:
            if feat not in saved_crps_drop:
                continue
            crps_d_ff = saved_crps_drop[feat][fast]
            mean_d, lo, hi = _bootstrap_delta(crps_d_ff, cs_ff, m_ff)
            cond_rows.append({
                "condition": "fast_front (sp_rate_3h < -1.5 hPa/hr)",
                "feature": f"drop_{feat}",
                "n": int(fast.sum()),
                "crpss": crpss(crps_d_ff, y_ff, clim_ff),
                "delta_vs_full_mean": mean_d,
                "delta_vs_full_lo": float(lo),
                "delta_vs_full_hi": float(hi),
            })

    # Moisture advection: Td rising, high moisture (td_trend_6h > 0.5 °C/hr)
    if "td_trend_6h" in X_vl_full.columns:
        td6 = X_vl_full["td_trend_6h"].to_numpy()
        moist = td6 > 0.5
        if moist.sum() >= 200:
            y_mv = y_vl[moist]
            m_mv = meta_vl[moist]
            clim_mv = _clim_preds(clim_table, global_stats, m_mv)["mean"]
            p_mv = predict(models_full, X_vl_full[moist], full_feats)
            b_mv = blend(p_mv, clim_table, global_stats, weights_full, m_mv)
            cs_mv = crps_from_quantiles(y_mv, b_mv)
            cond_rows.append({
                "condition": "moisture_advection (td_trend_6h > 0.5 °C/hr)",
                "feature": "full_model",
                "n": int(moist.sum()),
                "crpss": crpss(cs_mv, y_mv, clim_mv),
            })
            if "td_trend_6h" in saved_crps_drop:
                crps_d_mv = saved_crps_drop["td_trend_6h"][moist]
                mean_d, lo, hi = _bootstrap_delta(crps_d_mv, cs_mv, m_mv)
                cond_rows.append({
                    "condition": "moisture_advection (td_trend_6h > 0.5 °C/hr)",
                    "feature": "drop_td_trend_6h",
                    "n": int(moist.sum()),
                    "crpss": crpss(crps_d_mv, y_mv, clim_mv),
                    "delta_vs_full_mean": mean_d,
                    "delta_vs_full_lo": float(lo),
                    "delta_vs_full_hi": float(hi),
                })

    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT / "v3_ablation.csv", index=False)
    if cond_rows:
        pd.DataFrame(cond_rows).to_csv(OUT / "v3_conditional.csv", index=False)
    print(f"ablation → {OUT}/v3_ablation.csv", flush=True)
    return {"rows": rows}


# ─────────────────────────────────────────────── CLI ────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-cache", action="store_true",
                    help="build the 07 dataset (amount labels h=0..24)")
    ap.add_argument("--from-cache", action="store_true",
                    help="train + evaluate off the cached 07 dataset")
    ap.add_argument("--ablation", action="store_true",
                    help="run v3 feature ablation from the 07 cache")
    ap.add_argument("--all-cells", action="store_true",
                    help="use every land cell (full build, not just sampled_points.csv)")
    ap.add_argument("--k", type=int, default=4, help="endpoints per cell per month")
    ap.add_argument("--n-cells", type=int, default=None, help="limit cells (smoke test)")
    ap.add_argument("--years", type=str, default=None,
                    help="year range '2014-2024' or list '2016,2024'")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--n-boot", type=int, default=200, help="bootstrap iterations for ablation CIs")
    ap.add_argument("--save-plumes", action="store_true",
                    help="save 20 example plumes (raw/blended/clim) to outputs/ensemble/plumes.json")
    args = ap.parse_args()

    if args.years and "-" in args.years and "," not in args.years:
        a, b = args.years.split("-")
        yrs = list(range(int(a), int(b) + 1))
    elif args.years:
        yrs = [int(x) for x in args.years.split(",")]
    else:
        yrs = list(TRAIN_YEARS) + [VAL_YEAR, TEST_YEAR]

    if args.build_cache:
        print(build_cache(yrs, k_per_cell_month=args.k,
                          all_cells=args.all_cells, n_cells=args.n_cells, seed=args.seed))
    elif args.from_cache:
        print(train_ensemble(n_cells=args.n_cells, seed=args.seed, save_plumes=args.save_plumes))
    elif args.ablation:
        print(ensemble_feature_ablation(n_cells=args.n_cells, seed=args.seed, n_boot=args.n_boot))
    else:
        ap.print_help()
