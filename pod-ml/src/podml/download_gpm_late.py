"""Recent-data GPM rain checks (fine labels) via IMERG **Late Run**, over NASA Harmony.

Companion to `download_gpm_harmony.py` (which pulls the Final-Run *archive* for training). This one
answers ad-hoc "what did it actually rain at this GPS point and time?" questions on RECENT data
(last week / last month) — the post-sync ground-truth check for the fine model + combined weights
against pod-logged hikes.

Why Late Run: the Final Run lags ~3.5 months, so it can never cover a hike you did last week. The Late
Run lags ~14h and otherwise is the same satellite-observation product (same V07 grid, same fields). It is
NOT gauge-corrected (Final is) — a minor extra raw-satellite bias, fine for labels, and crucially it keeps
these labels in the SAME observation family as the coarse model's GPM labels (vs ERA5/Open-Meteo, which is a
reanalysis *model* product → circular, and less truthful than the GPM we already train on).

Semantics: returns the rain intensity (mm/hr) for the half-hour granule that CONTAINS the query time —
i.e. "was it raining where/when the pod was", not the forward-looking forecast label that the archive feeds.

All times are UTC (the pod logs GPS UTC). Inputs:
  --queries checks.csv          batch: CSV with columns time,lat,lon[,name]   (the pod-driven path)
  --lat L --lon L --time T      one point at one UTC time
  --lat L --lon L --start T --end T   one point, every half-hour in [start, end]
  --bbox W,S,E,N --start T --end T    store the gridded cutout (NetCDF) — boxes, not point extraction

Outputs (kept SEPARATE from the training archive in data/raw/gpm_grid/):
  data/raw/gpm_fine/fine_labels.csv          appended point results
  data/raw/gpm_fine/grids/late_<UTC>.nc      cutout grids (--bbox mode)

Run on the VM:
    python -m podml.download_gpm_late --queries hike_2026-06-11.csv
    python -m podml.download_gpm_late --lat -36.66 --lon 174.73 --time 2026-06-11T21:00 --name long_bay
"""

from __future__ import annotations

import argparse
import os
import shutil
import time
from pathlib import Path

import pandas as pd

from podml.config import DATA_RAW, load_config
from podml.download_gpm_harmony import _open_grid, _run_job  # reuse the proven Harmony plumbing

FINE_DIR = DATA_RAW / "gpm_fine"
GRID_SUBDIR = FINE_DIR / "grids"
POINT_CSV = FINE_DIR / "fine_labels.csv"
# precip + (frozen/liquid split for snow) + per-cell quality flag — all present in the Harmony subset.
KEEP_VARS = ["precipitation", "probabilityLiquidPrecipitation", "precipitationQualityIndex"]
POINT_MARGIN_DEG = 0.15  # ≥ half the 0.1° pixel → the nearest-neighbour cell is always inside the cutout
GPM_MAX_ATTEMPTS = 4
GPM_BACKOFF_SEC = 30  # linear backoff: 30s, 60s, 90s — Harmony 5xx/timeouts are transient


def granule_start(t) -> pd.Timestamp:
    """The period-BEGINNING half-hour [start, start+30min) that contains UTC time `t`.

    IMERG granules are stamped period-beginning, so flooring the query time to the half-hour
    gives the granule that observed it. tz-aware inputs are converted to UTC first.
    """
    ts = pd.Timestamp(t)
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts.floor("30min")


def load_queries(path: Path) -> pd.DataFrame:
    """Read a checks CSV (columns time,lat,lon[,name]) → normalised time/lat/lon/name frame (UTC, naive)."""
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    missing = {"time", "lat", "lon"} - set(cols)
    if missing:
        raise ValueError(f"queries CSV needs columns time,lat,lon — missing {sorted(missing)} (got {list(df.columns)})")
    out = pd.DataFrame({
        "time": pd.to_datetime(df[cols["time"]], utc=True).dt.tz_localize(None),
        "lat": df[cols["lat"]].astype(float),
        "lon": df[cols["lon"]].astype(float),
    })
    out["name"] = df[cols["name"]].astype(str) if "name" in cols else [f"q{i}" for i in range(len(df))]
    return out


def _download_granule(client, collection, bbox, gstart: pd.Timestamp):
    """Pull + open the single Late granule for the half-hour `gstart`, subset to `bbox`. None if unavailable."""
    start = gstart.to_pydatetime()
    stop = (gstart + pd.Timedelta(minutes=29, seconds=59)).to_pydatetime()
    tmp = GRID_SUBDIR / f"_tmp_{gstart:%Y%m%dT%H%M}"
    for attempt in range(1, GPM_MAX_ATTEMPTS + 1):
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            from harmony import Request

            req = Request(collection=collection, spatial=bbox,
                          temporal={"start": start, "stop": stop})
            job = _run_job(client, req)
            tmp.mkdir(parents=True)
            files = [f.result() for f in client.download_all(job, directory=str(tmp), overwrite=True)]
            for f in files:
                ds = _open_grid(Path(f))
                if ds is not None:
                    data = ds.load()  # pull into memory so the temp file can be deleted
                    ds.close()
                    return data
            return None  # job ran but no granule intersected
        except Exception as exc:  # noqa: BLE001 — transient Harmony error; classified below
            if "no matching granules" in str(exc).lower():
                print(f"[{gstart:%Y-%m-%d %H:%M}Z] no granule yet (Late Run ~14h latency) — skipping", flush=True)
                return None
            print(f"[{gstart:%Y-%m-%d %H:%M}Z] attempt {attempt} failed: {str(exc)[:80]}", flush=True)
            if attempt < GPM_MAX_ATTEMPTS:
                time.sleep(GPM_BACKOFF_SEC * attempt)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return None


def _extract_row(ds, q, gstart: pd.Timestamp) -> dict:
    """Nearest-pixel precip (+ extras) at query point `q`. NaNs if the granule was unavailable."""
    base = {"name": q["name"], "query_time_utc": q["time"], "lat": q["lat"], "lon": q["lon"],
            "granule_start_utc": gstart}
    if ds is None:
        nan = float("nan")
        return {**base, "pixel_lat": nan, "pixel_lon": nan,
                "precip_mm_hr": nan, "prob_liquid_pct": nan, "quality_index": nan}
    cell = ds.sel(lon=q["lon"], lat=q["lat"], method="nearest")

    def val(name):
        return float(cell[name].values.ravel()[0]) if name in cell else float("nan")

    return {**base,
            "pixel_lat": float(cell["lat"].values), "pixel_lon": float(cell["lon"].values),
            "precip_mm_hr": val("precipitation"),
            "prob_liquid_pct": val("probabilityLiquidPrecipitation"),
            "quality_index": val("precipitationQualityIndex")}


def fetch_points(queries: pd.DataFrame, collection_id: str) -> pd.DataFrame:
    """Group checks by half-hour granule, pull each granule once, extract the nearest pixel per point."""
    from harmony import BBox, Client, Collection

    queries = queries.copy()
    queries["granule"] = queries["time"].map(granule_start)
    collection = Collection(id=collection_id)
    client = Client()
    GRID_SUBDIR.mkdir(parents=True, exist_ok=True)

    rows = []
    for gstart, grp in queries.groupby("granule"):
        bbox = BBox(grp["lon"].min() - POINT_MARGIN_DEG, grp["lat"].min() - POINT_MARGIN_DEG,
                    grp["lon"].max() + POINT_MARGIN_DEG, grp["lat"].max() + POINT_MARGIN_DEG)
        ds = _download_granule(client, collection, bbox, gstart)
        for _, q in grp.iterrows():
            rows.append(_extract_row(ds, q, gstart))
    return pd.DataFrame(rows)


def fetch_grids(bbox_tuple, start, end, collection_id: str) -> list[Path]:
    """Store one compressed cutout NetCDF per half-hour over [start, end] for a bbox (no point extraction)."""
    from harmony import BBox, Client, Collection

    client = Client()
    collection = Collection(id=collection_id)
    GRID_SUBDIR.mkdir(parents=True, exist_ok=True)

    saved = []
    for gstart in pd.date_range(granule_start(start), granule_start(end), freq="30min"):
        ds = _download_granule(client, collection, BBox(*bbox_tuple), gstart)
        if ds is None:
            continue
        out = GRID_SUBDIR / f"late_{gstart:%Y%m%dT%H%M}Z.nc"
        ds.to_netcdf(out, encoding={v: {"zlib": True, "complevel": 4} for v in ds.data_vars})
        ds.close()
        saved.append(out)
        print(f"[{gstart:%Y-%m-%d %H:%M}Z] stored {out.name}", flush=True)
    return saved


def _append_csv(df: pd.DataFrame) -> None:
    """Append point results to the fine-labels CSV (header only on first write)."""
    FINE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(POINT_CSV, mode="a", header=not POINT_CSV.exists(), index=False)


def main() -> None:
    ap = argparse.ArgumentParser(description="GPM IMERG Late Run: recent-data rain checks (fine labels).")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--queries", help="CSV of checks: columns time,lat,lon[,name] (UTC times)")
    src.add_argument("--lat", type=float, help="point latitude (use with --lon)")
    src.add_argument("--bbox", help="grid-cutout box 'W,S,E,N' — stores NetCDF, no point extraction")
    ap.add_argument("--lon", type=float, help="point longitude (use with --lat)")
    ap.add_argument("--name", default="adhoc", help="label for a --lat/--lon point")
    ap.add_argument("--time", help="single UTC time, ISO 8601")
    ap.add_argument("--start", help="UTC start time for a point series or a --bbox window")
    ap.add_argument("--end", help="UTC end time for a point series or a --bbox window")
    ap.add_argument("--workers", type=int, default=8, help="parallel download threads per Harmony job")
    args = ap.parse_args()

    os.environ["NUM_REQUESTS_WORKERS"] = str(args.workers)  # set before harmony import
    cid = load_config()["gpm_imerg_late"]["harmony_collection_hhr"]

    if args.bbox:
        if not (args.start and args.end):
            ap.error("--bbox needs --start and --end")
        w, s, e, n = (float(x) for x in args.bbox.split(","))
        saved = fetch_grids((w, s, e, n), args.start, args.end, cid)
        print(f"\nStored {len(saved)} cutout grids -> {GRID_SUBDIR}")
        return

    if args.queries:
        queries = load_queries(Path(args.queries))
    else:
        if args.lon is None:
            ap.error("point mode needs --lat AND --lon (or use --queries)")
        if args.time:
            times = [granule_start(args.time)]
        elif args.start and args.end:
            times = pd.date_range(granule_start(args.start), granule_start(args.end), freq="30min")
        else:
            ap.error("point mode needs --time, or --start and --end")
        queries = pd.DataFrame({"name": args.name, "lat": args.lat, "lon": args.lon, "time": times})

    results = fetch_points(queries, cid)
    _append_csv(results)
    resolved = int(results["precip_mm_hr"].notna().sum())
    print(f"\n{resolved}/{len(results)} checks resolved -> {POINT_CSV}\n")
    print(results.to_string(index=False))


if __name__ == "__main__":
    main()
