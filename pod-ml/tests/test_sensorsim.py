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
