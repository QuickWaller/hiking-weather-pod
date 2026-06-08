"""Static domain maps for pod-ml — terrain, the model grid, and per-cell static variables.

These need NO trained model: they describe the playing field the model trains on, and double as a
sanity check on the grid/DEM plumbing that motionsim + grid training depend on. Figures land in
docs/figures/ (same convention as plots.py). Maps use matplotlib pcolormesh on the real lat/lon
coordinates — no cartopy dependency.

Maps produced (each skipped gracefully if its source data is absent, so this also runs on a laptop
that only has the DEM):
  - terrain_grid.png   native DEM (pretty) + DEM aggregated onto the 0.1° ERA5 grid ("what the model
                       sees"), both with the sampled training cells overlaid.
  - static_vars.png    per-cell elevation, climate zone, and land/valid mask on the model grid.
  - climatology.png    2016-2024 mean precip, mean temperature, mean MSLP (the static "baseline" the
                       model learns anomalies against).

Usage:
    python -m podml.maps                 # all maps it has data for
"""

from __future__ import annotations


import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import xarray as xr

from podml.config import CONFIG_PATH, ROOT
from podml.era5_load import load_era5_nz, month_files
from podml.static_features import (
    elevation_to_zones,
    load_dem_grid,
    load_era5_orography,
    pressure_to_msl,
)

plt.switch_backend("Agg")  # headless

FIG = ROOT / "docs" / "figures"
SAMPLED_CSV = CONFIG_PATH.parent / "sampled_points.csv"

# Climatology window — the fully-downloaded ERA5/GPM span we train on.
CLIM_START, CLIM_END = 2016, 2024

# NZ-appropriate zone cuts (must match static_features.elevation_to_zones defaults).
ZONE_NAMES = ["lowland\n<300m", "hill\n300-1000m", "alpine\n1000-2000m", "high alpine\n>2000m"]


def _load_sampled() -> pd.DataFrame | None:
    if not SAMPLED_CSV.exists():
        return None
    return pd.read_csv(SAMPLED_CSV)


def _overlay_sampled(ax: plt.Axes, samp: pd.DataFrame | None) -> None:
    """Scatter the committed training cells: probes (stars) vs stratified-sampled cells (dots)."""
    if samp is None:
        return
    for kind, marker, size, label in [("sampled", "o", 9, "sampled cells"),
                                      ("probe", "*", 160, "probe points")]:
        sub = samp[samp["kind"] == kind]
        if len(sub):
            ax.scatter(sub["lon"], sub["lat"], s=size, marker=marker, c="red",
                       edgecolors="black", linewidths=0.4, label=label, zorder=5)


def _dem_on_grid(ds: xr.Dataset) -> xr.DataArray:
    """Interpolate the native DEM onto ds's (lat, lon) grid (linear, nearest-fill at edges)."""
    dem = load_dem_grid()
    g = dem.interp(lat=ds["lat"], lon=ds["lon"], method="linear")
    if np.isnan(g.values).any():
        g = g.fillna(dem.interp(lat=ds["lat"], lon=ds["lon"], method="nearest"))
    return g


def _grid_ref() -> xr.Dataset | None:
    """One ERA5 year, lazily — just to get the model's (lat, lon) grid and a land/valid mask."""
    return load_era5_nz(CLIM_END, CLIM_END, group="core")


def _land_mask(ref: xr.Dataset) -> np.ndarray:
    """Boolean (lat, lon) mask of usable land cells (ERA5-Land masks sea as NaN)."""
    return ~np.isnan(ref["sp"].isel(valid_time=0).values)


def _orog_on_grid(ds: xr.Dataset) -> np.ndarray:
    """ERA5-Land orography height (m) selected onto ds's grid (same 0.1° lattice → exact cells)."""
    return load_era5_orography().interp(lat=ds["lat"], lon=ds["lon"], method="nearest").values


def map_terrain_grid(samp: pd.DataFrame | None) -> None:
    """Native DEM (pretty) beside the DEM aggregated onto the 0.1° model grid."""
    dem = load_dem_grid()
    ref = _grid_ref()

    ncols = 2 if ref is not None else 1
    fig, axes = plt.subplots(1, ncols, figsize=(7.5 * ncols, 8), squeeze=False)
    axes = axes[0]

    m = axes[0].pcolormesh(dem["lon"], dem["lat"], dem.values, cmap="terrain",
                           vmin=0, shading="auto")
    axes[0].set_title(f"NZ terrain (native DEM ~{dem['lat'].size}×{dem['lon'].size})")
    fig.colorbar(m, ax=axes[0], shrink=0.7, label="elevation (m)")
    _overlay_sampled(axes[0], samp)

    if ref is not None:
        # Mask the model-grid panel to usable land cells so it shows only what training uses.
        elev_grid = np.where(_land_mask(ref), _dem_on_grid(ref).values, np.nan)
        m2 = axes[1].pcolormesh(ref["lon"], ref["lat"], elev_grid, cmap="terrain",
                                vmin=0, shading="auto", edgecolors="k", linewidth=0.05)
        axes[1].set_title(f"On the 0.1° ERA5 grid — what the model sees "
                          f"({ref['lat'].size}×{ref['lon'].size} cells)")
        fig.colorbar(m2, ax=axes[1], shrink=0.7, label="cell mean elevation (m)")
        _overlay_sampled(axes[1], samp)

    for ax in axes:
        ax.set_xlabel("lon")
        ax.set_ylabel("lat")
        ax.set_aspect("equal")
        ax.grid(alpha=0.25, lw=0.5)
        if samp is not None:
            ax.legend(fontsize=8, loc="lower left")
    fig.suptitle("Terrain & the training grid", fontsize=14)
    fig.tight_layout()
    fig.savefig(FIG / "terrain_grid.png", dpi=120)
    plt.close(fig)
    print("wrote terrain_grid.png")


def map_static_vars(samp: pd.DataFrame | None) -> None:
    """Per-cell elevation, climate zone, and land/valid mask on the model grid."""
    ref = _grid_ref()
    if ref is None:
        print("skip static_vars.png — no ERA5 grid on disk")
        return
    valid = _land_mask(ref)
    elev = np.where(valid, _dem_on_grid(ref).values, np.nan)
    zones = np.where(valid, elevation_to_zones(np.nan_to_num(elev)), np.nan)

    fig, axes = plt.subplots(1, 3, figsize=(21, 7))
    m0 = axes[0].pcolormesh(ref["lon"], ref["lat"], elev, cmap="terrain", vmin=0, shading="auto")
    axes[0].set_title("cell elevation (m)")
    fig.colorbar(m0, ax=axes[0], shrink=0.7)

    m1 = axes[1].pcolormesh(ref["lon"], ref["lat"], zones, cmap="YlOrBr", shading="auto",
                            vmin=0, vmax=len(ZONE_NAMES) - 1)
    axes[1].set_title("climate zone (from elevation)")
    cb = fig.colorbar(m1, ax=axes[1], shrink=0.7, ticks=range(len(ZONE_NAMES)))
    cb.ax.set_yticklabels(ZONE_NAMES, fontsize=7)

    m2 = axes[2].pcolormesh(ref["lon"], ref["lat"], valid.astype(float), cmap="Greens", shading="auto")
    axes[2].set_title("land / valid ERA5-Land cells (green = usable)")
    fig.colorbar(m2, ax=axes[2], shrink=0.7)

    for ax in axes:
        ax.set_xlabel("lon")
        ax.set_ylabel("lat")
        ax.set_aspect("equal")
        ax.grid(alpha=0.25, lw=0.5)
        _overlay_sampled(ax, samp)
    fig.suptitle("Static per-cell variables", fontsize=14)
    fig.tight_layout()
    fig.savefig(FIG / "static_vars.png", dpi=120)
    plt.close(fig)
    print("wrote static_vars.png")


def map_climatology() -> None:
    """2016-2024 mean precip / temperature / MSLP — the static baseline behind the anomalies.

    Streamed one month at a time (per-cell running sum + count) so peak RAM stays ~one month, not
    9 years. A whole-span ``.mean().compute()`` OOM-killed the VM; never load the full span at once.
    """
    files = month_files(CLIM_START, CLIM_END, group="core")
    if not files:
        print("skip climatology.png — no ERA5 grid on disk")
        return
    print(f"climatology: streaming {len(files)} months {CLIM_START}-{CLIM_END} (bounded RAM)...", flush=True)

    sp_sum = t2m_sum = tp_sum = None
    n = 0
    grid_ref: xr.Dataset | None = None
    for i, f in enumerate(files):
        ds = xr.open_dataset(f)
        if sp_sum is None:
            grid_ref = ds[["sp", "lat", "lon"]].isel(valid_time=0).load()  # tiny: coords + mask only
            shape = ds["sp"].isel(valid_time=0).shape
            sp_sum = np.zeros(shape)
            t2m_sum = np.zeros(shape)
            tp_sum = np.zeros(shape)
        # skipna=False keeps ocean (always-NaN) cells NaN so they mask out naturally.
        sp_sum = sp_sum + ds["sp"].sum(dim="valid_time", skipna=False).values
        t2m_sum = t2m_sum + ds["t2m"].sum(dim="valid_time", skipna=False).values
        tp_sum = tp_sum + ds["tp"].sum(dim="valid_time", skipna=False).values
        n += ds.sizes["valid_time"]
        ds.close()
        if (i + 1) % 12 == 0:
            print(f"  ...{i + 1}/{len(files)} months", flush=True)

    assert grid_ref is not None
    valid = ~np.isnan(grid_ref["sp"].values)  # grid_ref already at valid_time=0
    # MSLP reduction uses ERA5-Land's OWN orography (the height sp lives at), not the DEM.
    orog = _orog_on_grid(grid_ref)
    temp_c = np.where(valid, t2m_sum / n - 273.15, np.nan)
    precip_mm_day = np.where(valid, tp_sum / n * 1000.0 * 24.0, np.nan)   # m/hr accum → mm/day
    mslp = np.where(valid, pressure_to_msl(sp_sum / n / 100.0, orog, np.nan_to_num(temp_c)), np.nan)
    ds_lat, ds_lon = grid_ref["lat"], grid_ref["lon"]

    panels = [
        ("mean precip (mm/day)", precip_mm_day, "Blues", None, None),
        ("mean temperature (°C)", temp_c, "RdYlBu_r", None, None),
        ("mean MSLP (hPa)", mslp, "viridis", None, None),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(21, 7))
    for ax, (title, data, cmap, vmin, vmax) in zip(axes, panels):
        m = ax.pcolormesh(ds_lon, ds_lat, data, cmap=cmap, shading="auto", vmin=vmin, vmax=vmax)
        ax.set_title(title)
        fig.colorbar(m, ax=ax, shrink=0.7)
        ax.set_xlabel("lon")
        ax.set_ylabel("lat")
        ax.set_aspect("equal")
        ax.grid(alpha=0.25, lw=0.5)
    fig.suptitle(f"Climatology {CLIM_START}–{CLIM_END} (ERA5-Land)", fontsize=14)
    fig.tight_layout()
    fig.savefig(FIG / "climatology.png", dpi=120)
    plt.close(fig)
    print("wrote climatology.png")


def main() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    samp = _load_sampled()
    map_terrain_grid(samp)
    map_static_vars(samp)
    map_climatology()
    print(f"figures -> {FIG}")


if __name__ == "__main__":
    main()
