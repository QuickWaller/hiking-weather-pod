"""Unit tests for the sensor-sim layer."""

import numpy as np
import pandas as pd

from podml.features import trailing_slope
from podml.sensorsim import SensorSimParams, degrade_signals


def _signals(n=30):
    return {
        "time": pd.date_range("2020-06-01", periods=n, freq="h"),
        "sp_hPa": 1000.0 + 0.5 * np.arange(n),  # rising 0.5 hPa/hr
        "t2m_C": np.full(n, 10.0),
        "rh": np.full(n, 60.0),
    }


def _noiseless():
    return SensorSimParams(pressure_noise_hpa=0, temp_noise_c=0, humidity_noise_pct=0, quantize=False)


def test_pressure_offset_cancels_in_tendency_but_shifts_level():
    d = degrade_signals(_signals(), _noiseless(), np.random.default_rng(0))
    clean = _signals()["sp_hPa"]
    # Constant offset → tendency unchanged...
    assert np.allclose(trailing_slope(clean, 4)[3:], trailing_slope(d["sp_hPa"], 4)[3:])
    # ...but absolute level is shifted by exactly the offset.
    assert np.allclose(d["sp_hPa"] - clean, 0.8)


def test_temp_bias_is_warm_only_and_cancels_in_trend():
    d = degrade_signals(_signals(), _noiseless(), np.random.default_rng(0))
    assert np.allclose(d["t2m_C"] - 10.0, 1.5)               # constant warm shift, never cools
    assert np.allclose(trailing_slope(d["t2m_C"], 4)[3:], 0.0)  # cancels in trend


def test_humidity_clipped_to_physical_range():
    d = degrade_signals(_signals(), SensorSimParams(humidity_noise_pct=80), np.random.default_rng(1))
    assert np.all((d["rh"] >= 0) & (d["rh"] <= 100))


def test_quantization_to_pod_resolution():
    d = degrade_signals(_signals(), SensorSimParams(), np.random.default_rng(2))
    assert np.allclose(d["rh"], np.round(d["rh"]))           # integer humidity
    assert np.allclose(d["sp_hPa"], np.round(d["sp_hPa"], 1))  # 0.1 hPa


def test_deterministic_with_seed():
    a = degrade_signals(_signals(), SensorSimParams(), np.random.default_rng(7))
    b = degrade_signals(_signals(), SensorSimParams(), np.random.default_rng(7))
    assert np.array_equal(a["sp_hPa"], b["sp_hPa"]) and np.array_equal(a["rh"], b["rh"])


def test_different_seeds_give_different_noise():
    """Different seeds produce different degradation."""
    a = degrade_signals(_signals(), SensorSimParams(), np.random.default_rng(123))
    b = degrade_signals(_signals(), SensorSimParams(), np.random.default_rng(456))
    assert not np.allclose(a["sp_hPa"], b["sp_hPa"])


def test_nan_preserved_in_pressure():
    """NaN values in input are preserved in output."""
    signals = _signals()
    signals["sp_hPa"][5] = np.nan
    d = degrade_signals(signals, _noiseless(), np.random.default_rng(0))
    assert np.isnan(d["sp_hPa"][5])
    # But other values should be degraded
    assert not np.isclose(d["sp_hPa"][4], signals["sp_hPa"][4])


def test_nan_preserved_in_temperature():
    """NaN values in temperature are preserved."""
    signals = _signals()
    signals["t2m_C"][10] = np.nan
    d = degrade_signals(signals, _noiseless(), np.random.default_rng(0))
    assert np.isnan(d["t2m_C"][10])


def test_nan_preserved_in_humidity():
    """NaN values in humidity are preserved."""
    signals = _signals()
    signals["rh"][15] = np.nan
    d = degrade_signals(signals, _noiseless(), np.random.default_rng(0))
    assert np.isnan(d["rh"][15])


def test_large_noise_creates_variance():
    """Large noise parameters produce high variance."""
    signals = _signals(n=100)
    params_small = SensorSimParams(pressure_noise_hpa=0.1)
    params_large = SensorSimParams(pressure_noise_hpa=2.0)

    d_small = degrade_signals(signals, params_small, np.random.default_rng(42))
    d_large = degrade_signals(signals, params_large, np.random.default_rng(42))

    var_small = np.nanvar(d_small["sp_hPa"] - signals["sp_hPa"])
    var_large = np.nanvar(d_large["sp_hPa"] - signals["sp_hPa"])
    assert var_large > var_small


def test_all_nan_signal_stays_all_nan():
    """If input is all NaN, output stays all NaN."""
    signals = _signals()
    signals["sp_hPa"] = np.full_like(signals["sp_hPa"], np.nan)
    d = degrade_signals(signals, SensorSimParams(), np.random.default_rng(0))
    assert np.all(np.isnan(d["sp_hPa"]))
