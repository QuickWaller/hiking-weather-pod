"""Label engineering from GPM IMERG satellite rainfall (honest, non-circular labels).

Unlike labels.py (which uses ERA5 precip, circular), GPM IMERG is satellite-measured
rainfall independent of ERA5's physics. Honest ground truth for model validation.

Resamples GPM's native 30-min data to hourly (max of 2 half-hours), then applies the
same forward-looking window logic as labels.py to build binary rain-severity labels.
Partial data handling: only months present on disk are loaded; missing months create gaps
that dropna() handles downstream.

Usage:
  from podml.labels_gpm import build_labels_gpm
  labels_df = build_labels_gpm(lat=-41.5, lon=171.1)  # hokitika_westcoast
  # Output: pd.DataFrame indexed by "valid_time", 12 columns (ge{thr}_h{h})
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import xarray as xr

from podml.config import DATA_RAW
from podml.labels import HORIZONS_H, THRESHOLDS_MM_HR, forward_window_max


def _open_gpm_grid(path: Path) -> xr.Dataset:
    """Open GPM monthly grid, handling the 'Grid' group structure."""
    try:
        ds = xr.open_dataset(path, group="Grid")
    except Exception:
        # If "Grid" group doesn't exist, try root
        ds = xr.open_dataset(path)
    return ds


def load_gpm_point(lat: float, lon: float, gpm_dir: Optional[Path] = None) -> pd.Series:
    """Load all available GPM monthly grids, extract nearest lat/lon → 30-min pd.Series.

    Args:
        lat, lon: probe point coordinates
        gpm_dir: directory of gpm_YYYY-MM.nc files (default: DATA_RAW / "gpm_grid")

    Returns:
        pd.Series indexed by pd.DatetimeIndex (30-min NZDT), values in mm/hr.
        If no GPM files exist, returns empty Series.
    """
    if gpm_dir is None:
        gpm_dir = DATA_RAW / "gpm_grid"

    gpm_files = sorted(gpm_dir.glob("gpm_*.nc"))
    if not gpm_files:
        return pd.Series([], dtype="float64")

    series_list = []
    for fpath in gpm_files:
        try:
            ds = _open_gpm_grid(fpath)
            precip = ds["precipitation"].sel(lon=lon, lat=lat, method="nearest")
            times = pd.to_datetime(precip["time"].values)
            s = pd.Series(precip.values.astype("float64"), index=times)
            series_list.append(s)
            ds.close()
        except Exception as e:
            # Skip months with missing/corrupted files; partial data is OK
            print(f"[load_gpm_point] {fpath.name}: skipped ({e})", flush=True)
            continue

    if not series_list:
        return pd.Series([], dtype="float64")
    return pd.concat(series_list).sort_index()


def load_gpm_cells_hourly(
    lats, lons, start_year: int, end_year: int, gpm_dir: Optional[Path] = None
) -> tuple[pd.DatetimeIndex, np.ndarray]:
    """Hourly GPM precip (mm/hr) for MANY cells at once, over [start_year, end_year].

    Efficient counterpart to load_gpm_point: opens each monthly grid once and selects all requested
    cells in one vectorised nearest-neighbour lookup, then resamples 30-min → hourly max (aligning to
    ERA5's on-the-hour valid_time). GPM cell centres are offset ~0.05° from ERA5's; nearest handles it.

    Args:
        lats, lons: 1-D arrays of cell coordinates (length n_cells).
        start_year, end_year: inclusive year range.
        gpm_dir: directory of gpm_YYYY-MM.nc (default DATA_RAW/"gpm_grid").

    Returns:
        (times, precip) where times is an hourly DatetimeIndex and precip is (n_time, n_cells) mm/hr.
        Missing months are simply absent from the time axis (partial data is fine).
    """
    if gpm_dir is None:
        gpm_dir = DATA_RAW / "gpm_grid"
    lat_da = xr.DataArray(np.asarray(lats, dtype="float64"), dims="cell")
    lon_da = xr.DataArray(np.asarray(lons, dtype="float64"), dims="cell")

    parts: list[pd.DataFrame] = []
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            fpath = gpm_dir / f"gpm_{year}-{month:02d}.nc"
            if not fpath.exists():
                continue
            ds = _open_gpm_grid(fpath)
            p = ds["precipitation"].sel(lat=lat_da, lon=lon_da, method="nearest")  # (time, cell)
            df = pd.DataFrame(
                p.transpose("time", "cell").values.astype("float64"),
                index=pd.to_datetime(ds["time"].values),
            )
            parts.append(df.resample("h").max())  # 30-min → hourly max, on-the-hour
            ds.close()

    if not parts:
        return pd.DatetimeIndex([]), np.empty((0, len(np.asarray(lats))))
    full = pd.concat(parts).sort_index()
    return full.index, full.values


def resample_to_hourly(s: pd.Series) -> pd.Series:
    """Resample 30-min GPM data → hourly max, aligned to hour boundaries.

    Each output hour (HH:00) contains the max of the 2 half-hours within it.
    This aligns to ERA5's hourly valid_time timestamps (on-the-hour).

    Args:
        s: 30-min pd.Series (time index in NZDT or UTC)

    Returns:
        Hourly pd.Series with DatetimeIndex on hour boundaries (HH:00:00).
    """
    hourly = s.resample("h").max()
    return hourly


def build_labels_gpm(
    lat: float,
    lon: float,
    gpm_dir: Optional[Path] = None,
    horizons: list[int] = HORIZONS_H,
    thresholds: list[float] = THRESHOLDS_MM_HR,
) -> pd.DataFrame:
    """Build binary rain-severity labels from GPM IMERG.

    Output format matches labels.build_labels() exactly, so it drops in to probe.py
    without changes.

    Args:
        lat, lon: probe point
        gpm_dir: directory of gpm_*.nc files
        horizons: lead times (hours): [6, 12, 24, 48]
        thresholds: rain intensities (mm/hr): [0.5, 2.5, 7.6]

    Returns:
        pd.DataFrame:
            Index: pd.DatetimeIndex named "valid_time" (hourly, on-the-hour)
            Columns: 12 total, one per (threshold, horizon) pair
                e.g., "ge0.5_h6", "ge2.5_h12", "ge7.6_h48"
            Values: float64, 0.0 or 1.0 (or NaN for tail with incomplete future)
    """
    precip_30min = load_gpm_point(lat, lon, gpm_dir)
    if precip_30min.empty:
        return pd.DataFrame()

    precip_hourly = resample_to_hourly(precip_30min)
    precip_values = precip_hourly.values

    times = precip_hourly.index
    df = pd.DataFrame(index=times)
    df.index.name = "valid_time"

    for h in horizons:
        fmax = forward_window_max(precip_values, h)
        for thr in thresholds:
            lab = (fmax >= thr).astype("float64")
            lab[np.isnan(fmax)] = np.nan
            df[f"ge{thr}_h{h}"] = lab

    return df
