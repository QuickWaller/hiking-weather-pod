"""Download ERA5-Land (0.1°, fine, land-only) for the NZ box from CDS, per month.

CDS subsets server-side via ``area=``, so we download only NZ (~25 MB/month) at full
hourly resolution — the fine grid that resolves NZ's orographic rain (West Coast vs
Canterbury lee). Requests are batched: BATCH_SIZE months per CDS job (all same year),
downloaded as one NetCDF then split into per-month files on disk. Batching makes full
use of each queue slot instead of one month per slot.

Each month is normalised to the project convention (``valid_time`` / ``lat`` / ``lon`` ;
vars already ``sp,t2m,d2m,tp``) and cached to
``data/raw/era5_grid/era5land_nz_<year>-<month>.nc``. Idempotent: cached months within
a batch are skipped; uncached months in the same batch are still fetched together.

NZ box covers North/South/Stewart + Hauraki Gulf + Great Barrier (not Chatham).
Land-only: sea cells are NaN — fine for an on-land pod.

Exit code 0 only if every requested month succeeded (so a supervisor knows to retry;
cached months are skipped on retry). Months not yet published by CDS will fail and be
reported — rerun later to pick them up.

Usage:
    python -m podml.download_era5_grid                          # 2010-2024, 3 workers, 3-month batches
    python -m podml.download_era5_grid --start-year 2024 --end-year 2024 --workers 2
"""

from __future__ import annotations

import argparse
import os
import random
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import xarray as xr

from podml.config import DATA_RAW, ROOT

NZ_AREA = [-34.0, 166.0, -47.0, 178.0]  # N, W, S, E
VARIABLES = [
    "surface_pressure", "2m_temperature", "2m_dewpoint_temperature", "total_precipitation",
]
CACHE = DATA_RAW / "era5_grid"
BATCH_SIZE = 3          # months per CDS job (all same year); CDS allows up to a full year
                        # for the NZ box (~25 MB/month), but 3 keeps memory bounded at ~560 MB
                        # per worker and retries don't lose more than 3 months on failure.
_COORD_RENAME = {"latitude": "lat", "longitude": "lon"}
_DROP = ["number", "expver"]
ERA5_MAX_ATTEMPTS = 8
ERA5_BACKOFF_SEC = 30
RATE_LIMIT_HINTS = ("temporarily limited", "has been rejected", "queued requests", "rejected")
RATE_LIMIT_MAX_ATTEMPTS = 40
RATE_LIMIT_BACKOFF_SEC = 120
FAILURE_LOG = ROOT / "era5_failures.log"


def _worker_id() -> str:
    name = threading.current_thread().name
    if "ThreadPoolExecutor" in name:
        return name.rsplit("_", 1)[-1].zfill(2)
    return name.replace(" ", "")[:4]


def month_cache_path(year: int, month: int):
    return CACHE / f"era5land_nz_{year}-{month:02d}.nc"


def _client():
    os.environ.setdefault("CDSAPI_RC", str(ROOT / ".cdsapirc"))
    import cdsapi

    # Default retry_max=500 means a hung poll could loop for ~16 hours (500×120s sleep).
    # Cap at 5 retries / 30s timeout / 30s sleep → worst-case hang ~5 minutes per call.
    return cdsapi.Client(retry_max=5, timeout=30, sleep_max=30)


def _record_failure(year: int, month: int, exc: Exception) -> str:
    """Append the FULL failure (CDS response body + traceback) to era5_failures.log."""
    body = ""
    resp = getattr(exc, "response", None)
    if resp is not None:
        body = (getattr(resp, "text", "") or "").strip().replace("\n", " ")
    summary = f"{type(exc).__name__}: {exc}"
    if body:
        summary += f" | CDS: {body[:400]}"
    ts = datetime.now(timezone.utc).isoformat()
    try:
        with open(FAILURE_LOG, "a") as fh:
            fh.write(f"\n===== [{year}-{month:02d}] {ts} =====\n")
            fh.write(summary + "\n")
            fh.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    except OSError:
        pass
    return summary


def _is_rate_limited(exc: Exception) -> bool:
    """True if this is CDS's transient queue-limit rejection (not a real per-month failure)."""
    text = str(exc).lower()
    resp = getattr(exc, "response", None)
    if resp is not None:
        text += " " + (getattr(resp, "text", "") or "").lower()
    return any(hint in text for hint in RATE_LIMIT_HINTS)


def download_batch(batch: list[tuple[int, int]]) -> list[str]:
    """Fetch a batch of months (all same year) in one CDS request, split into per-month files.

    Cached months within the batch are skipped; only uncached months are requested.
    Returns a list of result strings (one per month in the batch).
    """
    wid = _worker_id()
    cached = [(y, m) for y, m in batch if month_cache_path(y, m).exists()]
    to_fetch = [(y, m) for y, m in batch if not month_cache_path(y, m).exists()]
    results = [f"[W{wid}] [{y}-{m:02d}] cached" for y, m in cached]

    if not to_fetch:
        return results

    year = to_fetch[0][0]
    months = sorted(m for _, m in to_fetch)
    tag = f"{year}-[{'+'.join(f'{m:02d}' for m in months)}]"
    print(f"[W{wid}] {tag} started ({len(to_fetch)} months)", flush=True)
    CACHE.mkdir(parents=True, exist_ok=True)

    slug = f"{year}_m{'_'.join(f'{m:02d}' for m in months)}"
    raw = CACHE / f"era5land_nz_{slug}.cdsdownload"

    request = {
        "variable": VARIABLES,
        "year": str(year),
        "month": [f"{m:02d}" for m in months],
        "day": [f"{d:02d}" for d in range(1, 32)],
        "time": [f"{h:02d}:00" for h in range(24)],
        "data_format": "netcdf",
        "download_format": "unarchived",
        "area": NZ_AREA,
    }

    t0 = time.time()
    last_exc: Exception | None = None
    tries = rate_waits = 0
    while True:
        try:
            print(f"[W{wid}] {tag} submitting (attempt {rate_waits + tries + 1})", flush=True)
            _client().retrieve("reanalysis-era5-land", request, str(raw))
            ds = xr.open_dataset(raw)
            ds = ds.rename({k: v for k, v in _COORD_RENAME.items() if k in ds.variables})
            ds = ds.drop_vars([c for c in _DROP if c in ds.variables], errors="ignore")
            # Split lazily — reads from raw once per month, keeps peak RAM to one month at a time.
            for yr, mo in to_fetch:
                path = month_cache_path(yr, mo)
                mask = (ds.valid_time.dt.year == yr) & (ds.valid_time.dt.month == mo)
                month_ds = ds.isel(valid_time=mask.values)
                part = path.with_suffix(".nc.part")
                month_ds.to_netcdf(part)
                part.replace(path)
                msg = f"[W{wid}] [{yr}-{mo:02d}] {time.time() - t0:.0f}s {path.stat().st_size / 1e6:.0f}MB"
                results.append(msg)
                print(msg, flush=True)
            ds.close()
            raw.unlink(missing_ok=True)
            return results
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            raw.unlink(missing_ok=True)
            if _is_rate_limited(exc):
                rate_waits += 1
                if rate_waits > RATE_LIMIT_MAX_ATTEMPTS:
                    break
                delay = RATE_LIMIT_BACKOFF_SEC + random.randint(0, 60)
                print(f"[W{wid}] {tag} rate-limited retry {rate_waits}/{RATE_LIMIT_MAX_ATTEMPTS} "
                      f"(waiting {delay}s)", flush=True)
                time.sleep(delay)
                continue
            tries += 1
            print(f"[W{wid}] {tag} error {tries}/{ERA5_MAX_ATTEMPTS}: {exc}", flush=True)
            if tries >= ERA5_MAX_ATTEMPTS:
                break
            time.sleep(ERA5_BACKOFF_SEC * tries)

    summary = _record_failure(year, months[0], last_exc) if last_exc else "unknown error"
    raise RuntimeError(
        f"batch {tag} failed after {tries} retries / {rate_waits} rate-limit waits — {summary}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Download NZ ERA5-Land months from CDS")
    ap.add_argument("--start-year", type=int, default=2010)
    ap.add_argument("--end-year", type=int, default=2024)
    ap.add_argument("--workers", type=int, default=3,
                    help="parallel CDS requests (CDS allows ~2 concurrent; 3 workers keeps "
                         "slots full as one completes)")
    ap.add_argument("--batch-size", type=int, default=BATCH_SIZE,
                    help="months per CDS request (same year only)")
    args = ap.parse_args()

    # Build year-aligned batches newest-first so recent test-year data lands soonest.
    batches: list[list[tuple[int, int]]] = []
    for year in range(args.end_year, args.start_year - 1, -1):
        months = list(range(12, 0, -1))
        for i in range(0, 12, args.batch_size):
            batches.append([(year, m) for m in months[i: i + args.batch_size]])

    n_months = sum(len(b) for b in batches)
    print(f"ERA5-Land CDS: {n_months} months in {len(batches)} batches "
          f"({args.batch_size}/batch), {args.workers} parallel workers", flush=True)

    failures = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(download_batch, b): b for b in batches}
        for fut in as_completed(futures):
            b = futures[fut]
            tag = f"{b[0][0]}-[{'+'.join(f'{m:02d}' for _, m in b)}]"
            try:
                for msg in fut.result():
                    if "cached" not in msg:
                        print(msg, flush=True)
            except Exception as e:
                failures += 1
                print(f"[W??] {tag} FAILED: {e}  (full detail in era5_failures.log)", flush=True)

    if failures:
        print(f"Done with {failures} batch(es) failed — rerun to retry.", flush=True)
        return 1
    print("All months cached.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
