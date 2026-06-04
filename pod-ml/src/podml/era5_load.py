"""Load the cached NZ ERA5-Land grid (downloaded per-month from CDS) for training.

`download_era5_grid` writes one normalised NetCDF per month to
``data/raw/era5_grid/era5land_nz_<year>-<month>.nc`` on the project convention
(``valid_time`` / ``lat`` / ``lon`` ; vars ``sp,t2m,d2m,tp``). This module opens the
cached months for a requested year range and concatenates them along ``valid_time``.

No network access — fetching is the CDS step in `download_era5_grid`; this is a pure
local read, kept lazy (``open_mfdataset``) so callers can subsample cells before
materialising (the 0.1° grid is ~16k cells, ~2 GB per year in RAM).
"""

from __future__ import annotations

from pathlib import Path

import xarray as xr

from podml.config import DATA_RAW

ERA5_GRID_CACHE = DATA_RAW / "era5_grid"


def month_files(start_year: int, end_year: int) -> list[Path]:
    """Cached ERA5-Land month files for [start_year, end_year], chronologically."""
    files: list[Path] = []
    for y in range(start_year, end_year + 1):
        files += sorted(ERA5_GRID_CACHE.glob(f"era5land_nz_{y}-*.nc"))
    return files


def load_era5_nz(
    start_year: int = 2010,
    end_year: int = 2022,
    **_: object,
) -> xr.Dataset | None:
    """Open cached ERA5-Land months in [start_year, end_year], concat on valid_time.

    Returns None if no months are cached for the range (the caller decides). Lazy by
    default so callers can stride/subsample cells before ``.load()`` — essential on
    the fine 0.1° grid where a full year is ~2 GB.
    """
    files = month_files(start_year, end_year)
    if not files:
        return None
    return xr.open_mfdataset(files, combine="by_coords", engine="netcdf4")
