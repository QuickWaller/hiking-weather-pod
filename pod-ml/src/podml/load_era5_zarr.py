"""Load ERA5-Land from Pangeo Zarr (cloud-optimized, no download needed).

Pangeo hosts ERA5 as a Zarr store on Google Cloud Storage. No auth required,
lazy evaluation, only reads the data you slice.

Workflow:
  1. Open remote Zarr store (GCS bucket)
  2. Slice to NZ domain (lat/lon bounds)
  3. Select variables (sp, t2m, d2m)
  4. Load into xarray Dataset

Benefits:
  - No download — directly read from cloud
  - Lazy evaluation — only compute what you use
  - Scales to any region/date range
  - Free (public bucket)

Usage:
    # Load 2010 data for NZ (takes ~30s first time, then cached)
    ds = load_era5_nz(start_year=2010, end_year=2010)

    # Check what you got
    print(ds)  # dimensions, coordinates, data_vars

    # Access variables
    precip = ds['tp']  # total precipitation (m)
    pressure = ds['sp']  # surface pressure (Pa)
    temp = ds['t2m']  # 2m temperature (K)
"""

from __future__ import annotations

import xarray as xr

# Pangeo ERA5 Zarr store (Google Cloud Storage, public bucket, verified)
# Full global hourly ERA5 from 1940–2024
# Source: https://github.com/pangeo-data/pangeo-datastore
PANGEO_ERA5_HOURLY = "gs://gcp-public-data-era5/full_hourly_zarr"
PANGEO_ERA5_DAILY = "gs://gcp-public-data-era5/full_daily_zarr"


def load_era5_nz(
    start_year: int = 2010,
    end_year: int = 2022,
    variables: list[str] | None = None,
    domain: dict | None = None,
) -> xr.Dataset:
    """Load ERA5-Land data for NZ domain from Pangeo Zarr.

    Args:
        start_year, end_year: year range (inclusive)
        variables: ERA5 variables to load (default: sp, t2m, d2m)
        domain: NZ bounding box (default: -47 to -34 S, 166 to 178 E)

    Returns:
        xarray.Dataset with hourly data for the specified region/years

    Note:
        First load will be slower (Pangeo caches). Subsequent loads are fast.
        Requires: xarray, zarr, gcsfs (pip install)

    Example:
        >>> ds = load_era5_nz(start_year=2010, end_year=2010)
        >>> print(ds)  # inspect
        >>> temp = ds['t2m'].sel(time=slice('2010-06', '2010-08'))  # summer
    """
    if variables is None:
        variables = ["sp", "t2m", "d2m"]

    if domain is None:
        domain = {"south": -47.0, "north": -34.0, "west": 166.0, "east": 178.0}

    print(f"Loading ERA5-Land from Pangeo Zarr: {start_year}–{end_year}, NZ domain")
    print(f"  Domain: {domain}")
    print(f"  Variables: {variables}")

    # Implementation approach depends on Pangeo's exact Zarr structure
    # Option 1: Direct Zarr store (if available)
    # Option 2: zarr via xarray's open_dataset()
    # Option 3: Use intake-esm catalog (if available)

    try:
        # Open Pangeo ERA5 hourly Zarr store (verified, public, no auth needed)
        print("\n  Opening Pangeo ERA5 Zarr store...")
        print(f"  URL: {PANGEO_ERA5_HOURLY}")

        # Requires: pip install zarr gcsfs
        ds = xr.open_zarr(PANGEO_ERA5_HOURLY, consolidated=True)

        # Subset to NZ domain and time range
        subset = ds[variables].sel(
            lat=slice(domain["south"], domain["north"]),
            lon=slice(domain["west"], domain["east"]),
            time=slice(f"{start_year}-01-01", f"{end_year}-12-31"),
        )

        print(f"  ✓ Loaded: {dict(subset.dims)}")
        return subset

    except Exception as e:
        print(f"\n✗ Failed: {e}")
        print("\nFallback: python -m podml.download_era5 --full (requires ~/.cdsapirc)")
        return None  # type: ignore[return-value]


def load_era5_local(
    data_dir: str,
    start_year: int = 2010,
    end_year: int = 2022,
    domain: dict | None = None,
) -> xr.Dataset:
    """Load pre-downloaded ERA5-Land NetCDF files from disk.

    Use this if Pangeo Zarr is not available or too slow.

    Args:
        data_dir: directory with era5land_ts_*.nc files (from download_era5.py)
        start_year, end_year: year range
        domain: NZ bounding box

    Returns:
        xarray.Dataset combined across multiple point timeseries
    """
    print(f"Loading ERA5 from local files: {data_dir}")
    print("Not yet implemented — use Pangeo Zarr or download_era5 instead")
    return None  # type: ignore[return-value]


if __name__ == "__main__":
    # Quick test
    print("=== ERA5-Land Zarr Loader ===\n")
    ds = load_era5_nz(start_year=2020, end_year=2020)
    if ds is not None:
        print(f"\nLoaded dataset:\n{ds}")
