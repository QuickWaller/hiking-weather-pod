"""Unit tests for grid_to_xy — the leakage-critical part of grid training.

The earlier grid code flattened (time, lat, lon) before windowing, so a rain
spike in one cell leaked labels into adjacent cells. These tests pin the fix:
windowing runs per cell along time only, and every feature/label/time row stays
aligned under the C-order (row = t*n_cells + c) stacking.
"""

import numpy as np
import pandas as pd
import xarray as xr

from podml.labels import forward_window_max
from podml.train_grid import FEATURE_COLS, _forward_window_max_2d, grid_to_xy


def _toy_grid(tp_mm: np.ndarray):
    """Build a synthetic ERA5-style grid + DEM + climatology from a (time,lat,lon) mm array."""
    n_time, n_lat, n_lon = tp_mm.shape
    t = pd.date_range("2021-06-01", periods=n_time, freq="h")
    lat = np.array([-44.0, -43.0])[:n_lat]
    lon = np.array([170.0, 171.0])[:n_lon]
    ds = xr.Dataset(
        {
            "sp": (("valid_time", "lat", "lon"), np.full(tp_mm.shape, 101325.0)),
            "t2m": (("valid_time", "lat", "lon"), np.full(tp_mm.shape, 283.15)),
            "d2m": (("valid_time", "lat", "lon"), np.full(tp_mm.shape, 280.15)),
            "tp": (("valid_time", "lat", "lon"), tp_mm / 1000.0),  # mm -> m
        },
        coords={"valid_time": t, "lat": lat, "lon": lon},
    )
    elev = np.array([[100.0, 200.0], [300.0, 2500.0]])[:n_lat, :n_lon]
    dem = xr.DataArray(elev, dims=("lat", "lon"), coords={"lat": lat, "lon": lon})
    clim = {
        "precip_mean": np.full((n_lat, n_lon), 0.5),
        "pressure_mean": np.full((n_lat, n_lon), 1013.0),
        "temp_mean": np.full((n_lat, n_lon), 10.0),
    }
    return ds, dem, clim


def test_forward_window_max_2d_matches_per_column_1d():
    # The 2D windowing must equal applying the trusted 1D version to each column.
    rng = np.random.default_rng(0)
    x = rng.random((20, 5))
    out = _forward_window_max_2d(x, 3)
    for c in range(x.shape[1]):
        ref = forward_window_max(x[:, c], 3)
        np.testing.assert_allclose(out[:, c], ref, equal_nan=True)


def test_grid_to_xy_shapes_and_columns():
    ds, dem, clim = _toy_grid(np.zeros((8, 2, 2)))
    X, y, times = grid_to_xy(ds, dem, clim, horizons=[2], thresholds=[0.5, 2.5, 7.6])
    assert X.shape == (8 * 4, len(FEATURE_COLS))   # 8 timesteps x 4 cells
    assert list(X.columns) == FEATURE_COLS
    assert set(y.columns) == {"ge0.5_h2", "ge2.5_h2", "ge7.6_h2"}
    assert len(times) == 8 * 4


def test_grid_to_xy_no_cross_cell_leak():
    # One 10 mm spike in cell (0,0) at t=3. With h=2 it must label ONLY that cell's
    # rows at t=1 and t=2 (window t+1..t+2 reaches t=3) — never another cell.
    tp = np.zeros((8, 2, 2))
    tp[3, 0, 0] = 10.0
    ds, dem, clim = _toy_grid(tp)
    _, y, _ = grid_to_xy(ds, dem, clim, horizons=[2], thresholds=[7.6])

    col = "ge7.6_h2"
    # cell (0,0) -> c=0; row = t*n_cells + c
    n_cells = 4
    expected_hot = {1 * n_cells + 0, 2 * n_cells + 0}
    hot = set(np.where(y[col].to_numpy() == 1.0)[0])
    assert hot == expected_hot

    # Tail (t=6,7) has incomplete future -> NaN; everything else defined is 0 or the spike.
    defined = y[col].dropna()
    assert set(defined.index) == set(range(6 * n_cells))      # rows 0..23 defined
    assert (defined.drop(index=list(expected_hot)) == 0.0).all()


def test_grid_to_xy_static_features_tiled_per_cell():
    ds, dem, clim = _toy_grid(np.zeros((3, 2, 2)))
    X, _, _ = grid_to_xy(ds, dem, clim, horizons=[2], thresholds=[0.5])
    # row = t*4 + c, so the first 4 rows are the 4 cells in C-order at t=0.
    assert list(X["elevation"].iloc[:4]) == [100.0, 200.0, 300.0, 2500.0]
    # zone thresholds [300,1000,2000]: 100->0, 200->0, 300->1, 2500->3
    assert list(X["zone"].iloc[:4]) == [0, 0, 1, 3]
    # static values repeat for the next timestep block.
    assert X["elevation"].iloc[4] == 100.0
    assert X["precip_mean"].iloc[0] == 0.5


def test_grid_to_xy_humidity_in_range():
    ds, dem, clim = _toy_grid(np.zeros((4, 2, 2)))
    X, _, _ = grid_to_xy(ds, dem, clim, horizons=[2], thresholds=[0.5])
    assert (X["rh"] >= 0).all() and (X["rh"] <= 100).all()
