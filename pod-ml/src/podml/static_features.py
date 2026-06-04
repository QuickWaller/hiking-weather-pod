"""Static geographic features for grid-based training.

Per-cell features that don't change with time (elevation, climate zone, baseline rainfall).
These provide geographic context so the model learns "dry locations have less rain"
and can transfer across regions.

Pod can query these at runtime (static info via GPS + lookup table).

Workflow:
  1. Load DEM (elevation at each grid cell)
  2. Compute 20-year climatology (1990–2020 or 2010–2022 mean rainfall/pressure from ERA5)
  3. Join to features as additional columns
  4. Train model on (dynamic features + static features) across all cells
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

from podml.config import DATA_RAW


def load_dem_grid(dem_path: Path | None = None) -> xr.DataArray:
    """Load digital elevation model (DEM) for NZ.

    Args:
        dem_path: path to DEM NetCDF (default: data/raw/dem_nz.nc, from download_dem.py)

    Returns:
        xr.DataArray with dimensions (lat, lon), values = elevation in meters
    """
    if dem_path is None:
        dem_path = DATA_RAW / "dem_nz.nc"

    if not dem_path.exists():
        raise FileNotFoundError(f"DEM not found at {dem_path}")

    ds = xr.open_dataset(dem_path)
    # Expect variable named 'elevation', 'dem', 'alt', or similar
    elev_var = next(
        (v for v in ds.data_vars if any(n in v.lower() for n in ["elev", "dem", "alt"])),
        None,
    )
    if elev_var is None:
        raise ValueError(f"No elevation variable found in {dem_path}")

    return ds[elev_var]


def compute_climatology(
    era5_dir: Path | None = None,
    start_year: int = 2010,
    end_year: int = 2022,
) -> dict[str, xr.DataArray]:
    """Compute 20-year mean (climatology) from ERA5 gridded data.

    Args:
        era5_dir: directory with ERA5 monthly/hourly grids
        start_year, end_year: range for climatology

    Returns:
        dict with keys "precip_mean", "pressure_mean", "temp_mean", "humidity_mean"
        Each value is a DataArray with dimensions (lat, lon)

    Note: This is a placeholder. Real implementation would:
      1. Download ERA5 monthly grids via CDS
      2. Resample to daily if needed
      3. Compute mean over time dimension
    """
    if era5_dir is None:
        era5_dir = DATA_RAW / "era5_grid"

    if not era5_dir.exists():
        raise FileNotFoundError(
            f"ERA5 grid directory not found at {era5_dir}. "
            "Run: python -m podml.download_era5_grid"
        )

    # Placeholder: return dummy DataArrays with proper structure
    # In production, would load actual ERA5 grids and compute
    return {
        "precip_mean": None,  # type: ignore[assignment]
        "pressure_mean": None,  # type: ignore[assignment]
        "temp_mean": None,  # type: ignore[assignment]
        "humidity_mean": None,  # type: ignore[assignment]
    }


def elevation_to_zones(elevation: np.ndarray, thresholds: list[int] | None = None) -> np.ndarray:
    """Map elevation to discrete climate zones.

    Args:
        elevation: elevation in meters (array)
        thresholds: elevation cutoffs in meters (default: NZ-appropriate)

    Returns:
        np.ndarray of zone IDs (0=lowland, 1=hill, 2=alpine, etc.)
    """
    if thresholds is None:
        thresholds = [300, 1000, 2000]  # NZ-appropriate

    zones = np.zeros_like(elevation, dtype=int)
    for i, thr in enumerate(thresholds):
        zones[elevation >= thr] = i + 1

    return zones


def static_features_at_points(
    lats: np.ndarray,
    lons: np.ndarray,
    dem: xr.DataArray | None = None,
    climatology: dict[str, xr.DataArray] | None = None,
) -> pd.DataFrame:
    """Extract static features for a set of (lat, lon) points.

    Args:
        lats, lons: coordinate arrays (n,)
        dem: elevation DataArray (lat, lon)
        climatology: dict of climate variables (lat, lon)

    Returns:
        pd.DataFrame with columns: elevation, zone, precip_mean, pressure_mean, etc.
    """
    if dem is None:
        dem = load_dem_grid()

    features = pd.DataFrame({"lat": lats, "lon": lons})

    # Nearest-neighbor extraction
    elev = np.array([float(dem.sel(lat=lat, lon=lon, method="nearest")) for lat, lon in zip(lats, lons)])
    features["elevation"] = elev
    features["zone"] = elevation_to_zones(elev)

    if climatology:
        for var_name, var_da in climatology.items():
            if var_da is not None:
                vals = np.array(
                    [float(var_da.sel(lat=lat, lon=lon, method="nearest")) for lat, lon in zip(lats, lons)]
                )
                features[var_name] = vals

    return features


def add_static_to_features(
    dynamic_features: pd.DataFrame,
    lat: float,
    lon: float,
    dem: xr.DataArray | None = None,
    climatology: dict[str, Any] | None = None,
) -> pd.DataFrame:
    """Add static features to a time series of dynamic features.

    Args:
        dynamic_features: DataFrame with DatetimeIndex, dynamic columns (pressure, temp, humidity)
        lat, lon: location
        dem: elevation DataArray
        climatology: climate variables dict

    Returns:
        DataFrame with dynamic + static columns, same index as input
    """
    if dem is None:
        dem = load_dem_grid()

    df = dynamic_features.copy()

    # Static features are constant per location, repeat for all timesteps
    elev = float(dem.sel(lat=lat, lon=lon, method="nearest"))
    df["elevation"] = elev
    df["zone"] = elevation_to_zones(np.array([elev]))[0]

    if climatology:
        for var_name, var_da in climatology.items():
            if var_da is not None:
                val = float(var_da.sel(lat=lat, lon=lon, method="nearest"))
                df[var_name] = val

    return df
