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
_COORD_RENAME = {"latitude": "lat", "longitude": "lon"}  # valid_time already matches convention
_DROP = ["number", "expver"]
# Generic/unknown transient errors: a few quick retries with growing backoff.
ERA5_MAX_ATTEMPTS = 8
ERA5_BACKOFF_SEC = 30  # grows linearly: 30s, 60s, 90s, ...
# CDS limits how many requests you may have QUEUED per dataset and rejects submissions over
# that cap with a 400 "the job has been rejected / queued requests temporarily limited". That
# is TRANSIENT — it clears as our other jobs drain — NOT a per-month problem. So we wait it
# out (long backoff, many attempts) rather than failing the month. (Learned the hard way: it
# was misread as "permanently rejected months" and a skip-list nearly cost us real data.)
RATE_LIMIT_HINTS = ("temporarily limited", "has been rejected", "queued requests")
RATE_LIMIT_MAX_ATTEMPTS = 40
RATE_LIMIT_BACKOFF_SEC = 120  # base per try; jittered below so workers don't retry in lockstep

# Full, untruncated failure records (CDS error body + traceback) land here, so a 400 is
# actually diagnosable; stdout/era5_pull.log keeps only a one-line summary. Gitignored.
FAILURE_LOG = ROOT / "era5_failures.log"


def _worker_id() -> str:
    """Short stable worker ID from the current thread name (e.g. '00','01','02','03')."""
    name = threading.current_thread().name
    if "ThreadPoolExecutor" in name:
        # "ThreadPoolExecutor-0_0" → "00"
        return name.rsplit("_", 1)[-1].zfill(2)
    return name.replace(" ", "")[:4]


def month_cache_path(year: int, month: int):
    return CACHE / f"era5land_nz_{year}-{month:02d}.nc"


def _client():
    # cdsapi reads $CDSAPI_RC, else ~/.cdsapirc; our key lives repo-local (gitignored).
    os.environ.setdefault("CDSAPI_RC", str(ROOT / ".cdsapirc"))
    import cdsapi

    return cdsapi.Client()


def _record_failure(year: int, month: int, exc: Exception) -> str:
    """Append the FULL failure (CDS response body + traceback) to era5_failures.log.

    Returns a one-line summary for stdout. The CDS reason for a 400 lives in the HTTP
    response *body*, not in str(exc), so we pull it out explicitly — without it a rejected
    month is undiagnosable (which is exactly how 2010-09/10/12 went unexplained).
    """
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


def download_month(year: int, month: int) -> str:
    """Fetch+normalise+cache one month. No-op (fast) if already cached."""
    wid = _worker_id()
    path = month_cache_path(year, month)
    if path.exists():
        return f"[W{wid}] [{year}-{month:02d}] cached"
    print(f"[W{wid}] [{year}-{month:02d}] started", flush=True)
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
    last_exc: Exception | None = None
    tries = rate_waits = 0
    while True:
        try:
            _client().retrieve("reanalysis-era5-land", request, str(raw))
            # Normalise to the project convention, write to a temp, then atomically publish.
            ds = xr.open_dataset(raw)
            ds = ds.rename({k: v for k, v in _COORD_RENAME.items() if k in ds.variables})
            ds = ds.drop_vars([c for c in _DROP if c in ds.variables], errors="ignore")
            ds.to_netcdf(wrt)
            ds.close()
            os.replace(wrt, path)  # atomic: the final .nc only ever appears complete
            raw.unlink(missing_ok=True)
            return f"[W{wid}] [{year}-{month:02d}] {time.time() - t0:.0f}s {path.stat().st_size / 1e6:.0f}MB"
        except Exception as exc:  # noqa: BLE001 — classify + retry below
            last_exc = exc
            raw.unlink(missing_ok=True)
            wrt.unlink(missing_ok=True)
            # CDS queue-limit rejection: transient, just be patient — never give up early.
            if _is_rate_limited(exc):
                rate_waits += 1
                if rate_waits > RATE_LIMIT_MAX_ATTEMPTS:
                    break
                # Jitter so 4 workers don't resubmit in lockstep and re-collide on the queue.
                delay = RATE_LIMIT_BACKOFF_SEC + random.randint(0, 60)
                print(f"[W{wid}] [{year}-{month:02d}] rate-limited retry {rate_waits}/{RATE_LIMIT_MAX_ATTEMPTS} (waiting {delay}s)", flush=True)
                time.sleep(delay)
                continue
            # Genuine/unknown error: a few growing-backoff retries, then fail — NOT skip. A
            # later watchdog run retries the month, so nothing is permanently abandoned.
            tries += 1
            if tries >= ERA5_MAX_ATTEMPTS:
                break
            time.sleep(ERA5_BACKOFF_SEC * tries)
    summary = _record_failure(year, month, last_exc) if last_exc else "unknown error"
    raise RuntimeError(f"failed after {tries} retries / {rate_waits} rate-limit waits — {summary}")


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
                print(f"[W??] [{y}-{m:02d}] FAILED: {e}  (full detail in era5_failures.log)", flush=True)

    if failures:
        print(f"Done with {failures} month(s) failed — rerun to retry.", flush=True)
        return 1
    print("All months cached.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
