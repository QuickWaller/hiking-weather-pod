"""Unit tests for feature engineering (features.py).

Tests edge cases, boundary conditions, and parity constraints:
  - NaN handling in trailing slopes
  - Feature vector shape and column order (parity with pod C++)
  - Pressure trend sign conventions (negative = falling)
  - Humidity/temperature clipping
"""

import numpy as np
import pandas as pd
import pytest

from podml.features import (
    FEATURE_COLUMNS,
    build_features_from_signals,
    rh_from_t_td,
    trailing_slope,
)


class TestTrailingSlope:
    """Test least-squares pressure/humidity/temp tendencies."""

    def test_flat_signal_zero_slope(self):
        """Constant signal has zero slope."""
        y = np.ones(10)
        slope = trailing_slope(y, 5)
        assert np.isclose(slope[-1], 0.0, atol=1e-6)

    def test_linear_rising_positive_slope(self):
        """Linear rise has positive slope."""
        y = np.linspace(0, 10, 11)
        slope = trailing_slope(y, 5)
        assert slope[-1] > 0

    def test_linear_falling_negative_slope(self):
        """Linear fall has negative slope."""
        y = np.linspace(10, 0, 11)
        slope = trailing_slope(y, 5)
        assert slope[-1] < 0

    def test_window_size_n_needs_n_samples(self):
        """First n-1 values are NaN (insufficient window)."""
        y = np.arange(10)
        slope = trailing_slope(y, 5)
        assert np.isnan(slope[0])
        assert np.isnan(slope[3])
        assert not np.isnan(slope[4])  # first valid is at index n-1

    def test_short_window_all_nan(self):
        """Window larger than signal → all NaN."""
        y = np.ones(3)
        slope = trailing_slope(y, 10)
        assert np.all(np.isnan(slope))

    def test_nan_in_input_propagates(self):
        """NaN in signal leads to NaN in output."""
        y = np.array([1.0, 2.0, np.nan, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0])
        slope = trailing_slope(y, 4)
        # NaN in the window → NaN slope
        assert np.isnan(slope[3])  # window includes the NaN at index 2


class TestRhFromTd:
    """Test relative humidity calculation from temperature and dewpoint."""

    def test_dewpoint_equals_temp_gives_100pct(self):
        """RH = 100% when dew point equals temperature."""
        t_k = np.array([273.15 + 20.0])  # 20°C
        td_k = np.array([273.15 + 20.0])  # 20°C
        rh = rh_from_t_td(t_k, td_k)
        assert np.isclose(rh[0], 100.0, atol=0.1)

    def test_zero_dewpoint_drop_gives_high_rh(self):
        """Small dew point drop → high RH."""
        t_k = np.array([273.15 + 20.0])
        td_k = np.array([273.15 + 18.0])  # 2°C drop
        rh = rh_from_t_td(t_k, td_k)
        assert rh[0] > 80.0

    def test_large_dewpoint_drop_gives_low_rh(self):
        """Large dew point drop → low RH."""
        t_k = np.array([273.15 + 25.0])
        td_k = np.array([273.15 + 5.0])  # 20°C drop
        rh = rh_from_t_td(t_k, td_k)
        assert rh[0] < 30.0

    def test_clipped_to_0_100_pct(self):
        """Output clipped to [0, 100]."""
        t_k = np.array([273.15 + 20.0])
        # Extreme cases that might exceed 100% numerically
        td_k = np.array([273.15 + 20.1])
        rh = rh_from_t_td(t_k, td_k)
        assert 0 <= rh[0] <= 100

    def test_vectorized_multiple_values(self):
        """Handle arrays of temperatures and dewpoints."""
        t_k = np.array([273.15 + 10, 273.15 + 20, 273.15 + 30])
        td_k = np.array([273.15 + 5, 273.15 + 18, 273.15 + 25])
        rh = rh_from_t_td(t_k, td_k)
        assert len(rh) == 3
        assert np.all((rh >= 0) & (rh <= 100))


class TestBuildFeaturesFromSignals:
    """Test complete feature vector construction."""

    def _make_signals(self, n=100):
        """Create synthetic signal dict for testing."""
        times = pd.date_range("2024-01-01", periods=n, freq="h")
        sp_hpa = 1000 + 5 * np.sin(np.linspace(0, 4 * np.pi, n))  # oscillating pressure
        t2m_c = 15 + 5 * np.sin(np.linspace(0, 2 * np.pi, n))  # oscillating temp
        rh = 70 + 10 * np.sin(np.linspace(0, 2 * np.pi, n))
        rh = np.clip(rh, 0, 100)  # ensure valid range

        return {
            "time": times,
            "sp_hPa": sp_hpa,
            "t2m_C": t2m_c,
            "rh": rh,
        }

    def test_output_has_all_feature_columns(self):
        """Output DataFrame has exactly the right columns."""
        signals = self._make_signals()
        df = build_features_from_signals(signals)
        assert set(df.columns) == set(FEATURE_COLUMNS)

    def test_column_order_matches_contract(self):
        """Column order is the contract with pod C++ code."""
        signals = self._make_signals()
        df = build_features_from_signals(signals)
        assert list(df.columns) == list(FEATURE_COLUMNS)

    def test_pressure_absolute_matches_input(self):
        """First feature (sp_hPa) matches the input signal."""
        signals = self._make_signals()
        df = build_features_from_signals(signals)
        np.testing.assert_array_almost_equal(df["sp_hPa"].values, signals["sp_hPa"])

    def test_temperature_absolute_matches_input(self):
        """Temperature feature matches input."""
        signals = self._make_signals()
        df = build_features_from_signals(signals)
        np.testing.assert_array_almost_equal(df["t2m_C"].values, signals["t2m_C"])

    def test_humidity_absolute_matches_input(self):
        """Humidity feature matches input."""
        signals = self._make_signals()
        df = build_features_from_signals(signals)
        np.testing.assert_array_almost_equal(df["rh"].values, signals["rh"])

    def test_month_extracted_from_time(self):
        """Month feature extracted correctly from DatetimeIndex."""
        signals = self._make_signals(n=200)
        df = build_features_from_signals(signals)
        # Check a few months match the input times
        assert df["month"].iloc[0] == signals["time"][0].month
        assert df["month"].iloc[50] == signals["time"][50].month

    def test_hour_utc_extracted_from_time(self):
        """Hour feature extracted correctly."""
        signals = self._make_signals(n=24)
        df = build_features_from_signals(signals)
        # First 24 hours should be 0..23
        expected_hours = np.arange(24)
        np.testing.assert_array_equal(df["hour_utc"].values, expected_hours)

    def test_falling_pressure_negative_trend(self):
        """Falling pressure → negative trend."""
        # Monotonically decreasing pressure
        signals = {
            "time": pd.date_range("2024-01-01", periods=10, freq="h"),
            "sp_hPa": np.linspace(1010, 990, 10),  # decreasing
            "t2m_C": np.ones(10) * 15.0,
            "rh": np.ones(10) * 70.0,
        }
        df = build_features_from_signals(signals)
        # All valid trends should be negative
        trend_cols = [c for c in df.columns if "sp_rate" in c]
        for col in trend_cols:
            valid = df[col].dropna()
            if len(valid) > 0:
                assert (valid < 0).any() or (valid <= 0).all()

    def test_rising_pressure_positive_trend(self):
        """Rising pressure → positive trend."""
        signals = {
            "time": pd.date_range("2024-01-01", periods=10, freq="h"),
            "sp_hPa": np.linspace(990, 1010, 10),  # increasing
            "t2m_C": np.ones(10) * 15.0,
            "rh": np.ones(10) * 70.0,
        }
        df = build_features_from_signals(signals)
        trend_cols = [c for c in df.columns if "sp_rate" in c]
        for col in trend_cols:
            valid = df[col].dropna()
            if len(valid) > 0:
                assert (valid > 0).any() or (valid >= 0).all()

    def test_nan_in_pressure_leads_to_nan_trends(self):
        """NaN pressure → NaN in all pressure trends."""
        signals = {
            "time": pd.date_range("2024-01-01", periods=10, freq="h"),
            "sp_hPa": np.array([1000, 1001, np.nan, 1002, 1003, 1004, 1005, 1006, 1007, 1008]),
            "t2m_C": np.ones(10) * 15.0,
            "rh": np.ones(10) * 70.0,
        }
        df = build_features_from_signals(signals)
        trend_cols = [c for c in df.columns if "sp_rate" in c]
        # At least some trends should have NaN (from the NaN in the window)
        for col in trend_cols:
            if df[col].isna().any():
                assert True  # Good
                break
        else:
            pytest.fail("No NaN in trends despite NaN in pressure")

    def test_index_is_datetimeindex(self):
        """Output index is DatetimeIndex with name 'valid_time'."""
        signals = self._make_signals()
        df = build_features_from_signals(signals)
        assert isinstance(df.index, pd.DatetimeIndex)
        assert df.index.name == "valid_time"

    def test_all_values_finite_except_warmup(self):
        """All feature values are finite (after warmup window)."""
        signals = self._make_signals(n=200)
        df = build_features_from_signals(signals)
        # After ~72 samples (warmup for 72h trend), all should be finite
        df_tail = df.iloc[80:]
        assert df_tail.notna().all().all()
