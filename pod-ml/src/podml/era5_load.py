"""Load cached NZ ERA5-Land gridded months for training.

`download_era5_grid` writes one normalised NetCDF per month to
``data/raw/era5_grid/<group>/era5land_nz_<year>-<month>.nc``.
This module opens the cached months for a requested year range and
concatenates them along ``valid_time``.

No network access — fetching is the CDS step in `download_era5_grid`;
this is a pure local read, kept lazy (``open_mfdataset``) so callers
can subsample cells before materialising (the 0.1° grid is ~16k cells,
~2 GB per year in RAM).
"""

from __future__ import annotations

from pathlib import Path

import xarray as xr

from podml.config import DATA_RAW

ERA5_GRID_DIR = DATA_RAW / "era5_grid"


def era5_cache_dir(group: str = "core") -> Path:
    return ERA5_GRID_DIR / group


def month_files(start_year: int, end_year: int, group: str = "core") -> list[Path]:
    """Cached ERA5-Land month files for [start_year, end_year], chronologically."""
    cache = era5_cache_dir(group)
    files: list[Path] = []
    for y in range(start_year, end_year + 1):
        files += sorted(cache.glob(f"era5land_nz_{y}-*.nc"))
    return files


def load_era5_nz(
    start_year: int = 2010,
    end_year: int = 2022,
    group: str = "core",
    **_: object,
) -> xr.Dataset | None:
    """Open cached ERA5-Land months in [start_year, end_year], concat on valid_time.

    Returns None if no months are cached for the range. Lazy by default so callers
    can stride/subsample cells before ``.load()`` — essential on the fine 0.1° grid
    where a full year is ~2 GB.
    """
    files = month_files(start_year, end_year, group)
    if not files:
        return None
    return xr.open_mfdataset(files, combine="by_coords", engine="netcdf4")


def load_point_from_grid(
    name: str,
    cfg: dict,
    start_year: int = 2010,
    end_year: int = 2024,
    group: str = "core",
) -> xr.Dataset:
    """Extract a single probe-point time series from the gridded cache.

    Selects the nearest 0.1° grid cell to the probe point's lat/lon and
    returns a Dataset with only the time dimension — same structure as the
    old era5land_ts_* point files.
    """
    pt = cfg["probe_points"][name]
    ds = load_era5_nz(start_year, end_year, group=group)
    if ds is None:
        raise FileNotFoundError(
            f"No ERA5 grid files found for group='{group}' {start_year}–{end_year}. "
            f"Run: python -m podml.download_era5_grid --group {group}"
        )
    return ds.sel(lat=pt["lat"], lon=pt["lon"], method="nearest").compute()
