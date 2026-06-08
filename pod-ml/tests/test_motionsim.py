"""Unit tests for podml.motionsim — Markov regimes, feasible backward paths, and the moving-pod signals."""

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from podml.features import trailing_slope
from podml.motionsim import (
    MotionSimParams,
    REGIMES,
    sample_path_backward,
    sample_regimes,
    signals_along_path,
    transition_matrix,
)
from podml.static_features import pressure_to_msl


def _synth_ds(n_time=80, n_lat=5, n_lon=5, seed=0):
    rng = np.random.default_rng(seed)
    times = pd.date_range("2020-01-01", periods=n_time, freq="h")
    sp = rng.uniform(95000.0, 102000.0, (n_time, n_lat, n_lon))   # Pa
    t2m = rng.uniform(275.0, 290.0, (n_time, n_lat, n_lon))        # K
    d2m = t2m - rng.uniform(1.0, 5.0, (n_time, n_lat, n_lon))
    lat = np.linspace(-46.0, -45.6, n_lat)
    lon = np.linspace(168.0, 168.4, n_lon)
    return xr.Dataset(
        {"sp": (("valid_time", "lat", "lon"), sp),
         "t2m": (("valid_time", "lat", "lon"), t2m),
         "d2m": (("valid_time", "lat", "lon"), d2m)},
        coords={"valid_time": times, "lat": lat, "lon": lon},
    )


# --- Markov chain -------------------------------------------------------------

def test_transition_matrix_rows_sum_to_one_and_diagonal_matches_run_length():
    p = MotionSimParams()
    P = transition_matrix(p)
    assert np.allclose(P.sum(axis=1), 1.0)
    for i, L in enumerate(p.run_hours):
        assert P[i, i] == pytest.approx(1.0 - 1.0 / L)
    assert np.all(P >= 0)


def test_sample_regimes_recovers_steady_state_and_run_length():
    p = MotionSimParams()
    seq = sample_regimes(200_000, p, np.random.default_rng(1))
    # empirical regime shares ≈ configured steady-state
    freq = np.bincount(seq, minlength=len(REGIMES)) / seq.size
    assert np.allclose(freq, p.steady, atol=0.03)
    # empirical mean run length ≈ configured run_hours (loose: stochastic)
    for r, L in enumerate(p.run_hours):
        is_r = seq == r
        n_runs = np.sum(is_r & np.r_[True, seq[1:] != seq[:-1]])
        mean_run = is_r.sum() / max(n_runs, 1)
        assert mean_run == pytest.approx(L, rel=0.2)


# --- Path generation ----------------------------------------------------------

def test_path_is_correct_length_and_forward_ordered_in_time():
    land = np.ones((5, 5), dtype=bool)
    path = sample_path_backward((60, 2, 2), 48, land, MotionSimParams(), np.random.default_rng(2))
    assert len(path.t) == 49
    assert np.all(np.diff(path.t) == 1)          # forward in time, hourly
    assert path.t[-1] == 60 and path.i[-1] == 2 and path.j[-1] == 2  # ends at endpoint


def test_path_stays_on_land_and_in_bounds():
    land = np.ones((6, 6), dtype=bool)
    land[0, :] = False  # an ocean row the path must avoid
    rng = np.random.default_rng(3)
    for _ in range(20):
        path = sample_path_backward((70, 3, 3), 60, land, MotionSimParams(), rng)
        assert land[path.i, path.j].all()
        assert path.i.min() >= 0 and path.i.max() < 6
        assert path.j.min() >= 0 and path.j.max() < 6


def test_zero_speed_stays_in_endpoint_cell():
    land = np.ones((5, 5), dtype=bool)
    p = MotionSimParams(max_speed_kmh=(0.0, 0.0, 0.0))  # no regime can move
    path = sample_path_backward((40, 1, 4), 30, land, p, np.random.default_rng(4))
    assert np.all(path.i == 1) and np.all(path.j == 4)


def test_path_raises_on_insufficient_history_or_ocean_endpoint():
    land = np.ones((5, 5), dtype=bool)
    with pytest.raises(ValueError):
        sample_path_backward((10, 2, 2), 48, land, MotionSimParams(), np.random.default_rng(5))
    land[2, 2] = False
    with pytest.raises(ValueError):
        sample_path_backward((60, 2, 2), 48, land, MotionSimParams(), np.random.default_rng(6))


# --- Signals along path -------------------------------------------------------

def test_signals_shape_and_keys():
    ds = _synth_ds()
    orog = np.full((5, 5), 500.0)
    land = np.ones((5, 5), dtype=bool)
    path = sample_path_backward((70, 2, 2), 48, land, MotionSimParams(), np.random.default_rng(7))
    sig = signals_along_path(path, ds, orog, MotionSimParams(), np.random.default_rng(7))
    assert set(sig) == {"time", "sp_hPa", "t2m_C", "rh"}
    assert all(len(sig[k]) == 49 for k in ("time", "sp_hPa", "t2m_C", "rh"))
    assert np.all((sig["rh"] >= 0) & (sig["rh"] <= 100))


def test_zero_gps_error_gives_exact_clean_mslp():
    ds = _synth_ds()
    orog = np.linspace(0, 1500, 25).reshape(5, 5)
    land = np.ones((5, 5), dtype=bool)
    p = MotionSimParams(gps_alt_err_std_m=0.0)
    path = sample_path_backward((70, 2, 2), 48, land, p, np.random.default_rng(8))
    sig = signals_along_path(path, ds, orog, p, np.random.default_rng(8))
    sp = ds["sp"].values[path.t, path.i, path.j] / 100.0
    t2m_c = ds["t2m"].values[path.t, path.i, path.j] - 273.15
    expected = pressure_to_msl(sp, orog[path.i, path.j], t2m_c)
    assert np.allclose(sig["sp_hPa"], expected)


def test_gps_error_perturbs_pressure_and_constant_part_cancels_in_tendency():
    """A stationary, constant-pressure cell: GPS error adds noise to level but tendency stays ~0."""
    ds = _synth_ds()
    # make one cell's pressure AND temperature perfectly constant (MSLP reduction depends on both)
    ds["sp"][:, 2, 2] = 100000.0
    ds["t2m"][:, 2, 2] = 285.0
    orog = np.full((5, 5), 800.0)
    land = np.ones((5, 5), dtype=bool)
    stay = MotionSimParams(max_speed_kmh=(0.0, 0.0, 0.0))
    path = sample_path_backward((70, 2, 2), 48, land, stay, np.random.default_rng(9))

    clean = signals_along_path(path, ds, orog, MotionSimParams(gps_alt_err_std_m=0.0),
                               np.random.default_rng(9))
    noisy = signals_along_path(path, ds, orog, MotionSimParams(gps_alt_err_std_m=15.0),
                               np.random.default_rng(9))
    assert np.allclose(clean["sp_hPa"], clean["sp_hPa"][0])         # clean level constant
    assert np.std(noisy["sp_hPa"]) > 0.0                            # error injects level noise
    # the noise is small per-fix jitter (~0.12 hPa/m × 15 m ≈ a couple hPa), not a trend
    assert np.abs(np.nanmean(trailing_slope(noisy["sp_hPa"], 4))) < 1.0
