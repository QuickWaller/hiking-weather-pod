"""Download ERA5-Land full grid for NZ (gridded, not point timeseries).

This gets the complete spatial field (not individual points) so we can train
on all grid cells simultaneously. Dramatically increases training data.

ERA5-Land has ~0.1° resolution (~10 km). NZ is ~10° × 8° = ~100×80 grid cells.
Each monthly file is ~50–100 MB.

Options:
  1. **CDS API** (Copernicus): Requires cdsapirc auth, interactive.
  2. **Google Cloud Storage** (gs://gcp-public-data-era5): No auth, scriptable.
  3. **Pangeo Zarr** (zarr files): Fast, cloud-optimized, no download needed.

Recommendation: **Use Google Cloud (no auth) or Pangeo (no download)** for speed.
CDS is slow and interactive; only use if you need custom subsets.

Usage:
    # Option A: Download from Google Cloud Storage (no auth, fast)
    python -m podml.download_era5_grid --source gcs --start 2010-01 --end 2022-12

    # Option B: Load from Pangeo Zarr (no download, direct read)
    python -m podml.download_era5_grid --source zarr --start 2010 --end 2022

    # Option C: CDS API (requires ~/.cdsapirc auth)
    python -m podml.download_era5_grid --source cds --month 2010-01
"""

from __future__ import annotations

import argparse
from pathlib import Path

from podml.config import DATA_RAW


def download_gcs_era5(
    start_year: int,
    end_year: int,
    variables: list[str] | None = None,
    out_dir: Path | None = None,
) -> None:
    """Download ERA5-Land from Google Cloud Storage (no auth required).

    Args:
        start_year, end_year: year range
        variables: ERA5 variables (default: sp, t2m, d2m for pressure/temp/humidity)
        out_dir: output directory
    """
    if variables is None:
        variables = ["surface_pressure", "temperature_2m", "dewpoint_2m"]

    if out_dir is None:
        out_dir = DATA_RAW / "era5_grid"

    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"ERA5-Land GCS download: {start_year}–{end_year}, {variables}")
    print(f"Output: {out_dir}")
    print(
        """
    Implementation needed:
      1. Use gsutil or google-cloud-storage Python library
      2. List objects in gs://gcp-public-data-era5/
      3. Download monthly NetCDF files for NZ domain

    For now, recommend direct read via Pangeo Zarr (see load_era5_zarr).
    """
    )


def load_era5_zarr(
    start_year: int,
    end_year: int,
    region: dict | None = None,
) -> None:
    """Load ERA5-Land from Pangeo Zarr (cloud-optimized, no download).

    Args:
        start_year, end_year: year range
        region: dict with keys lat_min, lat_max, lon_min, lon_max (default: NZ bounds)

    Usage:
        import xarray as xr
        import zarr

        # Open remote Zarr store (no download)
        store = 'gs://gcp-public-data-era5/...'  # exact path TBD
        ds = xr.open_zarr(store)

        # Slice to NZ region
        nz = ds.sel(lat=slice(-47, -34), lon=slice(166, 178))
    """
    if region is None:
        region = {"lat_min": -47, "lat_max": -34, "lon_min": 166, "lon_max": 178}

    print(f"ERA5-Land Pangeo Zarr: {start_year}–{end_year}, NZ region {region}")
    print(
        """
    Implementation:
      1. Find Pangeo Zarr store URL (era5-land full global grid)
      2. Open with xr.open_zarr() — no download
      3. Slice to NZ domain: sel(lat=slice(-47,-34), lon=slice(166,178))
      4. Select variables: ['sp', 't2m', 'd2m']
      5. Resample to daily if needed (Zarr may be hourly)

    Benefits:
      - No download, direct cloud read
      - Lazy evaluation (only compute what you use)
      - Scales to any region/time
    """
    )


def download_cds_era5(month: str, out_path: Path | None = None) -> None:
    """Download single month from CDS API (requires ~/.cdsapirc).

    Args:
        month: 'YYYY-MM' (e.g., '2010-01')
        out_path: output file

    Note:
        CDS is interactive and slower than GCS/Zarr.
        Use only for custom subsets or when cloud options unavailable.
    """
    print(f"CDS ERA5-Land download: {month}")
    print(
        """
    Implementation (requires cdsapi + auth):
      import cdsapi
      client = cdsapi.Client()

      request = {
          'product_type': 'reanalysis',
          'variable': ['surface_pressure', 'temperature_2m', 'dewpoint_2m'],
          'month': '01',
          'year': '2010',
          'day': range(1, 32),
          'time': [f'{h:02d}:00' for h in range(24)],
          'grid': [0.1, 0.1],  # 0.1° resolution
          'area': [-34, 166, -47, 178],  # NZ: N, W, S, E
      }

      client.retrieve('reanalysis-era5-land', request).download(out_path)
    """
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Download ERA5-Land gridded data")
    ap.add_argument(
        "--source",
        choices=["gcs", "zarr", "cds"],
        default="zarr",
        help="Data source (default: zarr — no download needed)",
    )
    ap.add_argument("--start", type=str, help="Start year/month (YYYY or YYYY-MM)")
    ap.add_argument("--end", type=str, help="End year/month (YYYY or YYYY-MM)")
    ap.add_argument("--out-dir", type=Path, help="Output directory")
    args = ap.parse_args()

    if args.source == "gcs":
        start_year = int(args.start.split("-")[0]) if args.start else 2010
        end_year = int(args.end.split("-")[0]) if args.end else 2022
        download_gcs_era5(start_year, end_year, out_dir=args.out_dir)
    elif args.source == "zarr":
        start_year = int(args.start.split("-")[0]) if args.start else 2010
        end_year = int(args.end.split("-")[0]) if args.end else 2022
        load_era5_zarr(start_year, end_year)
    elif args.source == "cds":
        month = args.start or "2010-01"
        load_era5_zarr(int(args.start.split("-")[0]), int(args.start.split("-")[0]))
