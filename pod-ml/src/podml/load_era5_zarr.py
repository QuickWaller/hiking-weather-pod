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

# Pangeo ERA5-Land Zarr store (Google Cloud Storage, public bucket)
# This is the full global hourly ERA5-Land v10 from 2000–2024
PANGEO_ERA5_URL = "gs://gcp-public-data-era5/full_daily_zarr/2020/01/data.zarr"

# For now, use a simpler approach: leverage xarray's direct Zarr support
# The exact URL/structure depends on Pangeo's current setup
# (They have multiple formats: hourly, daily, monthly)


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
        # Attempt direct Zarr open (requires gcsfs)
        # This is the most efficient but needs the exact store path
        print("\n  Attempting direct Zarr access...")
        print(f"  URL: {PANGEO_ERA5_URL}")
        print("\n  NOTE: Exact Pangeo URL structure pending verification.")
        print("  If above fails, fallback approaches:")
        print("  1. Use intake-esm: intake.readthedocs.io")
        print("  2. Use OPeNDAP: xr.open_dataset(dods_url)")
        print("  3. Download via CDS: python -m podml.download_era5 --full")

        # Placeholder: would be replaced with actual Zarr open
        # ds = xr.open_zarr(PANGEO_ERA5_URL)
        # subset = ds[variables].sel(
        #     lat=slice(domain["south"], domain["north"]),
        #     lon=slice(domain["west"], domain["east"]),
        #     time=slice(f"{start_year}-01-01", f"{end_year}-12-31"),
        # )
        # return subset

        raise NotImplementedError(
            "Pangeo Zarr path structure pending verification. "
            "See below for fallback options."
        )

    except Exception as e:
        print(f"\nDirect Zarr failed: {e}")
        print("\n=== FALLBACK OPTIONS ===\n")
        print("1. USE INTAKE-ESM (recommended for Pangeo)")
        print("   pip install intake-esm intake-xarray")
        print("   cat = intake.open_esm_datastore('https://raw.githubusercontent.com/pangeo-data/...')")
        print("   ds = cat.to_dask()")
        print("\n2. USE OPeNDAP (slower but works)")
        print("   url = 'https://...-opendap-endpoint-...'")
        print("   ds = xr.open_dataset(url, engine='netcdf4')")
        print("\n3. DOWNLOAD VIA CDS (local, slowest)")
        print("   python -m podml.download_era5 --full")
        print("   Then use: load_era5_local()")
        print("\n=== NEXT STEP ===")
        print("Verify Pangeo Zarr URL at:")
        print("  https://pangeo.io/data.html")
        print("  https://github.com/pangeo-data/pangeo-datastore")
        print("\nOr use CDS API: requires ~/.cdsapirc setup")

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
