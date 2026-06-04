"""Grid-based model training: pool every NZ ERA5 cell instead of 5 probe points.

Each (timestep, grid-cell) pair is one training row. Stacking thousands of cells
gives the model geographic variety — elevation, climate zone, and 20-year
climatology per cell — so it can learn "dry lee cells rain less" instead of
memorising "rain is frequent" from a handful of wet points.

Pipeline:
  1. Load ERA5 grid for NZ from ARCO-ERA5 (load_era5_zarr.load_era5_nz)
  2. Regrid the DEM onto the ERA5 lat/lon grid (different native resolutions)
  3. Compute per-cell climatology (mean over the training years)
  4. Stack (time, cell) -> rows: dynamic features + static features
  5. Build labels per cell with forward_window_max ALONG TIME (no cross-cell leak)
  6. Train one LightGBM per (threshold, horizon) on the pooled rows

Memory note: one NZ year is ~8760 h x ~2600 cells ~= 23M rows. ``n_cells_sample``
draws a random subset of cells (full time series each, so windowing stays valid)
to keep training tractable; raise it for the final model.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr
from lightgbm import LGBMClassifier
from numpy.lib.stride_tricks import sliding_window_view

from podml.labels import HORIZONS_H, THRESHOLDS_MM_HR
from podml.load_era5_zarr import load_era5_nz
from podml.static_features import elevation_to_zones, load_dem_grid

# Feature columns in a fixed order (dynamic first, then static per-cell).
FEATURE_COLS = [
    "sp_hPa", "t2m_C", "rh", "month", "hour_utc",
    "elevation", "zone", "precip_mean", "pressure_mean", "temp_mean",
]


def _forward_window_max_2d(x: np.ndarray, h: int) -> np.ndarray:
    """forward_window_max applied independently down axis 0 (per cell/column).

    x: (n_time, n_cells). Returns (n_time, n_cells) where out[T, c] =
    max(x[T+1 .. T+h, c]); the last h rows are NaN (incomplete future).
    Windowing never crosses the column boundary, so cells stay independent.
    """
    x = np.asarray(x, dtype="float64")
    n = x.shape[0]
    out = np.full_like(x, np.nan)
    if n > h:
        # sliding_window_view over time -> (n_time-h+1, n_cells, h); max over window.
        wmax = sliding_window_view(x, h, axis=0).max(axis=-1)  # (n_time-h+1, n_cells)
        out[: n - h] = wmax[1 : n - h + 1]
    return out


def compute_climatology_from_era5(ds: xr.Dataset) -> dict[str, np.ndarray]:
    """Per-cell climatology (mean over time) for precip/pressure/temp.

    Returns dict {precip_mean, pressure_mean, temp_mean} each shaped (n_lat, n_lon).
    """
    out: dict[str, np.ndarray] = {}
    for key, var in {"precip": "tp", "pressure": "sp", "temp": "t2m"}.items():
        if var in ds.data_vars:
            out[f"{key}_mean"] = ds[var].mean(dim="time").values
    return out


def grid_to_xy(
    ds: xr.Dataset,
    dem_on_grid: xr.DataArray,
    climatology: dict[str, np.ndarray],
    horizons: list[int] = HORIZONS_H,
    thresholds: list[float] = THRESHOLDS_MM_HR,
) -> tuple[pd.DataFrame, pd.DataFrame, np.ndarray]:
    """Stack the grid into (features, labels, times) with one row per (time, cell).

    Args:
        ds: ERA5 Dataset with short-named vars (sp, t2m, d2m, tp) on time/lat/lon.
        dem_on_grid: elevation already interpolated onto ds's (lat, lon) grid.
        climatology: per-cell means from compute_climatology_from_era5 (n_lat, n_lon).

    Returns:
        X: features DataFrame (n_time*n_cells, len(FEATURE_COLS)).
        y: label DataFrame, columns ge{thr}_h{h}, same rows as X.
        times: datetime64 array aligned to X rows (for year-based splits).

    Row order is C-order over (n_time, n_cells): row = t*n_cells + c. Every array
    below is flattened the same way, so features, labels and times stay aligned.
    """
    ds = ds.transpose("time", "lat", "lon")
    n_time = ds.sizes["time"]
    n_cells = ds.sizes["lat"] * ds.sizes["lon"]

    sp = ds["sp"].values.reshape(n_time, n_cells) / 100.0    # Pa -> hPa
    t2m = ds["t2m"].values.reshape(n_time, n_cells) - 273.15  # K -> C
    d2m = ds["d2m"].values.reshape(n_time, n_cells) - 273.15
    a, b = 17.625, 243.04
    rh = np.clip(
        100.0 * np.exp(a * d2m / (b + d2m)) / np.exp(a * t2m / (b + t2m)), 0.0, 100.0
    )

    times = pd.to_datetime(ds["time"].values)
    month = np.repeat(times.month.to_numpy(), n_cells)
    hour = np.repeat(times.hour.to_numpy(), n_cells)

    elev_cells = dem_on_grid.values.reshape(n_cells)
    zone_cells = elevation_to_zones(elev_cells)

    X = pd.DataFrame({
        "sp_hPa": sp.reshape(-1),
        "t2m_C": t2m.reshape(-1),
        "rh": rh.reshape(-1),
        "month": month,
        "hour_utc": hour,
        "elevation": np.tile(elev_cells, n_time),
        "zone": np.tile(zone_cells, n_time),
        "precip_mean": np.tile(climatology["precip_mean"].reshape(n_cells), n_time),
        "pressure_mean": np.tile(climatology["pressure_mean"].reshape(n_cells), n_time),
        "temp_mean": np.tile(climatology["temp_mean"].reshape(n_cells), n_time),
    })[FEATURE_COLS]

    tp_mm = np.clip(ds["tp"].values.reshape(n_time, n_cells) * 1000.0, 0.0, None)
    y = pd.DataFrame(index=X.index)
    for h in horizons:
        fmax = _forward_window_max_2d(tp_mm, h)  # (n_time, n_cells)
        fflat = fmax.reshape(-1)
        for thr in thresholds:
            lab = (fflat >= thr).astype("float64")
            lab[np.isnan(fflat)] = np.nan
            y[f"ge{thr}_h{h}"] = lab

    times_row = np.repeat(times.to_numpy(), n_cells)
    return X, y, times_row


def _dem_on_era5_grid(ds: xr.Dataset) -> xr.DataArray:
    """Interpolate the native DEM onto ds's (lat, lon) grid (linear, nearest fill)."""
    dem = load_dem_grid()
    on_grid = dem.interp(lat=ds["lat"], lon=ds["lon"], method="linear")
    # Edge cells can fall outside the DEM extent -> fill with nearest.
    if np.isnan(on_grid.values).any():
        on_grid = on_grid.fillna(dem.interp(lat=ds["lat"], lon=ds["lon"], method="nearest"))
    return on_grid


def train_grid_model(
    train_years: range = range(2021, 2022),
    test_year: int = 2024,
    n_cells_sample: int | None = 400,
    seed: int = 42,
) -> dict:
    """Train one LightGBM per (threshold, horizon) on pooled NZ grid cells.

    Args:
        train_years: years to train on (inclusive range).
        test_year: held-out year for evaluation.
        n_cells_sample: random subset of grid cells (None = all). Each sampled cell
            keeps its full time series, so labels stay leak-free.
        seed: RNG seed for cell sampling.

    Returns:
        dict with status, trained models, and per-model train/test row counts.
    """
    print("=== Grid-based training ===\n")
    print(f"1. Loading ERA5 grid: train {min(train_years)}-{max(train_years)}, test {test_year}")
    # Load ONLY the years we use (train years + test year), each cached on its own,
    # rather than the contiguous span — avoids pulling unused middle years.
    years = sorted(set(train_years) | {test_year})
    ds = xr.concat([load_era5_nz(start_year=y, end_year=y) for y in years], dim="time").load()

    print("2. Regridding DEM onto ERA5 grid...")
    dem_on_grid = _dem_on_era5_grid(ds)

    print("3. Climatology (train years only, to avoid test leakage)...")
    ds_train_clim = ds.sel(time=ds["time"].dt.year.isin(list(train_years)))
    climatology = compute_climatology_from_era5(ds_train_clim)

    print("4. Stacking grid to rows...")
    X, y, times = grid_to_xy(ds, dem_on_grid, climatology)
    years_row = pd.DatetimeIndex(times).year.to_numpy()
    print(f"   full matrix: {X.shape}")

    # Cell subsample: keep whole-time-series for a random subset of cells.
    if n_cells_sample is not None:
        n_cells = ds.sizes["lat"] * ds.sizes["lon"]
        rng = np.random.default_rng(seed)
        keep_cells = np.zeros(n_cells, dtype=bool)
        keep_cells[rng.choice(n_cells, size=min(n_cells_sample, n_cells), replace=False)] = True
        n_time = len(times) // n_cells
        cell_mask = np.tile(keep_cells, n_time)
        X, y, years_row = X[cell_mask].reset_index(drop=True), y[cell_mask].reset_index(drop=True), years_row[cell_mask]
        print(f"   sampled {n_cells_sample} cells -> {X.shape}")

    train_mask = np.isin(years_row, list(train_years))
    test_mask = years_row == test_year

    print("5. Training LightGBM per (threshold, horizon)...")
    models, counts = {}, {}
    for thr in THRESHOLDS_MM_HR:
        for h in HORIZONS_H:
            col = f"ge{thr}_h{h}"
            tr = X[train_mask].join(y.loc[train_mask, col]).dropna()
            n_test = int((~np.isnan(y.loc[test_mask, col].to_numpy())).sum())
            if len(tr) > 100 and 0 < tr[col].mean() < 1:
                model = LGBMClassifier(
                    n_estimators=100, learning_rate=0.1, num_leaves=31,
                    verbose=-1, random_state=seed,
                )
                model.fit(tr[FEATURE_COLS], tr[col])
                models[col] = model
                counts[col] = {"n_train": len(tr), "n_test": n_test, "pos_rate": float(tr[col].mean())}
                print(f"   {col}: train={len(tr)} test={n_test} pos={tr[col].mean():.3f}")
            else:
                print(f"   {col}: skipped (insufficient/degenerate)")

    return {
        "status": "success",
        "models": models,
        "counts": counts,
        "n_features": len(FEATURE_COLS),
        "n_cells_sample": n_cells_sample,
    }


if __name__ == "__main__":
    result = train_grid_model()
    print(f"\nStatus: {result['status']} | models trained: {len(result['models'])}")
