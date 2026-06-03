"""Sensor-sim layer — degrade clean ERA5 signals into what the pod's BME280 would actually feed the model.

Turns the optimistic clean-reanalysis features into a realistic sensor view, so the skill probe can report
the DEPLOYABLE number, not the lab ceiling. The magnitudes here are provisional GUESSES (documented as such);
the field-validation loop (planned `validate_log.py`) will replace them with values MEASURED from the real
pod on its pack.

Physics baked in (see docs/02 "Sensor trust split"):
- **Pressure:** a CONSTANT per-station offset (sensor bias). Applied to raw pressure it CANCELS in the
  tendencies (subtraction) and persists only in absolute level — which is precisely why tendencies are the
  high-trust backbone. Plus tiny per-reading noise (averaging already crushes it).
- **Temperature:** a CONSTANT one-sided WARM bias (body/pack/solar only warms, never cools) → cancels in the
  temp trend, shifts only absolute temp. Plus small per-reading noise.
- **Humidity:** wider bidirectional per-reading noise (siting; the BME280 RH element also drifts/saturates
  near 100 %). This is the channel that hurts most, since `rh` is the top clean-data feature.
- **Quantization** to the pod's logged resolution.

Out of scope here: altitude-induced pressure error is a MOVING-hiker problem; at the fixed probe points it
doesn't apply. It re-enters at deployment and is handled by gating inference on 'stationary'.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class SensorSimParams:
    pressure_offset_hpa: float = 0.8   # constant sensor bias (±1 hPa spec) — cancels in tendencies
    pressure_noise_hpa: float = 0.03   # per-reading noise (BME280 ~0.01–0.03 hPa; near-negligible)
    temp_warm_bias_c: float = 1.5      # constant one-sided warm bias (never cools) — cancels in temp trend
    temp_noise_c: float = 0.3          # per-reading noise
    humidity_noise_pct: float = 5.0    # bidirectional siting/sensor noise (BME280 RH ±3 % + siting)
    quantize: bool = True              # round to the pod's logged resolution


def degrade_signals(signals: dict, params: SensorSimParams, rng: np.random.Generator) -> dict:
    """Return sensor-degraded copies of the raw signals (pressure/temp/humidity)."""
    sp = signals["sp_hPa"].astype("float64").copy()
    t = signals["t2m_C"].astype("float64").copy()
    rh = signals["rh"].astype("float64").copy()
    n = sp.size

    # Pressure: constant bias (cancels in tendencies) + tiny per-reading noise.
    sp += params.pressure_offset_hpa + rng.normal(0.0, params.pressure_noise_hpa, n)
    # Temperature: constant warm bias (cancels in trend) + per-reading noise.
    t += params.temp_warm_bias_c + rng.normal(0.0, params.temp_noise_c, n)
    # Humidity: bidirectional per-reading noise, clipped to the physical range.
    rh = np.clip(rh + rng.normal(0.0, params.humidity_noise_pct, n), 0.0, 100.0)

    if params.quantize:
        sp = np.round(sp, 1)   # 0.1 hPa
        t = np.round(t, 1)     # 0.1 °C
        rh = np.round(rh)      # 1 % (pod logs integer humidity)

    return {"time": signals["time"], "sp_hPa": sp, "t2m_C": t, "rh": rh}
