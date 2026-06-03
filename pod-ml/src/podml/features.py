"""Step 3 — engineered feature vector from the ERA5-Land hourly series.

PARITY CONSTRAINT (non-negotiable): a feature may only use what the POD can sense on-device —
pressure, temperature, humidity (BME280) and time (RTC). The pod has **no wind sensor**, so
`u10`/`v10` are NEVER features (they are label-side only, for the storm-wind threshold). Using a
variable the pod can't reproduce would be training-serving skew by construction.

These definitions are the SPEC the eventual C++ pod code must reproduce bit-for-bit (golden-vector
parity). Estimators are chosen to be reproducible on the pod's ring buffer:
  - pressure/temp/humidity tendencies = least-squares slope over a trailing window (noise-robust,
    and the absolute offset cancels — see docs/02 "Sensor trust split").

For v1 we compute DYNAMIC features per point (the point-based skill probe). Static/zone features
(CHELSA precip, elevation, coast distance) come with the zoning work in v2.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# Pressure-tendency ladder (hours). Pressure is the HIGH-trust backbone, so we give it long memory:
# 3-6h catches the imminent front; 24-72h captures the slower synoptic evolution (NZ systems persist
# 1-3 days) that short trends miss — added after the rehearsal showed skill fading at 24-48h. A week
# (168h) is one entry away if importance says it helps; beyond ~3 days `month` already covers the scale.
PRESSURE_TREND_HOURS = [3, 6, 12, 24, 48, 72]

# Shape features (range/chunk-deltas) were tested and DROPPED — no BSS or precision gain on rain or
# wind; the slope ladder already captured the recent shape. See docs/04-results.md.

# The pod-replicable feature vector (order is the contract — bump a version if it changes).
FEATURE_COLUMNS = (
    ["sp_hPa"]                                          # absolute level (LOW trust: sensor + altitude bias)
    + [f"sp_rate_{h}h" for h in PRESSURE_TREND_HOURS]   # pressure tendencies, hPa/hr (HIGH trust backbone)
    + ["rh", "rh_trend_3h",                             # humidity now + 3h trend (LOW trust: siting)
       "t2m_C", "t2m_trend_3h",                         # temperature now + 3h trend (LOW trust: siting)
       "month", "hour_utc"]                             # RTC: season + time of day
)


def rh_from_t_td(t2m_k: np.ndarray, d2m_k: np.ndarray) -> np.ndarray:
    """Relative humidity (%) from 2m temperature and dewpoint (Kelvin), Magnus/Tetens formula."""
    t = np.asarray(t2m_k, dtype="float64") - 273.15
    td = np.asarray(d2m_k, dtype="float64") - 273.15
    a, b = 17.625, 243.04  # Alduchov & Eskridge coefficients
    rh = 100.0 * np.exp(a * td / (b + td)) / np.exp(a * t / (b + t))
    return np.clip(rh, 0.0, 100.0)


def trailing_slope(y: np.ndarray, n: int) -> np.ndarray:
    """Least-squares slope per hour over the trailing `n` hourly samples.

    slope[t] = OLS slope of y[t-n+1 .. t] vs. x = 0..n-1 (hours). NaN for the first n-1 samples.
    Vectorised as a fixed linear filter — the same arithmetic the pod can run on its ring buffer.
    """
    y = np.asarray(y, dtype="float64")
    x = np.arange(n, dtype="float64")
    xc = x - x.mean()
    weights = (xc / (xc**2).sum())[::-1]  # reversed → np.convolve does cross-correlation
    out = np.full(y.shape, np.nan)
    if y.size >= n:
        out[n - 1:] = np.convolve(y, weights, mode="valid")
    return out


def raw_signals(ds) -> dict:
    """The pod-sensed raw signals, before feature-building.

    The sensor-sim layer degrades THESE (pressure/temp/humidity as the BME280 reads them) so that a
    constant pressure offset correctly cancels in the tendencies and persists only in absolute level.
    """
    return {
        "time": pd.to_datetime(ds["valid_time"].values),
        "sp_hPa": ds["sp"].values.astype("float64") / 100.0,    # Pa → hPa
        "t2m_C": ds["t2m"].values.astype("float64") - 273.15,   # K → °C
        "rh": rh_from_t_td(ds["t2m"].values, ds["d2m"].values),
    }


def build_features_from_signals(signals: dict) -> pd.DataFrame:
    """Build the feature vector from (possibly sensor-degraded) raw signals."""
    sp_hpa, t2m_c, rh = signals["sp_hPa"], signals["t2m_C"], signals["rh"]
    df = pd.DataFrame(index=signals["time"])
    df.index.name = "valid_time"
    df["sp_hPa"] = sp_hpa
    for h in PRESSURE_TREND_HOURS:
        df[f"sp_rate_{h}h"] = trailing_slope(sp_hpa, h + 1)  # h-hour span = h+1 hourly points
    df["rh"] = rh
    df["rh_trend_3h"] = trailing_slope(rh, 4)
    df["t2m_C"] = t2m_c
    df["t2m_trend_3h"] = trailing_slope(t2m_c, 4)
    df["month"] = df.index.month
    df["hour_utc"] = df.index.hour
    return df[FEATURE_COLUMNS]


def build_features(ds) -> pd.DataFrame:
    """Clean features straight from ERA5 (no sensor-sim)."""
    return build_features_from_signals(raw_signals(ds))


if __name__ == "__main__":
    import argparse

    from podml.config import DATA_RAW, load_config
    from podml.dataio import load_timeseries

    ap = argparse.ArgumentParser()
    ap.add_argument("--point", default=None, help="probe point name (default: verification_point)")
    args = ap.parse_args()

    cfg = load_config()
    name = args.point or cfg.get("verification_point") or next(iter(cfg["probe_points"]))
    t = cfg["time"]
    tag = f"{t['acquisition_start']}_{t['test_year']}-12-31"
    path = DATA_RAW / f"era5land_ts_{name}_{tag}.nc"

    print(f"Building features for {name} from {path.name}")
    feats = build_features(load_timeseries(path))
    print(f"\nShape: {feats.shape}")
    print(f"\n{feats.describe().round(3).T}")
    print("\nFirst rows with full history (after 6h warmup):")
    print(feats.iloc[6:9].round(3))
