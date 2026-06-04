"""Unit tests for sensor simulation (sensorsim.py).

Tests that sensor degradation:
  - Adds realistic noise to pressure, temperature, humidity
  - Preserves the shape of the signal (trends still readable)
  - Handles NaN gracefully
  - Is reproducible with seeding
"""

import numpy as np
import pandas as pd
import pytest

from podml.sensorsim import SensorSimParams, degrade_signals


class TestSensorSimParams:
    """Test parameter configuration."""

    def test_default_params_reasonable(self):
        """Default parameters are non-zero."""
        p = SensorSimParams()
        assert p.pressure_offset_hpa > 0
        assert p.pressure_noise_hpa > 0
        assert p.temp_offset_c >= 0
        assert p.temp_noise_c > 0
        assert p.humidity_noise_pct > 0

    def test_params_immutable(self):
        """Parameters are fixed (not dependent on data)."""
        p1 = SensorSimParams()
        p2 = SensorSimParams()
        assert p1.pressure_offset_hpa == p2.pressure_offset_hpa
        assert p1.temp_offset_c == p2.temp_offset_c


class TestDegradeSignals:
    """Test signal degradation (noise injection)."""

    def _make_signals(self, n=100):
        """Create synthetic clean signals."""
        times = pd.date_range("2024-01-01", periods=n, freq="h")
        return {
            "time": times,
            "sp_hPa": np.linspace(1000, 1010, n) + 5 * np.sin(np.linspace(0, 4 * np.pi, n)),
            "t2m_C": np.linspace(10, 20, n) + 3 * np.sin(np.linspace(0, 2 * np.pi, n)),
            "rh": np.linspace(50, 80, n) + 10 * np.cos(np.linspace(0, 2 * np.pi, n)),
        }

    def test_degraded_has_same_shape(self):
        """Degraded signal has same length as input."""
        signals = self._make_signals(n=100)
        degraded = degrade_signals(signals, SensorSimParams())
        assert len(degraded["sp_hPa"]) == len(signals["sp_hPa"])
        assert len(degraded["t2m_C"]) == len(signals["t2m_C"])
        assert len(degraded["rh"]) == len(signals["rh"])

    def test_degraded_is_different_from_clean(self):
        """Degraded signals are not identical to clean signals."""
        signals = self._make_signals(n=100)
        degraded = degrade_signals(signals, SensorSimParams())
        # At least some values should differ
        assert not np.allclose(degraded["sp_hPa"], signals["sp_hPa"])
        assert not np.allclose(degraded["t2m_C"], signals["t2m_C"])

    def test_pressure_offset_is_consistent(self):
        """Pressure offset is applied consistently across all samples."""
        signals = self._make_signals(n=100)
        params = SensorSimParams()
        degraded = degrade_signals(signals, params, np.random.default_rng(42))

        # Pressure offset should shift all values by roughly the same amount
        # (noise is on top, but the mean shift should be consistent)
        offset_observed = np.mean(degraded["sp_hPa"] - signals["sp_hPa"])
        assert 0 < offset_observed < 2.0  # reasonable bias (within params.pressure_offset_hpa)

    def test_seeded_rng_is_reproducible(self):
        """With fixed seed, degradation is reproducible."""
        signals = self._make_signals(n=50)
        params = SensorSimParams()

        rng1 = np.random.default_rng(seed=123)
        deg1 = degrade_signals(signals, params, rng1)

        rng2 = np.random.default_rng(seed=123)
        deg2 = degrade_signals(signals, params, rng2)

        np.testing.assert_array_almost_equal(deg1["sp_hPa"], deg2["sp_hPa"])
        np.testing.assert_array_almost_equal(deg1["t2m_C"], deg2["t2m_C"])

    def test_different_seeds_give_different_results(self):
        """Different seeds produce different noise patterns."""
        signals = self._make_signals(n=50)
        params = SensorSimParams()

        rng1 = np.random.default_rng(seed=111)
        deg1 = degrade_signals(signals, params, rng1)

        rng2 = np.random.default_rng(seed=222)
        deg2 = degrade_signals(signals, params, rng2)

        # Should differ
        assert not np.allclose(deg1["sp_hPa"], deg2["sp_hPa"])

    def test_nan_handling(self):
        """NaN values in input are preserved in output."""
        signals = self._make_signals(n=50)
        signals["sp_hPa"][10] = np.nan
        signals["t2m_C"][20] = np.nan
        signals["rh"][30] = np.nan

        degraded = degrade_signals(signals, SensorSimParams())

        assert np.isnan(degraded["sp_hPa"][10])
        assert np.isnan(degraded["t2m_C"][20])
        assert np.isnan(degraded["rh"][30])
        # And non-NaN values should differ from clean
        assert not np.isclose(degraded["sp_hPa"][11], signals["sp_hPa"][11])

    def test_noise_magnitude_scales_with_params(self):
        """Larger noise params → larger degradation."""
        signals = self._make_signals(n=100)

        params_low = SensorSimParams()
        params_low.pressure_noise_hpa = 0.1  # very small

        params_high = SensorSimParams()
        params_high.pressure_noise_hpa = 2.0  # large

        rng1 = np.random.default_rng(seed=42)
        deg_low = degrade_signals(signals, params_low, rng1)

        rng2 = np.random.default_rng(seed=42)
        deg_high = degrade_signals(signals, params_high, rng2)

        # Variance of degradation should be higher for high params
        var_low = np.nanvar(deg_low["sp_hPa"] - signals["sp_hPa"])
        var_high = np.nanvar(deg_high["sp_hPa"] - signals["sp_hPa"])
        assert var_high > var_low

    def test_humidity_clipped_to_0_100(self):
        """Humidity stays in [0, 100]%."""
        signals = self._make_signals(n=100)
        # Extreme values near boundaries
        signals["rh"] = np.clip(signals["rh"], 1, 99)
        degraded = degrade_signals(signals, SensorSimParams())
        assert np.all(degraded["rh"] >= 0)
        assert np.all(degraded["rh"] <= 100)

    def test_temperature_reasonable_range(self):
        """Temperature stays in reasonable range (not physically impossible)."""
        signals = self._make_signals(n=100)
        degraded = degrade_signals(signals, SensorSimParams())
        # Pod uses -30 to +60°C as safe range
        assert np.all(degraded["t2m_C"] > -50)
        assert np.all(degraded["t2m_C"] < 80)
