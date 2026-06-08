"""Motion-aware grid training on 2016–2024 (ERA5 features + GPM labels).

Each training row is the ENDPOINT of a simulated hiker trajectory (see motionsim): the feature history
is gathered along a feasible path across grid cells, degraded by the sensor model, then turned into the
pod-replicable feature vector; the label is GPM rain at the endpoint cell over the next H hours. This is
the deployable distribution — a moving pod — rather than a fixed station.

Pipeline (memory-bounded for the 4.8 GB VM — never loads the whole grid):
  1. GPM labels: per-cell hourly precip for all sampled cells, once (labels_gpm.load_gpm_cells_hourly).
  2. Static context: DEM elevation/zone per cell (sampled_points.csv), ERA5 orography + land mask.
  3. Stream ERA5 month-by-month (load [prev, cur] so 72 h of history is in-window). For each sampled
     cell sample K endpoint hours in the month; build a backward motion path, signals, sensor-degrade,
     feature vector (endpoint row), and look up the GPM forward-window label.
  4. Per-cell climatology (train years only) appended as static features (precip/pressure/temp means).
  5. Split by year (train 2016–22 / val 2023 / test 2024) with an H-hour embargo at each boundary.
  6. One LightGBM per (threshold, horizon); evaluate Brier Skill Score vs a cell+month climatology
     baseline, per-cell skill, motion-stratified skill, calibration, and false-alarm/miss — saved to
     outputs/motion/ for the report.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr
from lightgbm import LGBMClassifier
from sklearn.metrics import average_precision_score

from podml.config import CONFIG_PATH, ROOT
from podml.era5_load import era5_cache_dir
from podml.features import FEATURE_COLUMNS, PRESSURE_TREND_HOURS, build_features_endpoint
from podml.labels import HORIZONS_H, THRESHOLDS_MM_HR
from podml.labels_gpm import load_gpm_cells_hourly
from podml.motionsim import MotionSimParams, sample_path_backward, signals_along_path
from podml.sensorsim import SensorSimParams, degrade_signals
from podml.static_features import elevation_to_zones, load_dem_grid, load_era5_orography

SAMPLED_CSV = CONFIG_PATH.parent / "sampled_points.csv"
OUT = ROOT / "outputs" / "motion"
CACHE_DIR = OUT / "dataset"

N_HISTORY = max(PRESSURE_TREND_HOURS)  # hours of path history before the endpoint (72)
STATIC_COLS = ["elevation", "zone", "precip_mean", "pressure_mean", "temp_mean"]
ALL_FEATURES = list(FEATURE_COLUMNS) + STATIC_COLS

# Derived features the model KEEPS (measured to help, esp. the heavy-rain tail). precip_clim + coast_dist
# were measured to NOT help and are excluded (they still get computed into raw — we never prune raw).
KEPT_DERIVED = ["lat", "lon", "ruggedness_m", "month_sin", "month_cos"]

# What the MODEL actually trains on (curated subset of the cached superset — we never prune raw).
# `zone` excluded (dead weight, redundant with elevation, confirmed near-zero contribution).
MODEL_FEATURES = [f for f in ALL_FEATURES if f != "zone"] + KEPT_DERIVED

TRAIN_YEARS = range(2015, 2023)   # 2015–2022 (val 2023, test 2024)
VAL_YEAR = 2023
TEST_YEAR = 2024


# --------------------------------------------------------------------------- grid helpers

def _month_file(year: int, month: int) -> Path:
    return era5_cache_dir("core") / f"era5land_nz_{year}-{month:02d}.nc"


def _load_window(year: int, month: int) -> xr.Dataset | None:
    """Load ERA5 [prev_month, month] concatenated on valid_time (so 72 h history is in-window)."""
    files = []
    pm_year, pm = (year - 1, 12) if month == 1 else (year, month - 1)
    for y, m in [(pm_year, pm), (year, month)]:
        f = _month_file(y, m)
        if f.exists():
            files.append(f)
    if not files or not _month_file(year, month).exists():
        return None
    ds = xr.open_mfdataset(files, combine="by_coords", engine="netcdf4").load()
    return ds.transpose("valid_time", "lat", "lon")


def _cell_grid_index(ds: xr.Dataset, lats: np.ndarray, lons: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Nearest ERA5 (lat_idx, lon_idx) for each sampled cell."""
    glat = ds["lat"].values
    glon = ds["lon"].values
    i = np.array([int(np.abs(glat - la).argmin()) for la in lats])
    j = np.array([int(np.abs(glon - lo).argmin()) for lo in lons])
    return i, j


def _orog_on(ds: xr.Dataset) -> np.ndarray:
    return load_era5_orography().interp(lat=ds["lat"], lon=ds["lon"], method="nearest").values


# --------------------------------------------------------------------------- dataset build

def _flush_year(flush_dir: Path, year: int, rows_X: list, rows_y: list, rows_meta: list) -> None:
    """Write one year's rows to parquet parts (keeps peak RAM to ~one year, not the whole dataset)."""
    flush_dir.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows_X).to_parquet(flush_dir / f"X_{year}.parquet")
    pd.DataFrame(rows_y).to_parquet(flush_dir / f"y_{year}.parquet")
    pd.DataFrame(rows_meta).to_parquet(flush_dir / f"meta_{year}.parquet")


def build_dataset(
    cells: pd.DataFrame,
    gpm_times: pd.DatetimeIndex,
    precip: np.ndarray,                 # (n_gpm_time, n_cells) mm/hr
    k_per_cell_month: int,
    years: list[int],
    params: MotionSimParams,
    seed: int = 0,
    flush_dir: Path | None = None,
) -> tuple[pd.DataFrame | None, pd.DataFrame | None, pd.DataFrame | None]:
    """Stream ERA5 months, emit one feature row per endpoint. Returns (X, y, meta), or (None×3) if
    ``flush_dir`` is set (rows are written to per-year parquet parts to bound RAM on big builds)."""
    rng = np.random.default_rng(seed)
    sensor = SensorSimParams()
    gpm_pos = {t: k for k, t in enumerate(gpm_times)}  # timestamp → row in precip
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
            # positions in this window that belong to `month` and have N_HISTORY history before them
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
                    # label: forward-window max over GPM at this cell; skip if future incomplete
                    labels = {}
                    ok = True
                    for h in HORIZONS_H:
                        if h == 0:
                            fmax = precip[gp, c]
                        elif gp + h < precip.shape[0]:
                            window = precip[gp + 1: gp + 1 + h, c]
                            # All-missing GPM window → unlabelled (NaN), NOT a false "no rain".
                            fmax = np.nan if np.all(np.isnan(window)) else np.nanmax(window)
                        else:
                            ok = False
                            break
                        for thr in THRESHOLDS_MM_HR:
                            labels[f"ge{thr}_h{h}"] = np.nan if np.isnan(fmax) else float(fmax >= thr)
                    if not ok:
                        continue

                    path = sample_path_backward((int(t0), i0, j0), N_HISTORY, land, params, rng)
                    sig = signals_along_path(path, ds, orog, params, rng)
                    sig = degrade_signals(sig, sensor, rng)
                    xrow = build_features_endpoint(sig)  # endpoint feature row (fast path)
                    if any(np.isnan(v) for v in xrow.values()):
                        continue
                    elev_c = float(cells["elevation_m"].iloc[c])
                    xrow["elevation"] = elev_c
                    xrow["zone"] = float(elevation_to_zones(np.array([elev_c]))[0])

                    # recent motion class from the last 6 h of the path
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


# --------------------------------------------------------------------------- climatology features + baseline

def add_cell_climatology(X: pd.DataFrame, meta: pd.DataFrame, train_mask: np.ndarray) -> None:
    """Append per-cell climatology (train-only means of sp/t2m + precip proxy) as static features.

    Uses the dynamic feature values themselves (sp_hPa is MSLP, t2m_C) averaged per cell over training
    rows — a pod-knowable baseline, train-only so it never peeks at val/test.
    """
    tr = X[train_mask]
    cells = meta["cell"].values
    g = pd.DataFrame({"cell": cells[train_mask], "sp": tr["sp_hPa"].values,
                      "t": tr["t2m_C"].values, "rh": tr["rh"].values}).groupby("cell")
    pressure_mean = g["sp"].mean()
    temp_mean = g["t"].mean()
    precip_mean = g["rh"].mean()  # humidity proxy for wetness (precip baseline is GPM-derived elsewhere)
    glob = (pressure_mean.mean(), temp_mean.mean(), precip_mean.mean())
    X["pressure_mean"] = [pressure_mean.get(c, glob[0]) for c in cells]
    X["temp_mean"] = [temp_mean.get(c, glob[1]) for c in cells]
    X["precip_mean"] = [precip_mean.get(c, glob[2]) for c in cells]


def cell_month_climatology(y_col: pd.Series, meta: pd.DataFrame, train_mask: np.ndarray) -> np.ndarray:
    """Climatology baseline prob for every row = train rain-frequency for that (cell, month).

    This is the honest "knowing where + when you are" baseline the BSS is measured against. Falls back
    to the global train rate where a (cell, month) is unseen in training.
    """
    df = pd.DataFrame({"cell": meta["cell"].values, "month": meta["month"].values, "y": y_col.values})
    tr = df[train_mask].dropna()
    table = tr.groupby(["cell", "month"])["y"].mean()
    global_rate = tr["y"].mean()
    key = list(zip(df["cell"], df["month"]))
    return np.array([table.get(k, global_rate) for k in key])


# --------------------------------------------------------------------------- metrics

def _brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def _operating_points(p: np.ndarray, y: np.ndarray, n: int = 19) -> pd.DataFrame:
    """Sweep the decision threshold → recall (hit rate), false-alarm rate, precision, miss rate.

    The pod's banner is a decision threshold, so this is the directly actionable error trade-off:
    catching storms (recall) vs crying wolf (false alarms). One row per decision point.
    """
    P = float((y == 1).sum())
    N = float((y == 0).sum())
    rows = []
    for d in np.linspace(0.05, 0.95, n):
        pred = p >= d
        tp = float(np.sum(pred & (y == 1)))
        fp = float(np.sum(pred & (y == 0)))
        recall = tp / P if P > 0 else np.nan
        rows.append({"decision": float(d), "recall": recall, "miss_rate": 1.0 - recall,
                     "false_alarm_rate": fp / N if N > 0 else np.nan,
                     "precision": tp / (tp + fp) if (tp + fp) > 0 else np.nan})
    return pd.DataFrame(rows)


def _reliability(p: np.ndarray, y: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    bins = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(p, bins) - 1, 0, n_bins - 1)
    out = []
    for b in range(n_bins):
        m = idx == b
        if m.sum():
            out.append({"bin": b, "pred_mean": float(p[m].mean()),
                        "obs_freq": float(y[m].mean()), "n": int(m.sum())})
    return pd.DataFrame(out)


def train_and_eval(X: pd.DataFrame, y: pd.DataFrame, meta: pd.DataFrame, seed: int = 42) -> dict:
    years = meta["year"].to_numpy()
    times = pd.to_datetime(meta["time"].values)
    train_mask = np.isin(years, list(TRAIN_YEARS))
    val_mask = years == VAL_YEAR
    test_mask = years == TEST_YEAR

    ensure_model_features(X, y, meta)

    overall, per_cell, motion_rows, calib_rows, imp_rows, err_rows = [], [], [], [], [], []
    for h in HORIZONS_H:
        # embargo: drop train/val endpoints whose H-hour label window crosses the year boundary
        emb = pd.Timedelta(hours=h)
        boundary_tr = pd.Timestamp(f"{max(TRAIN_YEARS)}-12-31 23:00")
        boundary_val = pd.Timestamp(f"{VAL_YEAR}-12-31 23:00")
        embargo = ~(((times > boundary_tr - emb) & train_mask) | ((times > boundary_val - emb) & val_mask))
        for thr in THRESHOLDS_MM_HR:
            col = f"ge{thr}_h{h}"
            yc = y[col]
            tr = train_mask & embargo & yc.notna().to_numpy()
            te = test_mask & yc.notna().to_numpy()
            if tr.sum() < 200 or te.sum() < 50 or not (0 < yc[tr].mean() < 1):
                continue
            model = LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31,
                                   verbose=-1, random_state=seed)
            model.fit(X.loc[tr, MODEL_FEATURES], yc[tr])
            p = model.predict_proba(X.loc[te, MODEL_FEATURES])[:, 1]
            yt = yc[te].to_numpy()

            clim = cell_month_climatology(yc, meta, train_mask)[te]
            bm, bc = _brier(p, yt), _brier(clim, yt)
            bss = 1.0 - bm / bc if bc > 0 else np.nan
            pr_auc = average_precision_score(yt, p) if 0 < yt.mean() < 1 else np.nan
            overall.append({"threshold_mm_hr": thr, "horizon_h": h, "bss": bss,
                            "brier_model": bm, "brier_clim": bc, "pr_auc": pr_auc,
                            "pr_auc_lift": pr_auc / yt.mean() if yt.mean() > 0 else np.nan,
                            "pos_rate": float(yt.mean()), "n_train": int(tr.sum()), "n_test": int(te.sum())})

            # per-cell skill
            mt = meta[te]
            for cell, gi in pd.DataFrame({"c": mt["cell"].values, "p": p, "y": yt,
                                          "clim": clim}).groupby("c"):
                if len(gi) >= 30 and 0 < gi["y"].mean() < 1:
                    bcc = _brier(gi["clim"].to_numpy(), gi["y"].to_numpy())
                    per_cell.append({"cell": cell, "threshold_mm_hr": thr, "horizon_h": h,
                                     "lat": mt.loc[mt["cell"] == cell, "lat"].iloc[0],
                                     "lon": mt.loc[mt["cell"] == cell, "lon"].iloc[0],
                                     "elevation": mt.loc[mt["cell"] == cell, "elevation"].iloc[0],
                                     "bss": 1.0 - _brier(gi["p"].to_numpy(), gi["y"].to_numpy()) / bcc
                                     if bcc > 0 else np.nan, "n": int(len(gi))})

            # motion-stratified skill
            for mc, gi in pd.DataFrame({"m": mt["motion"].values, "p": p, "y": yt,
                                        "clim": clim}).groupby("m"):
                if len(gi) >= 30 and 0 < gi["y"].mean() < 1:
                    bcc = _brier(gi["clim"].to_numpy(), gi["y"].to_numpy())
                    motion_rows.append({"motion": mc, "threshold_mm_hr": thr, "horizon_h": h,
                                        "bss": 1.0 - _brier(gi["p"].to_numpy(), gi["y"].to_numpy()) / bcc
                                        if bcc > 0 else np.nan, "n": int(len(gi)),
                                        "pos_rate": float(gi["y"].mean())})

            rel = _reliability(p, yt)
            rel["threshold_mm_hr"] = thr
            rel["horizon_h"] = h
            calib_rows.append(rel)

            op = _operating_points(p, yt)
            op["threshold_mm_hr"] = thr
            op["horizon_h"] = h
            err_rows.append(op)

            for feat, gain in zip(MODEL_FEATURES, model.feature_importances_):
                imp_rows.append({"feature": feat, "gain": float(gain),
                                 "threshold_mm_hr": thr, "horizon_h": h})
            print(f"  {col}: bss={bss:.3f} prauc_lift="
                  f"{overall[-1]['pr_auc_lift']:.2f} n_tr={tr.sum()} n_te={te.sum()}", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(overall).to_csv(OUT / "metrics_overall.csv", index=False)
    pd.DataFrame(per_cell).to_csv(OUT / "per_cell.csv", index=False)
    pd.DataFrame(motion_rows).to_csv(OUT / "motion_strat.csv", index=False)
    pd.concat(calib_rows).to_csv(OUT / "calibration.csv", index=False) if calib_rows else None
    pd.concat(err_rows).to_csv(OUT / "errors_operating.csv", index=False) if err_rows else None
    pd.DataFrame(imp_rows).to_csv(OUT / "importance.csv", index=False)
    return {"n_models": len(overall), "out": str(OUT)}


# --------------------------------------------------------------------------- main

def all_land_cells() -> pd.DataFrame:
    """Every valid ERA5-Land land cell as a (name, lat, lon, elevation_m) table — for the full build."""
    ds = _load_window(2024, 1)
    assert ds is not None, "need ERA5 2024-01 on disk to enumerate the grid"
    land = ~np.isnan(ds["sp"].isel(valid_time=0).values)
    glat, glon = ds["lat"].values, ds["lon"].values
    dem = load_dem_grid().interp(lat=ds["lat"], lon=ds["lon"], method="nearest").values
    ds.close()
    rows = []
    for i in range(len(glat)):
        for j in range(len(glon)):
            if land[i, j]:
                rows.append({"name": f"g{glat[i]:.1f}_{glon[j]:.1f}".replace(".", "p"),
                             "lat": float(glat[i]), "lon": float(glon[j]),
                             "elevation_m": float(max(np.nan_to_num(dem[i, j]), 0.0))})
    return pd.DataFrame(rows)


def build_cache(years: list[int], k_per_cell_month: int = 4, all_cells: bool = False,
                n_cells: int | None = None, seed: int = 0, cache_dir: Path = CACHE_DIR) -> dict:
    """Build the endpoint dataset ONCE and write it to per-year parquet parts (the expensive step).

    Everything downstream (the cells learning-curve, retraining, feature/threshold experiments) then
    reads the cache and runs in minutes — see load_cache + train_from_cache.
    """
    cells = all_land_cells() if all_cells else pd.read_csv(SAMPLED_CSV)
    if n_cells is not None:
        cells = cells.iloc[:n_cells].reset_index(drop=True)
    print(f"build_cache: {len(cells)} cells, years {min(years)}-{max(years)}, k={k_per_cell_month}",
          flush=True)
    gpm_times, precip = load_gpm_cells_hourly(cells["lat"].to_numpy(), cells["lon"].to_numpy(),
                                              min(years), max(years))
    precip = precip.astype("float32")  # halve RAM (all-cells precip is ~1 GB otherwise)
    print(f"  GPM hours: {len(gpm_times)}; precip {precip.nbytes/1e9:.2f} GB", flush=True)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cells.to_parquet(cache_dir / "cells.parquet")
    build_dataset(cells, gpm_times, precip, k_per_cell_month, years, MotionSimParams(),
                  seed=seed, flush_dir=cache_dir)
    parts = sorted(cache_dir.glob("X_*.parquet"))
    n = sum(len(pd.read_parquet(p, columns=["sp_hPa"])) for p in parts)
    print(f"build_cache DONE: {n} rows across {len(parts)} year-parts -> {cache_dir}", flush=True)
    return {"rows": n, "cells": len(cells), "cache": str(cache_dir)}


def load_cache(cache_dir: Path = CACHE_DIR) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Reassemble the cached dataset (X, y, meta) from its per-year parquet parts."""
    X = pd.concat([pd.read_parquet(p) for p in sorted(cache_dir.glob("X_*.parquet"))], ignore_index=True)
    y = pd.concat([pd.read_parquet(p) for p in sorted(cache_dir.glob("y_*.parquet"))], ignore_index=True)
    meta = pd.concat([pd.read_parquet(p) for p in sorted(cache_dir.glob("meta_*.parquet"))],
                     ignore_index=True)
    return X, y, meta


def train_from_cache(cache_dir: Path = CACHE_DIR, n_cells: int | None = None,
                     seed: int = 42, cells_seed: int = 0) -> dict:
    """Train + evaluate off the cached dataset (minutes). Optional ``n_cells`` random cell-subset is the
    knob for the learning curve; everything else reads the frozen build, no rebuild."""
    X, y, meta = load_cache(cache_dir)
    if n_cells is not None:
        rng = np.random.default_rng(cells_seed)
        cells = meta["cell"].unique()
        keep = set(rng.choice(cells, size=min(n_cells, len(cells)), replace=False))
        mask = meta["cell"].isin(keep).to_numpy()
        X, y, meta = (X[mask].reset_index(drop=True), y[mask].reset_index(drop=True),
                      meta[mask].reset_index(drop=True))
    print(f"train_from_cache: X={X.shape}, cells={meta['cell'].nunique()}", flush=True)
    return train_and_eval(X, y, meta, seed=seed)


def _terrain_static() -> dict[tuple[float, float], tuple[float, float]]:
    """Per-cell (coast-distance km, ruggedness m) from the land mask + DEM. Keyed by (lat, lon)."""
    from scipy.ndimage import distance_transform_edt, uniform_filter
    ds = _load_window(2024, 1)
    assert ds is not None
    land = ~np.isnan(ds["sp"].isel(valid_time=0).values)
    glat, glon = ds["lat"].values, ds["lon"].values
    dem = np.nan_to_num(load_dem_grid().interp(lat=ds["lat"], lon=ds["lon"], method="linear").values)
    ds.close()
    coast = distance_transform_edt(land) * 11.0  # cells-from-ocean → km (~11 km/cell)
    m, m2 = uniform_filter(dem, 3), uniform_filter(dem * dem, 3)
    rugg = np.sqrt(np.clip(m2 - m * m, 0.0, None))  # local DEM std = orographic ruggedness
    out = {}
    for i in range(len(glat)):
        for j in range(len(glon)):
            if land[i, j]:
                out[(round(float(glat[i]), 2), round(float(glon[j]), 2))] = (
                    float(coast[i, j]), float(rugg[i, j]))
    return out


# The extra MODEL features these add (the B2–B5 wins). precip_clim REPLACES the humidity-proxy precip_mean.
DERIVED_COLS = ["lat", "lon", "month_sin", "month_cos", "precip_clim", "coast_dist_km", "ruggedness_m"]


def add_derived_features(X: pd.DataFrame, y: pd.DataFrame, meta: pd.DataFrame) -> None:
    """Attach the off-cache feature wins: lat/lon, cyclic month, real GPM precip-climatology
    (per-cell+month rain frequency from train years = mean of ge0.5_h0), coast-distance, ruggedness."""
    X["lat"] = meta["lat"].to_numpy()
    X["lon"] = meta["lon"].to_numpy()
    mo = X["month"].to_numpy()
    X["month_sin"] = np.sin(2 * np.pi * mo / 12.0)
    X["month_cos"] = np.cos(2 * np.pi * mo / 12.0)

    pre = np.isin(meta["year"].to_numpy(), list(TRAIN_YEARS))
    rc = pd.DataFrame({"cell": meta["cell"].to_numpy(), "month": meta["month"].to_numpy(),
                       "r": y["ge0.5_h0"].to_numpy()})[pre].dropna()
    tab, glob = rc.groupby(["cell", "month"])["r"].mean(), float(rc["r"].mean())
    X["precip_clim"] = np.array([tab.get(k, glob) for k in zip(meta["cell"], meta["month"])])

    terr = _terrain_static()
    keys = list(zip(meta["lat"].round(2), meta["lon"].round(2)))
    cd = np.array([terr.get(k, (np.nan, np.nan))[0] for k in keys])
    rg = np.array([terr.get(k, (np.nan, np.nan))[1] for k in keys])
    X["coast_dist_km"] = np.where(np.isnan(cd), np.nanmean(cd), cd)
    X["ruggedness_m"] = np.where(np.isnan(rg), 0.0, rg)


def ensure_model_features(X: pd.DataFrame, y: pd.DataFrame, meta: pd.DataFrame) -> None:
    """Attach all MODEL_FEATURES columns to a cached X (per-cell static + kept derived), idempotently."""
    if "pressure_mean" not in X.columns:
        _add_per_cell_static(X, meta)
    if "lat" not in X.columns:
        add_derived_features(X, y, meta)


def _add_per_cell_static(X: pd.DataFrame, meta: pd.DataFrame) -> None:
    """Attach per-cell climatology features from each cell's OWN train-year rows (pod-knowable, baked
    lookup at deploy). Computed for ALL cells so held-out eval cells get theirs too — not leakage, it's
    the cell's long-run average the pod ships, never the test year."""
    pre = np.isin(meta["year"].to_numpy(), list(TRAIN_YEARS))
    g = pd.DataFrame({"cell": meta["cell"].to_numpy(), "sp": X["sp_hPa"].to_numpy(),
                      "t": X["t2m_C"].to_numpy(), "rh": X["rh"].to_numpy()})[pre].groupby("cell")
    pm, tm, rm = g["sp"].mean(), g["t"].mean(), g["rh"].mean()
    cell = meta["cell"]
    X["pressure_mean"] = cell.map(pm).fillna(pm.mean()).to_numpy()
    X["temp_mean"] = cell.map(tm).fillna(tm.mean()).to_numpy()
    X["precip_mean"] = cell.map(rm).fillna(rm.mean()).to_numpy()


def _cell_month_clim(yc: pd.Series, meta: pd.DataFrame) -> tuple[pd.Series, float]:
    """Cell+month rain-frequency baseline from train years (each cell uses its own history)."""
    pre = np.isin(meta["year"].to_numpy(), list(TRAIN_YEARS))
    df = pd.DataFrame({"cell": meta["cell"].to_numpy(), "month": meta["month"].to_numpy(),
                       "y": yc.to_numpy()})[pre].dropna()
    return df.groupby(["cell", "month"])["y"].mean(), float(df["y"].mean())


def _bss_ci(p: np.ndarray, yt: np.ndarray, clim: np.ndarray, rng: np.random.Generator,
            n_boot: int = 200) -> tuple[float, float, float]:
    """BSS vs climatology + a bootstrap 95% CI (resample test rows)."""
    bss = 1.0 - _brier(p, yt) / _brier(clim, yt)
    n = len(yt)
    boots = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        bc = _brier(clim[idx], yt[idx])
        boots.append(1.0 - _brier(p[idx], yt[idx]) / bc if bc > 0 else np.nan)
    lo, hi = np.nanpercentile(boots, [2.5, 97.5])
    return bss, float(lo), float(hi)


def learning_curve(cache_dir: Path = CACHE_DIR, eval_n: int = 300,
                   counts: tuple[int, ...] = (50, 100, 200, 400, 800, 1600),
                   pairs: tuple[tuple[float, int], ...] = ((0.5, 6), (0.5, 24), (7.6, 6)),
                   seed: int = 0, n_boot: int = 200) -> dict:
    """Is N cells enough? Train on growing cell-subsets, evaluate on a FIXED held-out cell set (so each
    point is judged identically AND it tests spatial generalisation). Saves curve + CIs."""
    X, y, meta = load_cache(cache_dir)
    _add_per_cell_static(X, meta)
    rng = np.random.default_rng(seed)
    cells = meta["cell"].unique()
    eval_cells = set(rng.choice(cells, size=eval_n, replace=False))
    pool = np.array([c for c in cells if c not in eval_cells])
    counts = tuple(c for c in counts if c <= len(pool)) + (len(pool),)  # cap + add the max
    years = meta["year"].to_numpy()
    eval_base = meta["cell"].isin(eval_cells).to_numpy() & (years == TEST_YEAR)
    print(f"learning_curve: {len(pool)} train-pool cells, {eval_n} held-out eval cells, counts {counts}",
          flush=True)

    rows = []
    for c_n in counts:
        train_cells = set(rng.choice(pool, size=c_n, replace=False))
        tr_base = meta["cell"].isin(train_cells).to_numpy() & np.isin(years, list(TRAIN_YEARS))
        for thr, h in pairs:
            col = f"ge{thr}_h{h}"
            yc = y[col]
            tr = tr_base & yc.notna().to_numpy()
            te = eval_base & yc.notna().to_numpy()
            if tr.sum() < 200 or te.sum() < 50 or not (0 < yc[tr].mean() < 1):
                continue
            model = LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31,
                                   verbose=-1, random_state=42).fit(X.loc[tr, MODEL_FEATURES], yc[tr])
            p = model.predict_proba(X.loc[te, MODEL_FEATURES])[:, 1]
            yt = yc[te].to_numpy()
            table, glob = _cell_month_clim(yc, meta)
            key = list(zip(meta.loc[te, "cell"], meta.loc[te, "month"]))
            clim = np.array([table.get(k, glob) for k in key])
            bss, lo, hi = _bss_ci(p, yt, clim, rng, n_boot)
            rows.append({"n_cells": c_n, "threshold": thr, "horizon": h,
                         "bss": bss, "ci_lo": lo, "ci_hi": hi, "n_test": int(te.sum())})
            print(f"  cells={c_n:5d} ge{thr}_h{h}: bss={bss:.3f} [{lo:.3f},{hi:.3f}]", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT / "learning_curve.csv", index=False)
    return {"points": len(rows), "out": str(OUT / "learning_curve.csv")}


def _fit_eval_bss(X, yc, tr, te, feats, clim, rng, n_boot=200):
    model = LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31,
                           verbose=-1, random_state=42).fit(X.loc[tr, feats], yc[tr])
    p = model.predict_proba(X.loc[te, feats])[:, 1]
    return _bss_ci(p, yc[te].to_numpy(), clim, rng, n_boot)


def compare_feature_sets(cache_dir: Path = CACHE_DIR, n_cells: int = 800, seed: int = 0,
                         n_boot: int = 200) -> dict:
    """B2–B5: measure the feature wins off the cache. Baseline vs improved (real GPM precip-climatology
    replacing the humidity proxy, + lat/lon, cyclic month, coast-distance, ruggedness), then leave-one-out
    per derived feature at the common and heavy-rain classes to attribute each one (incl. niche value)."""
    X, y, meta = load_cache(cache_dir)
    _add_per_cell_static(X, meta)
    add_derived_features(X, y, meta)
    rng = np.random.default_rng(seed)
    cells = meta["cell"].unique()
    keep = set(rng.choice(cells, size=min(n_cells, len(cells)), replace=False))
    mask = meta["cell"].isin(keep).to_numpy()
    X, y, meta = X[mask].reset_index(drop=True), y[mask].reset_index(drop=True), meta[mask].reset_index(drop=True)
    years, times = meta["year"].to_numpy(), pd.to_datetime(meta["time"].values)
    improved = [f for f in MODEL_FEATURES if f != "precip_mean"] + DERIVED_COLS

    def masks(h, yc):
        emb = ~((times > pd.Timestamp(f"{max(TRAIN_YEARS)}-12-31 23:00") - pd.Timedelta(hours=h))
                & np.isin(years, list(TRAIN_YEARS)))
        tr = np.isin(years, list(TRAIN_YEARS)) & emb & yc.notna().to_numpy()
        te = (years == TEST_YEAR) & yc.notna().to_numpy()
        table, glob = _cell_month_clim(yc, meta)
        clim = np.array([table.get(k, glob) for k in zip(meta.loc[te, "cell"], meta.loc[te, "month"])])
        return tr, te, clim

    comp, abl = [], []
    for thr, h in [(0.5, 6), (2.5, 12), (7.6, 6), (0.5, 24)]:
        yc = y[f"ge{thr}_h{h}"]
        tr, te, clim = masks(h, yc)
        if tr.sum() < 200 or te.sum() < 50 or not (0 < yc[tr].mean() < 1):
            continue
        b = _fit_eval_bss(X, yc, tr, te, MODEL_FEATURES, clim, rng, n_boot)
        im = _fit_eval_bss(X, yc, tr, te, improved, clim, rng, n_boot)
        comp.append({"threshold": thr, "horizon": h, "bss_baseline": b[0], "bss_improved": im[0],
                     "delta": im[0] - b[0], "imp_lo": im[1], "imp_hi": im[2]})
        print(f"  ge{thr}_h{h}: base={b[0]:.3f} improved={im[0]:.3f} Δ={im[0]-b[0]:+.3f}", flush=True)

    # leave-one-out attribution at common + heavy classes (heavy = where niche features may matter)
    for thr, h in [(0.5, 6), (7.6, 6)]:
        yc = y[f"ge{thr}_h{h}"]
        tr, te, clim = masks(h, yc)
        full = _fit_eval_bss(X, yc, tr, te, improved, clim, rng, n_boot)[0]
        for f in DERIVED_COLS:
            drop = _fit_eval_bss(X, yc, tr, te, [c for c in improved if c != f], clim, rng, n_boot)[0]
            abl.append({"threshold": thr, "horizon": h, "feature": f, "bss_full": full,
                        "bss_without": drop, "contribution": full - drop})
            print(f"  [{thr}/{h}] drop {f}: Δ={full-drop:+.4f}", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(comp).to_csv(OUT / "feature_compare.csv", index=False)
    pd.DataFrame(abl).to_csv(OUT / "feature_ablation.csv", index=False)
    return {"out": str(OUT)}


def calibration_experiment(cache_dir: Path = CACHE_DIR, n_cells: int = 800, seed: int = 0,
                           n_boot: int = 200) -> dict:
    """C2: probability post-calibration (fit on val 2023, apply to test 2024). Isotonic for common
    thresholds, Platt/sigmoid for the rare heavy class (robust on few positives). Measures BSS raw vs
    calibrated (with CIs) and saves before/after reliability."""
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression
    X, y, meta = load_cache(cache_dir)
    ensure_model_features(X, y, meta)
    rng = np.random.default_rng(seed)
    cells = meta["cell"].unique()
    keep = set(rng.choice(cells, size=min(n_cells, len(cells)), replace=False))
    mask = meta["cell"].isin(keep).to_numpy()
    X, y, meta = X[mask].reset_index(drop=True), y[mask].reset_index(drop=True), meta[mask].reset_index(drop=True)
    years, times = meta["year"].to_numpy(), pd.to_datetime(meta["time"].values)

    comp, rel = [], []
    for thr, h in [(0.5, 6), (0.5, 24), (2.5, 12), (7.6, 6), (7.6, 24)]:
        yc = y[f"ge{thr}_h{h}"]
        emb_t = pd.Timestamp(f"{max(TRAIN_YEARS)}-12-31 23:00") - pd.Timedelta(hours=h)
        emb_v = pd.Timestamp(f"{VAL_YEAR}-12-31 23:00") - pd.Timedelta(hours=h)
        tr = np.isin(years, list(TRAIN_YEARS)) & ~(times > emb_t) & yc.notna().to_numpy()
        va = (years == VAL_YEAR) & ~(times > emb_v) & yc.notna().to_numpy()
        te = (years == TEST_YEAR) & yc.notna().to_numpy()
        if tr.sum() < 200 or va.sum() < 100 or te.sum() < 50 or not (0 < yc[tr].mean() < 1):
            continue
        model = LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31,
                               verbose=-1, random_state=42).fit(X.loc[tr, MODEL_FEATURES], yc[tr])
        pv, yv = model.predict_proba(X.loc[va, MODEL_FEATURES])[:, 1], yc[va].to_numpy()
        praw, yt = model.predict_proba(X.loc[te, MODEL_FEATURES])[:, 1], yc[te].to_numpy()
        if thr >= 7.6:  # rare → Platt (sigmoid), robust with few positives
            cal = LogisticRegression(max_iter=1000).fit(pv.reshape(-1, 1), yv)
            pcal = cal.predict_proba(praw.reshape(-1, 1))[:, 1]
            method = "platt"
        else:           # common → isotonic
            pcal = IsotonicRegression(out_of_bounds="clip").fit(pv, yv).transform(praw)
            method = "isotonic"
        table, glob = _cell_month_clim(yc, meta)
        clim = np.array([table.get(k, glob) for k in zip(meta.loc[te, "cell"], meta.loc[te, "month"])])
        b_raw = _bss_ci(praw, yt, clim, rng, n_boot)
        b_cal = _bss_ci(pcal, yt, clim, rng, n_boot)
        comp.append({"threshold": thr, "horizon": h, "method": method,
                     "bss_raw": b_raw[0], "bss_cal": b_cal[0], "delta": b_cal[0] - b_raw[0],
                     "cal_lo": b_cal[1], "cal_hi": b_cal[2]})
        for tag, p in [("raw", praw), ("calibrated", pcal)]:
            r = _reliability(p, yt)
            r["threshold"] = thr
            r["horizon"] = h
            r["kind"] = tag
            rel.append(r)
        print(f"  ge{thr}_h{h} [{method}]: raw={b_raw[0]:.3f} cal={b_cal[0]:.3f} Δ={b_cal[0]-b_raw[0]:+.3f}",
              flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(comp).to_csv(OUT / "calibration_compare.csv", index=False)
    pd.concat(rel).to_csv(OUT / "reliability_calib.csv", index=False)
    return {"out": str(OUT)}


_SEASON = {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM",
           6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON"}
_DETAIL_PAIRS = {(0.5, 6), (0.5, 24), (7.6, 6)}  # pairs that get per-cell error/motion/season breakdowns


def final_eval(cache_dir: Path = CACHE_DIR, seed: int = 42, n_boot: int = 200,
               far_budget: float = 0.1) -> dict:
    """The authoritative all-cells run (locked features, train 2015-22 / test 2024). Trains the 15 models
    once and emits every atlas layer: per-cell skill (full grid), per-cell false-alarm/miss + motion-penalty
    + seasonal skill (key pairs), events-per-cell, plus overall metrics/calibration/importance."""
    from sklearn.metrics import average_precision_score
    X, y, meta = load_cache(cache_dir)
    ensure_model_features(X, y, meta)
    rng = np.random.default_rng(seed)
    years, times = meta["year"].to_numpy(), pd.to_datetime(meta["time"].values)
    season = meta["month"].map(_SEASON).to_numpy()

    overall, pc, pcerr, pcm, pcs, imp = [], [], [], [], [], []
    for thr in THRESHOLDS_MM_HR:
        for h in HORIZONS_H:
            col = f"ge{thr}_h{h}"
            yc = y[col]
            emb = pd.Timestamp(f"{max(TRAIN_YEARS)}-12-31 23:00") - pd.Timedelta(hours=h)
            tr = np.isin(years, list(TRAIN_YEARS)) & ~(times > emb) & yc.notna().to_numpy()
            te = (years == TEST_YEAR) & yc.notna().to_numpy()
            if tr.sum() < 200 or te.sum() < 50 or not (0 < yc[tr].mean() < 1):
                continue
            model = LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31, verbose=-1,
                                   random_state=seed).fit(X.loc[tr, MODEL_FEATURES], yc[tr])
            p, yt = model.predict_proba(X.loc[te, MODEL_FEATURES])[:, 1], yc[te].to_numpy()
            table, glob = _cell_month_clim(yc, meta)
            clim = np.array([table.get(k, glob) for k in zip(meta.loc[te, "cell"], meta.loc[te, "month"])])
            bss, lo, hi = _bss_ci(p, yt, clim, rng, n_boot)
            overall.append({"threshold": thr, "horizon": h, "bss": bss, "ci_lo": lo, "ci_hi": hi,
                            "pr_auc_lift": average_precision_score(yt, p) / yt.mean() if yt.mean() > 0 else np.nan,
                            "pos_rate": float(yt.mean()), "n_test": int(te.sum())})
            for f, gi in zip(MODEL_FEATURES, model.feature_importances_):
                imp.append({"feature": f, "gain": float(gi), "threshold": thr, "horizon": h})

            # global decision point at the false-alarm budget (for per-cell error rates)
            op = _operating_points(p, yt, 50)
            ok = op[op["false_alarm_rate"] <= far_budget]
            dec = float(ok["decision"].min()) if len(ok) else 0.5
            df = pd.DataFrame({"cell": meta.loc[te, "cell"].to_numpy(), "motion": meta.loc[te, "motion"].to_numpy(),
                               "season": season[te], "lat": meta.loc[te, "lat"].to_numpy(),
                               "lon": meta.loc[te, "lon"].to_numpy(), "elev": meta.loc[te, "elevation"].to_numpy(),
                               "p": p, "y": yt, "clim": clim})
            detail = (thr, h) in _DETAIL_PAIRS
            for cell, g in df.groupby("cell"):
                bcc = _brier(g["clim"].to_numpy(), g["y"].to_numpy())
                rec = {"threshold": thr, "horizon": h, "cell": cell, "lat": g["lat"].iloc[0],
                       "lon": g["lon"].iloc[0], "elev": g["elev"].iloc[0], "n": int(len(g))}
                if len(g) >= 20 and 0 < g["y"].mean() < 1 and bcc > 0:
                    rec["bss"] = 1.0 - _brier(g["p"].to_numpy(), g["y"].to_numpy()) / bcc
                else:
                    rec["bss"] = np.nan
                pc.append(rec)
                if detail and len(g) >= 20:
                    pred = g["p"].to_numpy() >= dec
                    yy = g["y"].to_numpy().astype(bool)
                    fp, tn = int((pred & ~yy).sum()), int((~pred & ~yy).sum())
                    fn, tp = int((~pred & yy).sum()), int((pred & yy).sum())
                    pcerr.append({"threshold": thr, "horizon": h, "cell": cell, "lat": rec["lat"],
                                  "lon": rec["lon"], "fa_rate": fp / (fp + tn) if fp + tn else np.nan,
                                  "miss_rate": fn / (fn + tp) if fn + tp else np.nan})
            if detail:
                for (cell, mc), g in df.groupby(["cell", "motion"]):
                    bcc = _brier(g["clim"].to_numpy(), g["y"].to_numpy())
                    if len(g) >= 15 and 0 < g["y"].mean() < 1 and bcc > 0:
                        pcm.append({"threshold": thr, "horizon": h, "cell": cell, "motion": mc,
                                    "lat": g["lat"].iloc[0], "lon": g["lon"].iloc[0],
                                    "bss": 1.0 - _brier(g["p"].to_numpy(), g["y"].to_numpy()) / bcc})
                for (cell, se), g in df.groupby(["cell", "season"]):
                    bcc = _brier(g["clim"].to_numpy(), g["y"].to_numpy())
                    if len(g) >= 15 and 0 < g["y"].mean() < 1 and bcc > 0:
                        pcs.append({"threshold": thr, "horizon": h, "cell": cell, "season": se,
                                    "lat": g["lat"].iloc[0], "lon": g["lon"].iloc[0],
                                    "bss": 1.0 - _brier(g["p"].to_numpy(), g["y"].to_numpy()) / bcc})
            print(f"  ge{thr}_h{h}: bss={bss:.3f} [{lo:.3f},{hi:.3f}] cells={len(df.groupby('cell'))}",
                  flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in [("metrics_overall", overall), ("per_cell", pc), ("per_cell_error", pcerr),
                       ("per_cell_motion", pcm), ("per_cell_season", pcs), ("importance", imp)]:
        pd.DataFrame(data).to_csv(OUT / f"{name}.csv", index=False)
    return {"models": len(overall), "out": str(OUT)}


def _recall_at_far(p: np.ndarray, yt: np.ndarray, far_budget: float = 0.1) -> float:
    """Best recall achievable while keeping the false-alarm rate ≤ budget (the actionable banner point)."""
    op = _operating_points(p, yt, n=50)
    ok = op[op["false_alarm_rate"] <= far_budget]
    return float(ok["recall"].max()) if len(ok) else 0.0


def weighting_experiment(cache_dir: Path = CACHE_DIR, n_cells: int = 800, seed: int = 0) -> dict:
    """C3: does scale_pos_weight help the rare heavy class, or just rescale? Compares RANKING (PR-AUC,
    ROC-AUC — threshold-free) and recall@FAR≤0.1 across weightings. If ranking is unchanged, weighting is
    redundant with simply lowering the decision threshold."""
    from sklearn.metrics import average_precision_score, roc_auc_score
    X, y, meta = load_cache(cache_dir)
    ensure_model_features(X, y, meta)
    rng = np.random.default_rng(seed)
    cells = meta["cell"].unique()
    keep = set(rng.choice(cells, size=min(n_cells, len(cells)), replace=False))
    mask = meta["cell"].isin(keep).to_numpy()
    X, y, meta = X[mask].reset_index(drop=True), y[mask].reset_index(drop=True), meta[mask].reset_index(drop=True)
    years, times = meta["year"].to_numpy(), pd.to_datetime(meta["time"].values)

    rows = []
    for thr, h in [(7.6, 6), (7.6, 24), (2.5, 6)]:
        yc = y[f"ge{thr}_h{h}"]
        emb = pd.Timestamp(f"{max(TRAIN_YEARS)}-12-31 23:00") - pd.Timedelta(hours=h)
        tr = np.isin(years, list(TRAIN_YEARS)) & ~(times > emb) & yc.notna().to_numpy()
        te = (years == TEST_YEAR) & yc.notna().to_numpy()
        if tr.sum() < 200 or te.sum() < 50 or not (0 < yc[tr].mean() < 1):
            continue
        pos = float(yc[tr].sum())
        neg = float(tr.sum() - pos)
        for name, spw in [("none", 1.0), ("balanced", neg / pos), ("sqrt", (neg / pos) ** 0.5)]:
            model = LGBMClassifier(n_estimators=300, learning_rate=0.05, num_leaves=31, verbose=-1,
                                   random_state=42, scale_pos_weight=spw).fit(X.loc[tr, MODEL_FEATURES], yc[tr])
            p, yt = model.predict_proba(X.loc[te, MODEL_FEATURES])[:, 1], yc[te].to_numpy()
            rows.append({"threshold": thr, "horizon": h, "weighting": name, "spw": round(spw, 1),
                         "pr_auc": average_precision_score(yt, p), "roc_auc": roc_auc_score(yt, p),
                         "recall_at_far10": _recall_at_far(p, yt, 0.1), "pos_rate": float(yt.mean())})
            print(f"  ge{thr}_h{h} spw={name}: pr_auc={rows[-1]['pr_auc']:.3f} "
                  f"roc={rows[-1]['roc_auc']:.3f} recall@far.1={rows[-1]['recall_at_far10']:.3f}", flush=True)

    OUT.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(OUT / "weighting_compare.csv", index=False)
    return {"out": str(OUT)}


def run(k_per_cell_month: int = 6, n_cells: int | None = None, seed: int = 0,
        years: list[int] | None = None) -> dict:
    cells = pd.read_csv(SAMPLED_CSV)
    if n_cells is not None:
        cells = cells.iloc[:n_cells].reset_index(drop=True)
    if years is None:
        years = list(TRAIN_YEARS) + [VAL_YEAR, TEST_YEAR]
    print(f"cells: {len(cells)} | endpoints/cell/month: {k_per_cell_month} | years: {years}", flush=True)

    print("1. GPM labels (per-cell hourly precip)...", flush=True)
    gpm_times, precip = load_gpm_cells_hourly(cells["lat"].to_numpy(), cells["lon"].to_numpy(),
                                              min(years), max(years))
    print(f"   GPM hours: {len(gpm_times)}", flush=True)

    print("2-4. Streaming ERA5, building motion endpoints...", flush=True)
    X, y, meta = build_dataset(cells, gpm_times, precip, k_per_cell_month, years,
                               MotionSimParams(), seed=seed)
    print(f"   dataset: X={X.shape} y={y.shape}", flush=True)

    print("5-6. Train + evaluate...", flush=True)
    res = train_and_eval(X, y, meta)
    print(f"done: {res}", flush=True)
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-cache", action="store_true", help="build + cache the dataset, no training")
    ap.add_argument("--from-cache", action="store_true", help="train + evaluate off the cached dataset")
    ap.add_argument("--learning-curve", action="store_true", help="cells learning curve off the cache")
    ap.add_argument("--feature-compare", action="store_true", help="B2-B5 feature wins comparison")
    ap.add_argument("--calibration", action="store_true", help="C2 probability calibration with/without")
    ap.add_argument("--weighting", action="store_true", help="C3 scale_pos_weight for the heavy class")
    ap.add_argument("--final-eval", action="store_true", help="authoritative all-cells run + atlas data")
    ap.add_argument("--all-cells", action="store_true", help="use every land cell (full build)")
    ap.add_argument("--k", type=int, default=6, help="endpoints per cell per month")
    ap.add_argument("--n-cells", type=int, default=None, help="limit cells (smoke test)")
    ap.add_argument("--years", type=str, default=None, help="range '2015-2024' or list '2016,2024'")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    if args.years and "-" in args.years and "," not in args.years:
        a, b = args.years.split("-")
        yrs = list(range(int(a), int(b) + 1))
    elif args.years:
        yrs = [int(x) for x in args.years.split(",")]
    else:
        yrs = None

    if args.build_cache:
        print(build_cache(yrs or list(range(2015, 2025)), k_per_cell_month=args.k,
                          all_cells=args.all_cells, n_cells=args.n_cells, seed=args.seed))
    elif args.from_cache:
        print(train_from_cache(n_cells=args.n_cells, seed=args.seed))
    elif args.learning_curve:
        print(learning_curve(seed=args.seed))
    elif args.feature_compare:
        print(compare_feature_sets(seed=args.seed))
    elif args.calibration:
        print(calibration_experiment(seed=args.seed))
    elif args.weighting:
        print(weighting_experiment(seed=args.seed))
    elif args.final_eval:
        print(final_eval(seed=args.seed))
    else:
        run(k_per_cell_month=args.k, n_cells=args.n_cells, seed=args.seed, years=yrs)
