"""Step 2 — download a small NZ slice of ERA5-Land hourly *time-series* and verify the
variable catalogue against our design assumptions (see docs/03-datasets.md).

The goal here is VERIFICATION, not bulk download: pull one week at one point, then print
the real variable names, units, grid snapping, and time convention so we can confirm
reality before building features/labels on top.

Prereq: a configured `~/.cdsapirc` (CDS API url + key). See README "Data access".

Usage:
    python -m podml.download_era5                 # 1-week slice, verification point (cheap)
    python -m podml.download_era5 --point mtcook_alpine
    python -m podml.download_era5 --full          # full train..test range, ALL probe points
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

from podml.config import ROOT
from podml.config import DATA_RAW as RAW
from podml.config import load_config
from podml.dataio import load_timeseries


def build_request(variables, lon: float, lat: float, date_range: str, fmt: str = "netcdf") -> dict:
    """Time-series request schema (differs from gridded: single point, date as 'start/end')."""
    return {
        "variable": list(variables),
        "location": {"longitude": float(lon), "latitude": float(lat)},
        "date": [date_range],  # e.g. "2022-06-01/2022-06-07"
        "data_format": fmt,
    }


def _cds_client():
    """Build a CDS client, preferring a repo-local .cdsapirc (gitignored) over ~/.cdsapirc."""
    import os

    import cdsapi  # imported lazily so the module loads even before credentials exist

    repo_rc = ROOT / ".cdsapirc"
    if repo_rc.exists():
        # cdsapi reads the rc file named by $CDSAPI_RC, else ~/.cdsapirc.
        os.environ.setdefault("CDSAPI_RC", str(repo_rc))
    return cdsapi.Client()


def download_point(dataset: str, request: dict, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    client = _cds_client()
    client.retrieve(dataset, request).download(str(out_path))
    return out_path


def inspect(path: Path) -> None:
    """Print everything we need to verify against docs/03-datasets.md."""
    print(f"\n{'=' * 70}\nInspecting {path.name}\n{'=' * 70}")
    try:
        ds = load_timeseries(path)
    except Exception as e:  # noqa: BLE001
        print(f"  Could not load ({e}).")
        return

    print(ds)  # full repr: dims, coords, data_vars, global attrs

    print("\n--- Coordinates (verify lat/lon snapping to the 0.1deg grid) ---")
    for name, c in ds.coords.items():
        vals = np.atleast_1d(c.values)
        show = vals[:3] if vals.size > 3 else vals
        print(f"  {name}: dtype={c.dtype} shape={c.shape} e.g. {show}")
        keep = {k: c.attrs[k] for k in ("units", "calendar", "long_name") if k in c.attrs}
        if keep:
            print(f"      attrs={keep}")

    # Time convention — critical for the strictly-after-T label window.
    tname = next((n for n in ds.coords if "time" in n.lower()), None)
    if tname is not None:
        t = ds[tname]
        print(f"\n--- Time coord '{tname}' (confirm hourly + period convention) ---")
        print(f"  first: {np.atleast_1d(t.values)[:3]}")
        print(f"  last:  {np.atleast_1d(t.values)[-1]}")
        if t.size > 1:
            print(f"  spacing (first steps): {np.diff(np.atleast_1d(t.values)[:5])}")

    print("\n--- Data variables (name / units / range / long_name) ---")
    for name, v in ds.data_vars.items():
        units = v.attrs.get("units", "?")
        long = v.attrs.get("long_name", "")
        vals = v.values.astype("float64")
        if np.isfinite(vals).any():
            rng = (round(float(np.nanmin(vals)), 4), round(float(np.nanmax(vals)), 4))
        else:
            rng = ("all-NaN", "all-NaN")
        print(f"  {name:8s} units={str(units):10s} range={rng}  {long}")

    print("\n--- Sanity checks vs docs/03-datasets.md ---")
    names = set(ds.data_vars)
    _check("surface pressure present (sp)", "sp" in names)
    _check("2m temp present (t2m)", "t2m" in names)
    _check("2m dewpoint present (d2m) [we derive RH from t2m+d2m]", "d2m" in names)
    _check("10m wind present (u10,v10)", {"u10", "v10"} <= names)
    _check("total precip present (tp) [labels use GPM; this is cross-check]", "tp" in names)
    _check("NO mean-sea-level pressure (we reduce sp ourselves)", "msl" not in names)
    _check("NO wind gust (gusts come from ERA5 single-levels at step 4)",
           not any("gust" in n.lower() or n in {"i10fg", "fg10"} for n in names))
    ds.close()


def _check(label: str, ok: bool) -> None:
    print(f"  [{'OK ' if ok else '!! '}] {label}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Download + verify ERA5-Land time-series for NZ points.")
    ap.add_argument("--full", action="store_true",
                    help="Full train..test date range, ALL probe points (large).")
    ap.add_argument("--point", help="Probe point name (default: config verification_point).")
    args = ap.parse_args()

    cfg = load_config()
    era = cfg["era5_land"]
    dataset = era["timeseries_dataset"]
    variables = era["candidate_variables"]
    points = cfg["probe_points"]
    t = cfg["time"]

    if args.full:
        selected = points
        # Acquire the full span (1991..test) so we have the recent-climatology reference + ablation
        # windows; the actual training window is chosen empirically at step 5.
        start = t.get("acquisition_start", t["train_start"])
        date_range = f"{start}/{t['test_year']}-12-31"
    else:
        name = args.point or cfg.get("verification_point") or next(iter(points))
        selected = {name: points[name]}
        vs = t["verification_slice"]
        date_range = f"{vs['start']}/{vs['end']}"

    print(f"Dataset : {dataset}")
    print(f"Variables: {variables}")
    print(f"Date range: {date_range}")
    print(f"Points  : {list(selected)}")

    for name, p in selected.items():
        tag = date_range.replace("/", "_")
        out = RAW / f"era5land_ts_{name}_{tag}.nc"
        print(f"\n>>> {name}  ({p['lat']}, {p['lon']})  [{p['regime']}]  ->  {out.name}")
        req = build_request(variables, p["lon"], p["lat"], date_range)
        download_point(dataset, req, out)
        inspect(out)


if __name__ == "__main__":
    main()
