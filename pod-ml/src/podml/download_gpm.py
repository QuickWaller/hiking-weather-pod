"""Step 2b — download a tiny slice of GPM IMERG and verify the precip *label* variable and its
timestamp convention (the period-beginning vs -ending question flagged in docs/03-datasets.md).

GPM is our label source for precipitation (independent of ERA5 — using ERA5's own precip as the
label would be partly circular and overstate skill). IMERG Final V07 covers 2000-06 onward.

Prereq — run ONCE in YOUR OWN terminal (interactive; persists Earthdata creds to netrc, no password
ever stored in the repo or pasted in chat):

    .\\.venv\\Scripts\\python.exe -c "import earthaccess; earthaccess.login(persist=True)"

Then:
    python -m podml.download_gpm
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

from podml.config import DATA_RAW, load_config

RAW = DATA_RAW / "gpm"


def inspect(path: Path, domain: dict | None = None) -> None:
    """Verify variable name, units, dims, and — crucially — the time convention."""
    print(f"\n{'=' * 70}\nInspecting {path.name}\n{'=' * 70}")
    try:
        ds = xr.open_dataset(path, group="Grid")  # IMERG stores fields under /Grid
    except Exception as e:  # noqa: BLE001
        print(f"  group='Grid' failed ({e}); trying root group...")
        ds = xr.open_dataset(path)

    print("--- Data variables ---")
    for name, v in ds.data_vars.items():
        print(f"  {name:30s} dims={v.dims} units={v.attrs.get('units', '?')}")

    pname = next((n for n in ds.data_vars if n.lower() == "precipitation"), None)
    pname = pname or next((n for n in ds.data_vars if "precip" in n.lower()), None)
    print("\n--- Precip field ---")
    if pname:
        p = ds[pname]
        vals = p.values.astype("float64")
        # NZ-only range so the numbers mean something (granule is global).
        if domain and {"latitude", "longitude"}.issubset(set(p.dims) | set(ds.coords)):
            try:
                sub = p.sel(
                    lon=slice(domain["west"], domain["east"]),
                    lat=slice(domain["south"], domain["north"]),
                ).values.astype("float64")
                vals = sub if np.isfinite(sub).any() else vals
            except Exception:  # noqa: BLE001
                pass
        good = np.isfinite(vals) & (vals >= 0)
        rng = (round(float(vals[good].min()), 3), round(float(vals[good].max()), 3)) if good.any() else None
        print(f"  name={pname!r}  units={p.attrs.get('units', '?')}  dims={p.dims}  range(>=0)={rng}")
    else:
        print("  !! no precipitation-like variable found — check product/version")

    print("\n--- Time convention (period-beginning vs -ending for the label window) ---")
    for tn in ("time", "time_bnds"):
        if tn in ds.variables:
            print(f"  {tn}: {np.atleast_1d(ds[tn].values).ravel()[:4]}")
    # The granule filename also encodes S<start>-E<end> of the half-hour window — print it.
    print(f"  filename window: {path.name}")
    ds.close()


def main() -> None:
    import earthaccess

    cfg = load_config()
    dom = cfg["domain"]
    gpm = cfg["gpm_imerg"]
    vs = cfg["time"]["verification_slice"]

    earthaccess.login()  # uses persisted netrc/env credentials

    bbox = (dom["west"], dom["south"], dom["east"], dom["north"])  # (W, S, E, N)
    print(f"Searching {gpm['product']} v{gpm['version']} over NZ {bbox} on {vs['start']} ...")
    results = earthaccess.search_data(
        short_name=gpm["product"],
        version=str(gpm["version"]),
        temporal=(f"{vs['start']}T00:00:00", f"{vs['start']}T01:30:00"),  # ~3 half-hour granules
        bounding_box=bbox,
    )
    print(f"Found {len(results)} granule(s).")
    if not results:
        print("No granules — verify product short_name/version and that the Earthdata login succeeded.")
        return

    RAW.mkdir(parents=True, exist_ok=True)
    try:
        files = earthaccess.download(results[:2], str(RAW))
    except Exception as e:  # noqa: BLE001
        # earthaccess reports GES DISC 403s as a generic "EULA" traceback. The real fix is a one-time
        # per-account client approval; surface the actionable URL instead of the stack trace.
        print(
            f"\nDownload failed ({type(e).__name__}). If this is a GES DISC 403, approve the data "
            "client ONCE (per Earthdata account) at:\n"
            "  https://urs.earthdata.nasa.gov/approve_app?client_id=e2WVk8Pw6weeLUKZYOxvTQ\n"
            "then re-run."
        )
        raise
    for f in files:
        inspect(Path(f), domain=dom)


if __name__ == "__main__":
    main()
