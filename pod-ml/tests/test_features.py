"""Unit tests for feature engineering — the math the pod must reproduce bit-for-bit."""

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from podml.features import (
    FEATURE_COLUMNS, build_features, rh_from_t_td, td_from_t_rh, trailing_slope,
)


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
    # month=6 → sin=sin(2π*6/12)=0, cos=cos(2π*6/12)=-1
    assert df["month_sin"].iloc[0] == pytest.approx(0.0, abs=1e-9)
    assert df["month_cos"].iloc[0] == pytest.approx(-1.0, abs=1e-9)
    # hour 0 → sin=0, cos=1
    assert df["hour_sin"].iloc[0] == pytest.approx(0.0, abs=1e-9)
    assert df["hour_cos"].iloc[0] == pytest.approx(1.0, abs=1e-9)


def test_month_not_in_feature_columns():
    """Raw month is replaced by cyclic pair — must not appear in contract."""
    assert "month" not in FEATURE_COLUMNS


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


# ---- Additional edge cases ----

def test_slope_nan_propagates():
    """NaN in signal leads to NaN in trends."""
    y = np.array([1.0, 2.0, np.nan, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
    slope = trailing_slope(y, 4)
    # Window including the NaN should produce NaN
    assert np.isnan(slope[3])


def test_rh_extreme_dewpoint_drop():
    """Large dew point drop leads to low RH."""
    rh = rh_from_t_td(np.array([293.15]), np.array([273.15]))  # 20°C drop
    assert rh[0] < 30.0


def test_rh_small_dewpoint_drop():
    """Small dew point drop leads to high RH."""
    rh = rh_from_t_td(np.array([293.15]), np.array([291.15]))  # 2°C drop
    assert rh[0] > 80.0


def test_rh_vectorized():
    """Handle arrays of different temperatures."""
    t_k = np.array([283.15, 293.15, 303.15])
    td_k = np.array([273.15, 283.15, 293.15])
    rh = rh_from_t_td(t_k, td_k)
    assert len(rh) == 3
    assert np.all((rh >= 0) & (rh <= 100))


def test_pressure_falling_trend_negative():
    """Falling pressure produces negative trend."""
    y = np.linspace(1010, 990, 10)  # monotonic decrease
    slope = trailing_slope(y, 5)
    assert slope[-1] < 0


def test_pressure_rising_trend_positive():
    """Rising pressure produces positive trend."""
    y = np.linspace(990, 1010, 10)  # monotonic increase
    slope = trailing_slope(y, 5)
    assert slope[-1] > 0


def test_index_name_is_valid_time():
    """Output index is named 'valid_time'."""
    df = build_features(_toy_dataset())
    assert df.index.name == "valid_time"


# ---- td_from_t_rh (Magnus inverse) ----

def test_td_saturation_returns_t():
    """At RH=100% the dewpoint equals the air temperature."""
    t = np.array([15.0, 0.0, -5.0])
    td = td_from_t_rh(t, np.full(3, 100.0))
    assert np.allclose(td, t, atol=0.01)


def test_td_round_trip():
    """td_from_t_rh is the exact inverse of rh_from_t_td (within floating-point tolerance)."""
    t_k = np.array([288.15, 293.15, 278.15])   # 15, 20, 5 °C
    td_k = np.array([283.15, 285.15, 273.15])   # 10, 12, 0 °C
    rh = rh_from_t_td(t_k, td_k)
    t_c = t_k - 273.15
    td_c = td_k - 273.15
    recovered = td_from_t_rh(t_c, rh)
    assert np.allclose(recovered, td_c, atol=0.01)


def test_td_dry_air_below_t():
    """Dewpoint must be ≤ air temperature for any RH < 100%."""
    t = np.array([20.0, 10.0, 0.0])
    rh = np.array([50.0, 70.0, 80.0])
    assert np.all(td_from_t_rh(t, rh) <= t)


# ---- dewpoint_dep golden vectors ----

def test_dewpoint_dep_in_feature_columns():
    assert "dewpoint_dep" in FEATURE_COLUMNS


def test_dewpoint_dep_zero_at_saturation():
    """At RH=100% T=Td so dewpoint_dep must be 0."""
    n = 12
    t = pd.date_range("2020-06-01", periods=n, freq="h")
    ds = xr.Dataset(
        {"sp": ("valid_time", np.full(n, 100000.0)),
         "t2m": ("valid_time", np.full(n, 283.15)),
         "d2m": ("valid_time", np.full(n, 283.15))},   # Td == T → saturated
        coords={"valid_time": t},
    )
    df = build_features(ds)
    assert np.allclose(df["dewpoint_dep"].dropna(), 0.0, atol=0.01)


def test_dewpoint_dep_positive_for_unsaturated():
    """Dewpoint depression must be > 0 when Td < T (air not saturated)."""
    df = build_features(_toy_dataset())   # d2m = 5°C, t2m = 10°C
    assert (df["dewpoint_dep"].dropna() > 0).all()


def test_dewpoint_dep_round_trip():
    """rh reconstructed from T and dewpoint_dep must match the input RH."""
    from podml.features import td_from_t_rh as _td
    t_c = np.array([15.0, 20.0, 5.0])
    rh_in = np.array([60.0, 80.0, 90.0])
    td_c = _td(t_c, rh_in)
    dep = t_c - td_c
    # reconstruct: Td = T - dep, then back to RH (in Kelvin)
    rh_out = rh_from_t_td(t_c + 273.15, (t_c - dep) + 273.15)
    assert np.allclose(rh_out, rh_in, atol=0.1)


# ---- cyclic hour golden vectors ----

def test_hour_sin_cos_in_feature_columns():
    assert "hour_sin" in FEATURE_COLUMNS
    assert "hour_cos" in FEATURE_COLUMNS


def test_hour_utc_not_in_feature_columns():
    """Raw hour_utc is replaced by cyclic pair — must not appear in contract."""
    assert "hour_utc" not in FEATURE_COLUMNS


def test_cyclic_hour_known_values():
    """Spot-check known cyclic values: h=0→(0,1), h=6→(1,0), h=12→(0,-1), h=18→(-1,0)."""
    n = 25
    t = pd.date_range("2020-06-01 00:00", periods=n, freq="h")
    ds = xr.Dataset(
        {"sp": ("valid_time", np.full(n, 100000.0)),
         "t2m": ("valid_time", np.full(n, 283.15)),
         "d2m": ("valid_time", np.full(n, 278.15))},
        coords={"valid_time": t},
    )
    df = build_features(ds)
    assert df["hour_sin"].iloc[0] == pytest.approx(0.0, abs=1e-9)   # h=0
    assert df["hour_cos"].iloc[0] == pytest.approx(1.0, abs=1e-9)
    assert df["hour_sin"].iloc[6] == pytest.approx(1.0, abs=1e-9)   # h=6
    assert df["hour_cos"].iloc[6] == pytest.approx(0.0, abs=1e-6)
    assert df["hour_sin"].iloc[12] == pytest.approx(0.0, abs=1e-9)  # h=12
    assert df["hour_cos"].iloc[12] == pytest.approx(-1.0, abs=1e-9)


def test_cyclic_hour_unit_circle():
    """sin²+cos² must equal 1 for every row."""
    df = build_features(_toy_dataset())
    r2 = df["hour_sin"] ** 2 + df["hour_cos"] ** 2
    assert np.allclose(r2, 1.0, atol=1e-12)


# ---- cyclic month golden vectors ----

def test_month_sin_cos_in_feature_columns():
    assert "month_sin" in FEATURE_COLUMNS
    assert "month_cos" in FEATURE_COLUMNS


def test_cyclic_month_unit_circle():
    """sin²+cos² must equal 1 for every row."""
    df = build_features(_toy_dataset())
    r2 = df["month_sin"] ** 2 + df["month_cos"] ** 2
    assert np.allclose(r2, 1.0, atol=1e-12)


def test_cyclic_month_known_values():
    """month=3 → sin=1, cos=0; month=9 → sin=-1, cos=0."""
    n = 12
    for mo, exp_sin, exp_cos in [(3, 1.0, 0.0), (9, -1.0, 0.0), (6, 0.0, -1.0), (12, 0.0, 1.0)]:
        t = pd.date_range(f"2020-{mo:02d}-01", periods=n, freq="h")
        ds = xr.Dataset(
            {"sp": ("valid_time", np.full(n, 100000.0)),
             "t2m": ("valid_time", np.full(n, 283.15)),
             "d2m": ("valid_time", np.full(n, 278.15))},
            coords={"valid_time": t},
        )
        df = build_features(ds)
        assert df["month_sin"].iloc[0] == pytest.approx(exp_sin, abs=1e-9), f"month={mo} sin"
        assert df["month_cos"].iloc[0] == pytest.approx(exp_cos, abs=1e-9), f"month={mo} cos"


# ---- sp_accel features ----

def test_sp_accel_features_in_feature_columns():
    assert "sp_accel_nested" in FEATURE_COLUMNS
    assert "sp_accel_disjoint" in FEATURE_COLUMNS


def _toy_dataset_long(n=20):
    """Longer dataset (20h) for features that need extended warmup."""
    t = pd.date_range("2020-06-01", periods=n, freq="h")
    return xr.Dataset(
        {
            "sp": ("valid_time", np.full(n, 100000.0)),
            "t2m": ("valid_time", np.full(n, 283.15)),
            "d2m": ("valid_time", np.full(n, 278.15)),
        },
        coords={"valid_time": t},
    )


def test_sp_accel_nested_constant_pressure_is_zero():
    """Constant pressure → all sp_rate_* = 0 → sp_accel_nested = 0."""
    df = build_features(_toy_dataset_long())
    assert np.allclose(df["sp_accel_nested"].dropna(), 0.0, atol=1e-10)


def test_sp_accel_disjoint_constant_pressure_is_zero():
    """Constant pressure → all slopes equal → sp_accel_disjoint = 0 after warmup."""
    df = build_features(_toy_dataset_long())
    # Needs 7 points for 3h slope warmup + 3 steps of lag = 10 points total
    valid = df["sp_accel_disjoint"].iloc[9:]
    assert np.allclose(valid.dropna(), 0.0, atol=1e-10)


def test_sp_accel_nested_linear_pressure_is_zero():
    """Linearly rising pressure → sp_rate_3h == sp_rate_6h (same slope) → nested accel = 0."""
    n = 20
    t = pd.date_range("2020-06-01", periods=n, freq="h")
    ds = xr.Dataset(
        {"sp": ("valid_time", 100000.0 + 100.0 * np.arange(n)),  # 1 hPa/hr linear rise
         "t2m": ("valid_time", np.full(n, 283.15)),
         "d2m": ("valid_time", np.full(n, 278.15))},
        coords={"valid_time": t},
    )
    df = build_features(ds)
    assert np.allclose(df["sp_accel_nested"].dropna(), 0.0, atol=1e-6)


# ---- td_trend features ----

def test_td_trend_features_in_feature_columns():
    assert "td_trend_3h" in FEATURE_COLUMNS
    assert "td_trend_6h" in FEATURE_COLUMNS


def test_t2m_trend_6h_in_feature_columns():
    assert "t2m_trend_6h" in FEATURE_COLUMNS


def test_td_trends_constant_humidity_is_zero():
    """Constant T and RH → Td constant → both td trends = 0 after warmup."""
    df = build_features(_toy_dataset_long())
    assert np.allclose(df["td_trend_3h"].dropna(), 0.0, atol=1e-10)
    assert np.allclose(df["td_trend_6h"].dropna(), 0.0, atol=1e-10)


def test_t2m_trend_6h_constant_is_zero():
    """Constant temperature → t2m_trend_6h = 0 after warmup."""
    df = build_features(_toy_dataset_long())
    assert np.allclose(df["t2m_trend_6h"].dropna(), 0.0, atol=1e-10)


def test_td_trend_6h_rising_humidity_is_positive():
    """Rising RH at constant T → Td rises → td_trend_6h > 0."""
    n = 20
    t = pd.date_range("2020-06-01", periods=n, freq="h")
    # RH rises from 50% to ~90% over 20h at constant T=10°C
    rh_vals = np.linspace(50.0, 90.0, n)
    # convert RH to d2m (in K) for xarray
    t_c = 10.0
    td_c = td_from_t_rh(np.full(n, t_c), rh_vals)
    d2m_k = td_c + 273.15
    ds = xr.Dataset(
        {"sp": ("valid_time", np.full(n, 100000.0)),
         "t2m": ("valid_time", np.full(n, t_c + 273.15)),
         "d2m": ("valid_time", d2m_k)},
        coords={"valid_time": t},
    )
    df = build_features(ds)
    assert df["td_trend_6h"].dropna().iloc[-1] > 0
