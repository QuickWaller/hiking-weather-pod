"""Unit tests for podml.maps (static domain maps) and the ERA5-Land orography loader.

The map-drawing functions are also integration-checked by the real VM runs (they produced correct
terrain/static/climatology figures); here we unit-test the new algorithmic pieces — the MSLP
reduction physics and the geopotential→height loader — plus a smoke test that the plotting path runs
end-to-end and writes a PNG.
"""

import numpy as np
import pytest
import xarray as xr

from podml import maps
from podml.maps import pressure_to_msl
from podml.static_features import G0, load_era5_orography


def test_pressure_to_msl_zero_elevation_is_identity():
    """At sea level there's nothing to reduce — MSLP equals the station pressure."""
    p = np.array([1000.0, 980.0])
    assert np.allclose(pressure_to_msl(p, np.zeros(2), np.full(2, 10.0)), p)


def test_pressure_to_msl_increases_with_elevation():
    """Higher station → larger sea-level value (we add back the air column below it)."""
    p = np.full(3, 850.0)
    t = np.full(3, 5.0)
    msl = pressure_to_msl(p, np.array([0.0, 1000.0, 1800.0]), t)
    assert msl[0] < msl[1] < msl[2]
    assert msl[0] == pytest.approx(850.0, abs=1e-6)


def test_pressure_to_msl_alpine_lands_in_physical_band():
    """A ~810 hPa reading at ~1800 m should reduce into the realistic MSLP band, not blow up."""
    msl = pressure_to_msl(np.array([812.0]), np.array([1800.0]), np.array([2.0]))
    assert 980.0 < msl[0] < 1045.0


def test_load_era5_orography_converts_and_squeezes_time(tmp_path):
    """z (m²/s²) → height (m) via /g, and the singleton time dim is dropped."""
    lat = np.array([-46.0, -45.9])
    lon = np.array([168.0, 168.1])
    # z chosen so z/g = [[0, 1000], [10000, 2000]] m
    z = np.array([[[0.0, 1000.0 * G0], [10000.0 * G0, 2000.0 * G0]]])
    ds = xr.Dataset({"z": (("time", "lat", "lon"), z)},
                    coords={"time": [0], "lat": lat, "lon": lon})
    path = tmp_path / "geo.nc"
    ds.to_netcdf(path)

    orog = load_era5_orography(path)
    assert "time" not in orog.dims
    assert orog.sel(lat=-46.0, lon=168.0).item() == pytest.approx(0.0)
    assert orog.sel(lat=-46.0, lon=168.1).item() == pytest.approx(1000.0, rel=1e-6)
    assert orog.sel(lat=-45.9, lon=168.0).item() == pytest.approx(10000.0, rel=1e-6)


def test_load_era5_orography_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_era5_orography(tmp_path / "does_not_exist.nc")


def test_terrain_map_smoke(tmp_path, monkeypatch):
    """The plotting path runs and writes a PNG (DEM-only branch, no ERA5/orography needed)."""
    lat = np.linspace(-47.0, -34.0, 20)
    lon = np.linspace(166.0, 178.0, 18)
    elev = np.random.default_rng(0).uniform(0, 2000, size=(lat.size, lon.size))
    dem = xr.DataArray(elev, coords={"lat": lat, "lon": lon}, dims=("lat", "lon"))

    monkeypatch.setattr(maps, "FIG", tmp_path)
    monkeypatch.setattr(maps, "load_dem_grid", lambda *a, **k: dem)
    monkeypatch.setattr(maps, "_grid_ref", lambda: None)  # skip the ERA5-grid panel

    maps.map_terrain_grid(samp=None)
    assert (tmp_path / "terrain_grid.png").exists()
    assert (tmp_path / "terrain_grid.png").stat().st_size > 0
