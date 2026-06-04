"""Deep integrity check for the downloaded monthly grids — the layer the file-count
dashboard can't do.

`status_server.py` only knows whether a file *exists*. This opens each month and asks
"is it actually usable?": does it decode, does it hold a full month of timesteps, is the
time axis sane, are the expected variables present, and is there real (non-NaN) data over
the NZ box. A month that exists but fails these is worse than a missing one — it silently
poisons the labels — so the management agent re-pulls it (delete the file; the watchdog
refetches on its next tick).

Emits JSON (``--json``) for the agent, or a human summary by default.

  python -m podml.validate                 # human summary, both datasets
  python -m podml.validate --json          # machine-readable, for Hermes
  python -m podml.validate --dataset gpm   # one dataset
  python -m podml.validate --deep          # scan every timestep for NaN, not just a sample

A month is reported under "problems" with the specific failing checks; the agent maps that
to a re-pull. Read-only — never deletes or modifies anything.
"""

from __future__ import annotations

import argparse
import calendar
import json
import re
import sys
from pathlib import Path

from podml.config import DATA_RAW

# Per-dataset shape expectations. steps_per_day: 48 = 30-min (GPM), 24 = hourly (ERA5).
# min_valid_frac: floor on the fraction of non-NaN cells in the sampled field. GPM precip is
# global (ocean has real values) so we expect lots of valid data; ERA5-Land is land-only, so a
# mostly-ocean NZ box is legitimately mostly-NaN — there we only flag a *completely* empty field.
DATASETS = {
    "gpm": {
        "dir": DATA_RAW / "gpm_grid",
        "glob": "gpm_*.nc",
        "steps_per_day": 48,
        "required_vars": ["precipitation"],
        "probe_var": "precipitation",
        "min_valid_frac": 0.5,
    },
    "era5": {
        "dir": DATA_RAW / "era5_grid",
        "glob": "era5land_nz_*.nc",
        "steps_per_day": 24,
        "required_vars": ["sp", "t2m", "d2m", "tp"],
        "probe_var": "tp",
        "min_valid_frac": 0.0,  # land-only: only flag a 100%-NaN field
    },
}

_TIME_DIMS = ("time", "valid_time")
_YM = re.compile(r"(\d{4})-(\d{2})")


def _ym_from_name(name: str) -> tuple[int, int] | None:
    m = _YM.search(name)
    return (int(m.group(1)), int(m.group(2))) if m else None


def _time_coord(ds):
    for d in _TIME_DIMS:
        if d in ds.variables:
            return d
    return None


def _check_file(path: Path, spec: dict, deep: bool) -> list[str]:
    """Return a list of issue strings for one month file ([] = clean)."""
    import numpy as np
    import xarray as xr

    issues: list[str] = []
    try:
        ds = xr.open_dataset(path)
    except Exception as exc:  # noqa: BLE001 — corrupt / truncated / not NetCDF
        return [f"won't open: {type(exc).__name__}: {str(exc)[:60]}"]

    try:
        # --- variables present ---
        missing = [v for v in spec["required_vars"] if v not in ds.variables]
        if missing:
            issues.append(f"missing vars: {','.join(missing)}")

        # --- timestep count vs a full month ---
        tdim = _time_coord(ds)
        ym = _ym_from_name(path.name)
        if tdim is None:
            issues.append("no time coordinate")
        elif ym is not None:
            days = calendar.monthrange(ym[0], ym[1])[1]
            expected = days * spec["steps_per_day"]
            n = int(ds.sizes.get(tdim, 0))
            if n < 0.95 * expected:
                issues.append(f"steps {n}/{expected} ({100 * n / expected:.0f}%)")
            # --- time axis sane: strictly increasing, no dupes ---
            tvals = ds[tdim].values
            if n > 1:
                diffs = np.diff(tvals.astype("datetime64[ns]").astype("int64"))
                if (diffs <= 0).any():
                    issues.append("time axis not strictly increasing (dupes/gaps)")

        # --- real data present over the NZ box ---
        pv = spec["probe_var"]
        if pv in ds.variables:
            da = ds[pv]
            sample = da if deep else (da.isel({tdim: da.sizes[tdim] // 2}) if tdim else da)
            arr = np.asarray(sample.values, dtype="float64")
            total = arr.size
            valid = int(np.isfinite(arr).sum()) if total else 0
            frac = valid / total if total else 0.0
            if spec["min_valid_frac"] == 0.0:
                if valid == 0:
                    issues.append(f"{pv} field is 100% NaN/empty")
            elif frac < spec["min_valid_frac"]:
                issues.append(f"{pv} valid {100 * frac:.0f}% (< {100 * spec['min_valid_frac']:.0f}%)")
        else:
            issues.append(f"probe var '{pv}' absent")
    finally:
        ds.close()

    return issues


def validate_dataset(name: str, deep: bool = False) -> dict:
    spec = DATASETS[name]
    files = sorted(spec["dir"].glob(spec["glob"]))
    problems = []
    for f in files:
        issues = _check_file(f, spec, deep)
        if issues:
            problems.append({"file": f.name, "month": None if _ym_from_name(f.name) is None
                             else "%04d-%02d" % _ym_from_name(f.name), "issues": issues})
    return {
        "dir": str(spec["dir"]),
        "n_files": len(files),
        "ok": len(files) - len(problems),
        "bad": len(problems),
        "problems": problems,
    }


def run(datasets: list[str], deep: bool) -> dict:
    import time
    return {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "deep": deep,
        "datasets": {name: validate_dataset(name, deep) for name in datasets},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Deep integrity check of downloaded monthly grids.")
    ap.add_argument("--dataset", choices=[*DATASETS, "all"], default="all")
    ap.add_argument("--deep", action="store_true",
                    help="scan every timestep for NaN (default: sample one mid-month step)")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = ap.parse_args()

    names = list(DATASETS) if args.dataset == "all" else [args.dataset]
    report = run(names, args.deep)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        for name, d in report["datasets"].items():
            print(f"\n{name}: {d['ok']}/{d['n_files']} clean, {d['bad']} bad  ({d['dir']})")
            for p in d["problems"]:
                print(f"  ✗ {p['file']}: {'; '.join(p['issues'])}")
        print()

    # Non-zero exit if anything is broken — lets a supervisor / agent branch on it.
    total_bad = sum(d["bad"] for d in report["datasets"].values())
    return 1 if total_bad else 0


if __name__ == "__main__":
    sys.exit(main())
