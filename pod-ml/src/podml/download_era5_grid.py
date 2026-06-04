"""Download the NZ ERA5 grid slice we need for grid training — one year per file.

Pulls from ARCO-ERA5 via ``load_era5_nz`` (which caches each year to
``data/raw/era5_grid/era5_nz_<y>_<y>_<vars>.nc``). ARCO is chunked one timestep
per chunk, so a year is many small reads and takes a while — but it is a one-time
cost. Idempotent: already-cached years are skipped, so the job is safe to restart
(that is how the watchdog and the future weekly top-up cron reuse it).

Exit code 0 only if every requested year succeeded; non-zero if any year failed,
so a supervisor knows to retry (cached years are skipped on retry).

Usage:
    python -m podml.download_era5_grid                       # 2010-2024
    python -m podml.download_era5_grid --start-year 2024 --end-year 2024
"""

from __future__ import annotations

import argparse
import time

from podml.load_era5_zarr import load_era5_nz


def download_years(start_year: int, end_year: int) -> int:
    """Pull+cache each year in [start_year, end_year]. Returns the failure count."""
    failures = 0
    for y in range(start_year, end_year + 1):
        t0 = time.time()
        try:
            ds = load_era5_nz(start_year=y, end_year=y)  # cache hit -> fast; else pulls
            ds.close()
            print(f"[{y}] ok in {time.time() - t0:.0f}s", flush=True)
        except Exception as e:  # one bad year must not abort the rest
            failures += 1
            print(f"[{y}] FAILED: {type(e).__name__}: {e}", flush=True)
    return failures


def main() -> int:
    ap = argparse.ArgumentParser(description="Download NZ ERA5 grid years to local cache")
    ap.add_argument("--start-year", type=int, default=2010)
    ap.add_argument("--end-year", type=int, default=2024)
    args = ap.parse_args()

    print(f"ERA5 grid download: {args.start_year}-{args.end_year}", flush=True)
    failures = download_years(args.start_year, args.end_year)
    if failures:
        print(f"Done with {failures} year(s) failed — rerun to retry.", flush=True)
        return 1
    print("All years cached.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
