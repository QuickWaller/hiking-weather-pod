"""Download ERA5-Land (0.1°, fine, land-only) for the NZ box from CDS, per month.

CDS subsets server-side via ``area=``, so we download only NZ (~25 MB/month) at full
hourly resolution — the fine grid that resolves NZ's orographic rain (West Coast vs
Canterbury lee). Requests are PER MONTH: a full-year ERA5-Land request exceeds CDS's
per-request cost limit. Months are independent, so we parallelise across them to beat
CDS's slow single-stream download.

Each month is normalised to the project convention (``valid_time`` / ``lat`` / ``lon`` ;
vars already ``sp,t2m,d2m,tp``) and cached to
``data/raw/era5_grid/era5land_nz_<year>-<month>.nc``. Idempotent: cached months are
skipped, so it's safe to restart / resume / run alongside the watchdog.

NZ box covers North/South/Stewart + Hauraki Gulf + Great Barrier (not Chatham).
Land-only: sea cells are NaN — fine for an on-land pod.

Exit code 0 only if every requested month succeeded (so a supervisor knows to retry;
cached months are skipped on retry). Months not yet published by CDS will fail and be
reported — rerun later to pick them up.

Usage:
    python -m podml.download_era5_grid                          # 2010-2024, 4 parallel
    python -m podml.download_era5_grid --start-year 2024 --end-year 2024 --workers 6
"""

from __future__ import annotations

import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import xarray as xr

from podml.config import DATA_RAW, ROOT

NZ_AREA = [-34.0, 166.0, -47.0, 178.0]  # N, W, S, E
VARIABLES = [
    "surface_pressure", "2m_temperature", "2m_dewpoint_temperature", "total_precipitation",
]
CACHE = DATA_RAW / "era5_grid"
_COORD_RENAME = {"latitude": "lat", "longitude": "lon"}  # valid_time already matches convention
_DROP = ["number", "expver"]


def month_cache_path(year: int, month: int):
    return CACHE / f"era5land_nz_{year}-{month:02d}.nc"


def _client():
    # cdsapi reads $CDSAPI_RC, else ~/.cdsapirc; our key lives repo-local (gitignored).
    os.environ.setdefault("CDSAPI_RC", str(ROOT / ".cdsapirc"))
    import cdsapi

    return cdsapi.Client()


def download_month(year: int, month: int) -> str:
    """Fetch+normalise+cache one month. No-op (fast) if already cached."""
    path = month_cache_path(year, month)
    if path.exists():
        return f"[{year}-{month:02d}] cached"
    CACHE.mkdir(parents=True, exist_ok=True)
    # Temp files must NOT end in .nc, or the cache glob in era5_load would match a
    # half-written file. Write the final atomically via os.replace.
    raw = path.with_name(path.name + ".cdsdownload")  # CDS retrieve target
    wrt = path.with_name(path.name + ".writing")       # normalised, pre-rename
    request = {
        "variable": VARIABLES,
        "year": str(year),
        "month": f"{month:02d}",
        "day": [f"{d:02d}" for d in range(1, 32)],
        "time": [f"{h:02d}:00" for h in range(24)],
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": NZ_AREA,
    }
    t0 = time.time()
    _client().retrieve("reanalysis-era5-land", request, str(raw))
    # Normalise to the project convention, write to a temp, then atomically publish.
    ds = xr.open_dataset(raw)
    ds = ds.rename({k: v for k, v in _COORD_RENAME.items() if k in ds.variables})
    ds = ds.drop_vars([c for c in _DROP if c in ds.variables], errors="ignore")
    ds.to_netcdf(wrt)
    ds.close()
    os.replace(wrt, path)  # atomic: the final .nc only ever appears complete
    raw.unlink(missing_ok=True)
    return f"[{year}-{month:02d}] {time.time() - t0:.0f}s {path.stat().st_size / 1e6:.0f}MB"


def main() -> int:
    ap = argparse.ArgumentParser(description="Download NZ ERA5-Land months from CDS")
    ap.add_argument("--start-year", type=int, default=2010)
    ap.add_argument("--end-year", type=int, default=2024)
    ap.add_argument("--workers", type=int, default=4, help="parallel CDS requests")
    args = ap.parse_args()

    months = [(y, m) for y in range(args.start_year, args.end_year + 1) for m in range(1, 13)]
    print(f"ERA5-Land CDS: {len(months)} months, {args.workers} parallel", flush=True)

    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(download_month, y, m): (y, m) for y, m in months}
        for fut in as_completed(futures):
            y, m = futures[fut]
            try:
                print(fut.result(), flush=True)
            except Exception as e:  # one bad/unpublished month must not abort the rest
                failures += 1
                print(f"[{y}-{m:02d}] FAILED: {type(e).__name__}: {str(e)[:160]}", flush=True)

    if failures:
        print(f"Done with {failures} month(s) failed — rerun to retry.", flush=True)
        return 1
    print("All months cached.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
