"""Load ERA5 for NZ from Google's ARCO-ERA5 Zarr store, with a local disk cache.

ARCO-ERA5 (Analysis-Ready, Cloud-Optimized ERA5) is published by Google Research
on a public GCS bucket — anonymous access (``token="anon"``). It is chunked at one
timestep per chunk, so pulling a multi-year NZ slice means tens of thousands of
tiny network reads and is slow. We therefore pull each year ONCE and cache it as a
local NetCDF; every later call reads from disk at local speed.

  Store : gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3
  Span  : 1940 .. present, hourly, 0.25° global
  Cache : data/raw/era5_grid/era5_nz_<start>_<end>_<vars>.nc
  Ref   : https://github.com/google-research/arco-era5

ARCO uses long CF names (``2m_temperature``) and ``latitude``/``longitude`` coords;
we rename to the pod-ml short names (``t2m``/``sp``/``d2m``/``tp`` on ``lat``/``lon``/
``time``) so that ARCO-specific naming is confined to this module.

Requires: xarray, zarr, gcsfs (in pyproject; installed in the VM venv).
"""

from __future__ import annotations

import xarray as xr

from podml.config import DATA_RAW

# Public ARCO-ERA5 Zarr store (Google Research, anonymous GCS access — verified).
ARCO_ERA5 = "gs://gcp-public-data-arco-era5/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
ERA5_GRID_CACHE = DATA_RAW / "era5_grid"

# ARCO long CF name -> pod-ml short name (matches labels.py / features.py).
_VAR_RENAME = {
    "surface_pressure": "sp",
    "2m_temperature": "t2m",
    "2m_dewpoint_temperature": "d2m",
    "total_precipitation": "tp",
}
_COORD_RENAME = {"latitude": "lat", "longitude": "lon"}
_SHORT_TO_LONG = {v: k for k, v in _VAR_RENAME.items()}

_DEFAULT_VARS = ["sp", "t2m", "d2m", "tp"]
_DEFAULT_DOMAIN = {"south": -47.0, "north": -34.0, "west": 166.0, "east": 178.0}


def _cache_path(start_year: int, end_year: int, variables: list[str]):
    tag = "-".join(sorted(variables))
    return ERA5_GRID_CACHE / f"era5_nz_{start_year}_{end_year}_{tag}.nc"


def _pull_from_arco(
    start_year: int, end_year: int, variables: list[str], domain: dict
) -> xr.Dataset:
    """Fetch the NZ slice straight from ARCO-ERA5 (slow; the bit we cache)."""
    long_vars = [_SHORT_TO_LONG[v] for v in variables]
    ds = xr.open_zarr(ARCO_ERA5, chunks=None, storage_options={"token": "anon"})
    subset = ds[long_vars].sel(
        # latitude descends (north first); longitude is 0..360 so 166..178 is direct.
        latitude=slice(domain["north"], domain["south"]),
        longitude=slice(domain["west"], domain["east"]),
        time=slice(f"{start_year}-01-01", f"{end_year}-12-31"),
    )
    return subset.rename({**_VAR_RENAME, **_COORD_RENAME})


def load_era5_nz(
    start_year: int = 2010,
    end_year: int = 2022,
    variables: list[str] | None = None,
    domain: dict | None = None,
    use_cache: bool = True,
) -> xr.Dataset:
    """Load ERA5 for the NZ domain (short-named vars), cached to local NetCDF.

    Args:
        start_year, end_year: year range (inclusive).
        variables: pod-ml short names (default: sp, t2m, d2m, tp).
        domain: NZ bounding box (default: 34-47 S, 166-178 E).
        use_cache: read/write the on-disk cache. Disabled automatically for a
            non-default domain (the cache key only encodes years + variables).

    Returns:
        xarray.Dataset on ``time``/``lat``/``lon``. Cache hits are lazy
        (``open_dataset``); a fresh ARCO pull is materialised before caching.
    """
    variables = variables or list(_DEFAULT_VARS)
    domain = domain or dict(_DEFAULT_DOMAIN)
    cacheable = use_cache and domain == _DEFAULT_DOMAIN

    if cacheable:
        path = _cache_path(start_year, end_year, variables)
        if path.exists():
            print(f"  ERA5 {start_year}-{end_year}: cache hit -> {path.name}")
            return xr.open_dataset(path)

    print(f"  ERA5 {start_year}-{end_year}: pulling from ARCO (vars={variables})...")
    ds = _pull_from_arco(start_year, end_year, variables, domain)

    if cacheable:
        ds = ds.load()  # materialise before writing
        ERA5_GRID_CACHE.mkdir(parents=True, exist_ok=True)
        path = _cache_path(start_year, end_year, variables)
        ds.to_netcdf(path)
        print(f"  cached -> {path.name} ({dict(ds.sizes)})")
    return ds


if __name__ == "__main__":
    print("=== ARCO-ERA5 NZ loader (smoke test: 2024, cached) ===\n")
    ds = load_era5_nz(start_year=2024, end_year=2024)
    print(ds)
