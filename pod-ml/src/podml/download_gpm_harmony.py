"""Step 4 — GPM IMERG 30-min rain over the NZ grid, via NASA Harmony, stored monthly.

Stores the FULL NZ box (not just the probe points), so we download ONCE and serve both the point-probe
AND the eventual gridded model. One compressed NetCDF per month = a checkpoint: re-running skips finished
months (resumable across crashes/disconnects). After downloading, extracts the probe-point pixels to a CSV.

  data/raw/gpm_grid/gpm_YYYY-MM.nc   full NZ-box precip (+ liquid-precip fraction for snow), time x lon x lat
  data/raw/gpm_grid/points.csv       30-min precip (mm/hr) at the 5 probe points, derived from the grids

Long job — run on the VM in tmux:
    python -m podml.download_gpm_harmony --start 2022-01 --end 2024-12
    python -m podml.download_gpm_harmony --start 2022-01 --end 2024-12 --points-only  # re-extract points
"""

from __future__ import annotations

import argparse
import atexit
import os
import shutil
import time
from pathlib import Path

import pandas as pd
import xarray as xr

from podml.config import DATA_RAW, load_config

GRID_DIR = DATA_RAW / "gpm_grid"
KEEP_VARS = ["precipitation", "probabilityLiquidPrecipitation"]  # rain + (frozen/liquid) for snow


def month_range(start: str, end: str):
    """Yield (year, month) inclusive from 'YYYY-MM' start to end."""
    p, last = pd.Period(start, freq="M"), pd.Period(end, freq="M")
    while p <= last:
        yield p.year, p.month
        p += 1


def _grid_path(year: int, month: int) -> Path:
    return GRID_DIR / f"gpm_{year}-{month:02d}.nc"


def _open_grid(path: Path):
    """HHR data sits under group 'Grid'; daily at root. Return whichever has precipitation."""
    for grp in ("Grid", None):
        try:
            ds = xr.open_dataset(path, group=grp) if grp else xr.open_dataset(path)
        except Exception:  # noqa: BLE001
            continue
        if "precipitation" in ds.data_vars:
            return ds
        ds.close()
    return None


def _to_timestamp(tval) -> pd.Timestamp:
    """cftime (Julian calendar) or numpy datetime64 → pandas Timestamp."""
    if hasattr(tval, "year"):
        return pd.Timestamp(tval.year, tval.month, tval.day,
                            getattr(tval, "hour", 0), getattr(tval, "minute", 0))
    return pd.Timestamp(tval)


def _run_job(client, req):
    """Submit and resume through Harmony's preview-pause until the job is terminal."""
    job = client.submit(req)
    terminal = {"successful", "failed", "canceled", "complete_with_errors"}
    while True:
        status = client.status(job).get("status", "")
        if status == "paused":
            client.resume(job)
        elif status in terminal:
            return job
        time.sleep(2)


def stack_month(files) -> "xr.Dataset | None":
    """Stack a month's granules into one (time, lon, lat) Dataset over the NZ box."""
    dsets = []
    for f in files:
        ds = _open_grid(Path(f))
        if ds is None:
            continue
        keep = [v for v in KEEP_VARS if v in ds.data_vars]
        sub = ds[keep].load().assign_coords(time=[_to_timestamp(ds["time"].values.ravel()[0])])
        dsets.append(sub)
        ds.close()
    if not dsets:
        return None
    return xr.concat(dsets, dim="time").sortby("time")


def _acquire_lock() -> None:
    """Refuse to start if another GPM pull is alive — two processes sharing temp dirs corrupt months."""
    GRID_DIR.mkdir(parents=True, exist_ok=True)
    lock = GRID_DIR / ".pull.lock"
    if lock.exists():
        try:
            old = int(lock.read_text().strip() or "0")
            os.kill(old, 0)  # no exception ⇒ that pid is alive
        except (ValueError, ProcessLookupError):
            pass  # stale/unparsable lock → take over
        else:
            raise SystemExit(f"Another GPM pull (pid {old}) is already running; refusing to start a second.")
    lock.write_text(str(os.getpid()))
    atexit.register(lambda: lock.unlink(missing_ok=True))


def build_grid(start: str, end: str, client, collection, bbox) -> None:
    """Download + store one NetCDF per month (skips months already on disk)."""
    from harmony import Request

    GRID_DIR.mkdir(parents=True, exist_ok=True)
    # Newest month first, so recent years (what the probe needs) land soonest; old years backfill.
    for yr, mo in reversed(list(month_range(start, end))):
        out = _grid_path(yr, mo)
        if out.exists():
            print(f"[{yr}-{mo:02d}] already stored, skipping", flush=True)
            continue
        # PER-MONTH private temp dir: a stale/parallel run can never delete this month's granules mid-stack.
        tmp = GRID_DIR / f"_tmp_{yr}{mo:02d}"
        shutil.rmtree(tmp, ignore_errors=True)
        s = pd.Timestamp(yr, mo, 1)
        e = (s + pd.offsets.MonthEnd(1)).replace(hour=23, minute=59)
        print(f"[{yr}-{mo:02d}] Harmony request...", flush=True)
        try:
            req = Request(collection=collection, spatial=bbox,
                          temporal={"start": s.to_pydatetime(), "stop": e.to_pydatetime()})
            job = _run_job(client, req)
            tmp.mkdir(parents=True)
            files = [f.result() for f in client.download_all(job, directory=str(tmp), overwrite=True)]
            month = stack_month(files)
            if month is None:
                print(f"[{yr}-{mo:02d}] no usable granules — skipping", flush=True)
                continue
            steps, ngran = month.sizes["time"], len(files)
            if steps < 0.95 * ngran:
                # Integrity guard: each granule is one 30-min step, so steps should ≈ granules. A big
                # shortfall means granules went missing (stale parallel run / partial downloads) → do NOT
                # bank a holey month; leave it absent so a later run retries it cleanly.
                print(f"[{yr}-{mo:02d}] INCOMPLETE {steps}/{ngran} steps — NOT banking, will retry",
                      flush=True)
                continue
            # Write atomically (temp + rename) so an interrupted write never leaves a half file that
            # looks complete to the `out.exists()` skip.
            part = out.with_suffix(".nc.part")
            month.to_netcdf(part, encoding={v: {"zlib": True, "complevel": 4} for v in month.data_vars})
            part.replace(out)
            print(f"[{yr}-{mo:02d}] {ngran} granules -> {steps} steps -> {out.name}", flush=True)
        except Exception as exc:  # noqa: BLE001
            # No data (recent months past Final latency, or pre-2000) or a transient error → skip and
            # keep going; since no file is written, a later re-run retries the month.
            print(f"[{yr}-{mo:02d}] SKIPPED: {str(exc)[:90]}", flush=True)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def extract_points(start: str, end: str, points: dict) -> pd.DataFrame:
    """Read the monthly grids and pull the probe-point precip pixels → time x points DataFrame."""
    frames = []
    for yr, mo in month_range(start, end):
        gp = _grid_path(yr, mo)
        if not gp.exists():
            continue
        ds = xr.open_dataset(gp)
        cols = {name: ds["precipitation"].sel(lon=p["lon"], lat=p["lat"], method="nearest").values.ravel()
                for name, p in points.items()}
        frames.append(pd.DataFrame(cols, index=pd.to_datetime(ds["time"].values)))
        ds.close()
    return pd.concat(frames).sort_index() if frames else pd.DataFrame()


def main() -> None:
    ap = argparse.ArgumentParser(description="GPM HHR NZ grid via Harmony: store monthly + extract points.")
    ap.add_argument("--start", required=True, help="start month, YYYY-MM")
    ap.add_argument("--end", required=True, help="end month, YYYY-MM")
    ap.add_argument("--workers", type=int, default=16, help="parallel download threads")
    ap.add_argument("--points-only", action="store_true",
                    help="skip downloading; just (re)extract the point CSV from existing monthly grids")
    args = ap.parse_args()

    os.environ["NUM_REQUESTS_WORKERS"] = str(args.workers)  # set before harmony import
    cfg = load_config()
    dom, gpm, points = cfg["domain"], cfg["gpm_imerg"], cfg["probe_points"]

    if not args.points_only:
        _acquire_lock()  # one pull at a time — concurrent runs corrupt months
        from harmony import BBox, Client, Collection
        build_grid(args.start, args.end, Client(), Collection(id=gpm["harmony_collection_hhr"]),
                   BBox(dom["west"], dom["south"], dom["east"], dom["north"]))

    pts = extract_points(args.start, args.end, points)
    GRID_DIR.mkdir(parents=True, exist_ok=True)
    out_csv = GRID_DIR / "points.csv"
    pts.to_csv(out_csv)
    print(f"\nExtracted {len(pts)} timesteps x {len(points)} points -> {out_csv}")


if __name__ == "__main__":
    main()
