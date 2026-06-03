"""Loading downloaded data files into xarray Datasets."""

from __future__ import annotations

import zipfile
from pathlib import Path

import xarray as xr


def load_timeseries(path: Path) -> xr.Dataset:
    """Load a CDS ERA5-Land time-series download into one merged Dataset.

    The time-series endpoint returns a .zip of per-group NetCDF files (wind /
    2m-temperature / pressure-precipitation) even when data_format=netcdf. We extract
    once (cached in a sibling ``_nc`` dir; delete it to reclaim space) and merge on the
    shared time/location coords. ``compat='override'`` is correct because all groups
    share identical coords, and it silences the no_conflicts FutureWarning.
    """
    if zipfile.is_zipfile(path):
        extract_dir = Path(f"{path.with_suffix('')}_nc")
        ncs = sorted(extract_dir.glob("*.nc")) if extract_dir.exists() else []
        if not ncs:
            extract_dir.mkdir(exist_ok=True)
            with zipfile.ZipFile(path) as z:
                z.extractall(extract_dir)
            ncs = sorted(extract_dir.glob("*.nc"))
        return xr.merge([xr.open_dataset(f) for f in ncs], compat="override")
    return xr.open_dataset(path)
