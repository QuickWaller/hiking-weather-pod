"""Unit tests for feature engineering — the math the pod must reproduce bit-for-bit."""

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from podml.features import FEATURE_COLUMNS, build_features, rh_from_t_td, trailing_slope


# ---- trailing_slope: the clever bit, so prove it against hand truth ----

def test_slope_constant_is_zero():
    out = trailing_slope(np.full(10, 5.0), 4)
    assert np.allclose(out[3:], 0.0)


def test_slope_linear_is_exact():
    # y rises 2 per hourly step → OLS slope must be exactly 2.0/hr after warmup
    out = trailing_slope(2.0 * np.arange(10), 4)
    assert np.allclose(out[3:], 2.0)


def test_slope_warmup_is_nan():
    out = trailing_slope(np.arange(10.0), 4)
    assert np.all(np.isnan(out[:3]))
    assert not np.any(np.isnan(out[3:]))


def test_slope_sign_is_negative_for_falling_pressure():
    out = trailing_slope(np.array([1010.0, 1009.0, 1007.0, 1004.0, 1000.0]), 4)
    assert out[-1] < 0


def test_slope_6h_window_uses_7_points():
    out = trailing_slope(np.arange(20.0), 7)  # 6h window = 7 hourly samples
    assert np.all(np.isnan(out[:6]))
    assert np.allclose(out[6:], 1.0)


# ---- rh_from_t_td ----

def test_rh_saturation_is_100():
    assert rh_from_t_td(np.array([288.15]), np.array([288.15]))[0] == pytest.approx(100.0)


def test_rh_known_value():
    # t=20°C, td=10°C → ~52.5%
    assert rh_from_t_td(np.array([293.15]), np.array([283.15]))[0] == pytest.approx(52.5, abs=1.0)


def test_rh_is_clipped_0_100():
    rh = rh_from_t_td(np.array([300.0, 250.0]), np.array([250.0, 300.0]))
    assert np.all((rh >= 0) & (rh <= 100))


# ---- build_features: schema + parity guards ----

def _toy_dataset(n=12):
    t = pd.date_range("2020-06-01", periods=n, freq="h")
    return xr.Dataset(
        {
            "sp": ("valid_time", np.full(n, 100000.0)),  # Pa
            "t2m": ("valid_time", np.full(n, 283.15)),   # 10 °C
            "d2m": ("valid_time", np.full(n, 278.15)),   # 5 °C
            "u10": ("valid_time", np.full(n, 3.0)),      # present, must be IGNORED
            "v10": ("valid_time", np.full(n, -2.0)),
        },
        coords={"valid_time": t},
    )


def test_features_schema_matches_contract():
    assert list(build_features(_toy_dataset()).columns) == FEATURE_COLUMNS


def test_features_exclude_wind_for_parity():
    # The pod has NO wind sensor — wind must never become a feature.
    cols = build_features(_toy_dataset()).columns
    assert not any(("u10" in c) or ("v10" in c) or ("wind" in c.lower()) for c in cols)


def test_features_unit_conversions():
    df = build_features(_toy_dataset())
    assert df["sp_hPa"].iloc[0] == pytest.approx(1000.0)  # 100000 Pa → 1000 hPa
    assert df["t2m_C"].iloc[0] == pytest.approx(10.0)     # 283.15 K → 10 °C


def test_features_temporal_columns():
    df = build_features(_toy_dataset())
    assert (df["month"] == 6).all()
    assert df["hour_utc"].iloc[0] == 0


def test_long_pressure_trend_is_exact():
    # pressure rising 100 Pa/hr == 1 hPa/hr → 24h slope must be exactly 1.0 hPa/hr after warmup
    n = 30
    t = pd.date_range("2020-06-01", periods=n, freq="h")
    ds = xr.Dataset(
        {
            "sp": ("valid_time", 100000.0 + 100.0 * np.arange(n)),
            "t2m": ("valid_time", np.full(n, 283.15)),
            "d2m": ("valid_time", np.full(n, 278.15)),
        },
        coords={"valid_time": t},
    )
    df = build_features(ds)
    assert df["sp_rate_24h"].iloc[25] == pytest.approx(1.0, abs=1e-6)
    assert np.isnan(df["sp_rate_24h"].iloc[23])  # warmup: needs 25 points
