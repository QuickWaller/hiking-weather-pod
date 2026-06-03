"""Unit tests for the elevation-stratified cell sampler (pure functions, synthetic DEM)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import xarray as xr

from podml.sample_points import BAND_EDGES, cell_table, stratify_sample


def _synthetic_dem(step_deg=0.01):
    """A tiny DEM: two 0.1° cells, one all-land sloping, one half-ocean."""
    lat = np.round(np.arange(-41.05, -40.94, step_deg), 3)  # spans cells -41.0 and -41.1
    lon = np.round(np.arange(174.00, 174.11, step_deg), 3)  # spans cells 174.0 and 174.1
    elev = np.zeros((lat.size, lon.size))
    elev[:, :] = 100.0  # mostly land at 100 m
    elev[: lat.size // 2, 0] = -50.0  # punch some ocean into the western column
    return xr.Dataset({"elevation": (("lat", "lon"), elev)}, coords={"lat": lat, "lon": lon})


def test_cell_table_means_land_only_and_land_frac():
    tab = cell_table(_synthetic_dem())
    # cells snap to the 0.1° grid
    assert set(tab["lat"].round(1)) <= {-41.0, -41.1}
    # land-mean ignores the ocean pixels → stays at 100 m, never pulled toward -50
    assert np.allclose(tab["elevation_m"].dropna(), 100.0)
    # land_frac is between 0 and 1, and the ocean-punched area drops some cells below 1.0
    assert tab["land_frac"].between(0, 1).all()
    assert (tab["land_frac"] < 1.0).any()


def test_stratify_sample_respects_n_bands_and_land():
    # Build a cell table directly: 300 cells across the full elevation range, all land.
    rng = np.random.default_rng(0)
    cells = pd.DataFrame(
        {
            "lat": np.round(rng.uniform(-47, -35, 300), 1),
            "lon": np.round(rng.uniform(167, 178, 300), 1),
            "elevation_m": rng.uniform(1, 2500, 300),
            "land_frac": 1.0,
        }
    ).drop_duplicates(["lat", "lon"])

    samp = stratify_sample(cells, n=60, seed=1)
    assert 50 <= len(samp) <= 60  # ~n, allowing for band scarcity
    assert (samp["elevation_m"] > 0).all()
    assert samp["band"].nunique() == len(BAND_EDGES)  # every band represented


def test_stratify_sample_drops_ocean_cells():
    cells = pd.DataFrame(
        {
            "lat": [-41.0, -41.1, -41.2],
            "lon": [174.0, 174.1, 174.2],
            "elevation_m": [100.0, 200.0, np.nan],  # third is all-ocean
            "land_frac": [1.0, 0.3, 0.0],  # second is mostly ocean → excluded by min_land_frac
        }
    )
    samp = stratify_sample(cells, n=10, min_land_frac=0.5, seed=0)
    assert set(samp["lat"]) == {-41.0}  # only the genuine land cell survives
