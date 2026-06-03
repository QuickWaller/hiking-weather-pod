"""Step 3b — choose ~200 training cells, stratified across the elevation range.

Each training row of the real model is an ERA5-Land 0.1° cell (≈11 km): both the features (ERA5) and the
label (GPM) are cell-resolution, so the natural sampling unit is the *cell*, not an arbitrary lat/lon.
We:
  1. aggregate the DEM (podml.download_dem) onto the ERA5-Land 0.1° grid → per-cell mean elevation + land
     fraction (so we can drop mostly-ocean coastal cells that ERA5-Land masks),
  2. keep land cells, and
  3. stratify-sample across elevation bands so the model sees the full orographic gradient (high alpine
     terrain is rare but is exactly where the elevation→rain signal lives — so we sample it ~evenly, not
     proportionally).

The 5 original probe points are always retained (continuity with the point-probe results). Output is a
small, COMMITTED table so both machines pull the identical set:

  config/sampled_points.csv   name,lat,lon,elevation_m,band,land_frac,kind

Usage:
    python -m podml.sample_points --n 200 --seed 0
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
import xarray as xr

from podml.config import CONFIG_PATH, DATA_RAW, load_config

DEM_PATH = DATA_RAW / "dem_nz.nc"
OUT_CSV = CONFIG_PATH.parent / "sampled_points.csv"

# Elevation band edges (m). Open-topped last band. ~Even sampling per band oversamples rare high terrain.
BAND_EDGES = [0, 50, 150, 400, 800, 1400]


def cell_table(dem: xr.Dataset, step: float = 0.1) -> pd.DataFrame:
    """Aggregate a DEM onto the ERA5-Land 0.1° grid → one row per cell.

    Returns columns: lat, lon (cell centres, snapped to the 0.1° grid), elevation_m (mean over the
    cell's LAND pixels), land_frac (fraction of the cell's DEM pixels above sea level).
    """
    z = dem["elevation"]
    df = pd.DataFrame(
        {
            "lat": np.repeat(z["lat"].values, z["lon"].size),
            "lon": np.tile(z["lon"].values, z["lat"].size),
            "elev": z.values.ravel(),
        }
    )
    df["clat"] = np.round(df["lat"] / step) * step
    df["clon"] = np.round(df["lon"] / step) * step
    df["is_land"] = df["elev"] > 0
    g = df.groupby(["clat", "clon"])
    out = pd.DataFrame(
        {
            "land_frac": g["is_land"].mean(),
            # mean elevation over land pixels only (NaN if the cell is all ocean)
            "elevation_m": df[df["is_land"]].groupby(["clat", "clon"])["elev"].mean(),
        }
    ).reset_index()
    out = out.rename(columns={"clat": "lat", "clon": "lon"})
    out["lat"] = out["lat"].round(2)
    out["lon"] = out["lon"].round(2)
    return out


def stratify_sample(cells: pd.DataFrame, n: int, edges=BAND_EDGES, min_land_frac=0.5, seed=0):
    """Pick ~n land cells, spread ~evenly across elevation bands (deficits redistributed)."""
    rng = np.random.default_rng(seed)
    land = cells[(cells["land_frac"] >= min_land_frac) & cells["elevation_m"].notna()].copy()
    land["band"] = np.digitize(land["elevation_m"], edges)  # 1..len(edges)
    bands = sorted(land["band"].unique())

    per = max(1, n // len(bands))
    picked = []
    for b in bands:
        pool = land[land["band"] == b]
        take = min(per, len(pool))
        picked.append(pool.sample(take, random_state=rng.integers(1 << 31)))
    chosen = pd.concat(picked)

    # Redistribute any shortfall by drawing from the (still-unused) deepest pools.
    if len(chosen) < n:
        rest = land.drop(index=chosen.index)
        if len(rest):
            chosen = pd.concat([chosen, rest.sample(min(n - len(chosen), len(rest)),
                                                     random_state=rng.integers(1 << 31))])
    return chosen.sort_values(["band", "lat", "lon"]).reset_index(drop=True)


def _name(lat: float, lon: float) -> str:
    return f"g{lat:+05.1f}_{lon:05.1f}".replace(".", "p").replace("+", "n").replace("-", "s")


def build(n: int, seed: int) -> pd.DataFrame:
    cells = cell_table(xr.open_dataset(DEM_PATH))
    samp = stratify_sample(cells, n=n, seed=seed)
    samp["name"] = [_name(la, lo) for la, lo in zip(samp["lat"], samp["lon"], strict=True)]
    samp["kind"] = "sampled"

    # Always retain the 5 original probe points (continuity with the point-probe results).
    probes = load_config()["probe_points"]
    extra = []
    for nm, p in probes.items():
        if not ((samp["lat"] == round(p["lat"], 2)) & (samp["lon"] == round(p["lon"], 2))).any():
            extra.append({"name": nm, "lat": p["lat"], "lon": p["lon"],
                          "elevation_m": p["elevation_m"], "band": -1, "land_frac": 1.0,
                          "kind": "probe"})
    out = pd.concat([samp, pd.DataFrame(extra)], ignore_index=True) if extra else samp
    cols = ["name", "lat", "lon", "elevation_m", "band", "land_frac", "kind"]
    return out[cols].round({"elevation_m": 0, "land_frac": 2})


def main() -> None:
    ap = argparse.ArgumentParser(description="Stratified-by-elevation ERA5 cell sample for NZ.")
    ap.add_argument("--n", type=int, default=200, help="approx number of sampled cells")
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    out = build(args.n, args.seed)
    out.to_csv(OUT_CSV, index=False)
    by_band = out[out["kind"] == "sampled"].groupby("band").size().to_dict()
    print(f"wrote {len(out)} points -> {OUT_CSV}")
    print(f"  sampled per elevation band {BAND_EDGES}+ : {by_band}")
    print(f"  elevation span: {out['elevation_m'].min():.0f}..{out['elevation_m'].max():.0f} m")


if __name__ == "__main__":
    main()
