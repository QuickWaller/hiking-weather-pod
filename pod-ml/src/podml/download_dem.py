"""Step 3a — fetch a NZ elevation grid (ETOPO 2022, NOAA, public domain).

Used for two things downstream:
  1. a LAND MASK + per-cell elevation, to stratify ~200 training points across the orographic range
     (see podml.sample_points), and
  2. the per-point **elevation feature** (the pod feeds its own measured altitude at inference; here the
     training point gets its true ground height).

We OPeNDAP-subset the global ETOPO file to the NZ box, so only the subset (~MBs) transfers — no giant
global download and no rasterio/GIS dependency (xarray + netcdf4 read it). 30 arc-sec ≈ 0.9 km is ample:
GPM labels are 11 km, so finer elevation adds no *trainable* signal, and inference uses the pod's own
altitude anyway. A later swap to Copernicus 30 m point-sampling is a clean upgrade if needed.

  data/raw/dem_nz.nc   elevation (m), NZ box, ~1 km

Usage:
    python -m podml.download_dem            # 30 arc-sec (default)
    python -m podml.download_dem --res 60s  # coarser/faster
"""

from __future__ import annotations

import argparse

import xarray as xr

from podml.config import DATA_RAW, load_config

# NOAA NCEI THREDDS OPeNDAP endpoint for the global ETOPO 2022 surface-elevation grid.
ETOPO_DODS = (
    "https://www.ngdc.noaa.gov/thredds/dodsC/global/ETOPO2022/"
    "{res}/{res}_surface_elev_netcdf/ETOPO_2022_v1_{res}_N90W180_surface.nc"
)
OUT = DATA_RAW / "dem_nz.nc"


def _pick(ds, *candidates: str) -> str:
    """Return the first candidate name present in the dataset (coords or vars)."""
    for c in candidates:
        if c in ds.variables:
            return c
    raise KeyError(f"none of {candidates} found in {list(ds.variables)}")


def fetch_nz_dem(domain: dict, res: str = "30s", out=OUT):
    """OPeNDAP-subset ETOPO to the NZ box; save elevation(lat, lon) → out."""
    url = ETOPO_DODS.format(res=res)
    print(f"opening (OPeNDAP) {url}")
    ds = xr.open_dataset(url)
    lat = _pick(ds, "lat", "latitude", "y")
    lon = _pick(ds, "lon", "longitude", "x")
    zname = _pick(ds, "z", "elevation", "Band1", "surface")

    south, north = sorted((domain["south"], domain["north"]))
    west, east = sorted((domain["west"], domain["east"]))
    sub = ds[[zname]].sel({lat: slice(south, north), lon: slice(west, east)})
    if sub[lat].size == 0:  # ETOPO lat stored descending → flip the slice
        sub = ds[[zname]].sel({lat: slice(north, south), lon: slice(west, east)})
    sub = sub.rename({zname: "elevation", lat: "lat", lon: "lon"}).load()
    ds.close()

    out.parent.mkdir(parents=True, exist_ok=True)
    sub.to_netcdf(out, encoding={"elevation": {"zlib": True, "complevel": 4}})
    print(
        f"saved {out.name}  dims={dict(sub.sizes)}  "
        f"elev {float(sub.elevation.min()):.0f}..{float(sub.elevation.max()):.0f} m"
    )
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Fetch NZ-box ETOPO 2022 elevation grid via OPeNDAP.")
    ap.add_argument("--res", default="30s", choices=["30s", "60s"], help="grid resolution")
    args = ap.parse_args()
    cfg = load_config()
    fetch_nz_dem(cfg["domain"], res=args.res)


if __name__ == "__main__":
    main()
