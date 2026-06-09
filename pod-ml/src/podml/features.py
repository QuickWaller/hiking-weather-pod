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

from typing import Any

import numpy as np
import pandas as pd
import xarray as xr

# Pressure-tendency ladder (hours). Pressure is the HIGH-trust backbone, so we give it long memory:
# 3-6h catches the imminent front; 24-72h captures the slower synoptic evolution (NZ systems persist
# 1-3 days) that short trends miss — added after the rehearsal showed skill fading at 24-48h. A week
# (168h) is one entry away if importance says it helps; beyond ~3 days `month` already covers the scale.
PRESSURE_TREND_HOURS = [3, 6, 12, 24, 48, 72]

# Shape features (range/chunk-deltas) were tested and DROPPED — no BSS or precision gain on rain or
# wind; the slope ladder already captured the recent shape. See docs/04-results.md.

# Bump this when FEATURE_COLUMNS order or content changes so cached builds and firmware can signal
# their generation. v1 = original (... hour_utc); v2 = cyclic hour + dewpoint_dep;
# v3 = sp_accel + td_trend_6h + t2m_trend_6h + cyclic month (raw month removed).
FEATURE_VECTOR_VERSION = 3

# The pod-replicable feature vector (order is the contract — bump FEATURE_VECTOR_VERSION if it changes).
FEATURE_COLUMNS = (
    ["sp_hPa"]                                           # absolute level (LOW trust: sensor + altitude bias)
    + [f"sp_rate_{h}h" for h in PRESSURE_TREND_HOURS]   # pressure tendencies, hPa/hr (HIGH trust backbone)
    + ["sp_accel_nested",                                # sp_rate_3h − sp_rate_6h: WMO code-8 analog
       "sp_accel_disjoint",                              # slope[last 3h] − slope[3–6h ago]: pure 2nd deriv
       "rh", "rh_trend_3h",                              # humidity now + 3h trend (LOW trust: siting)
       "t2m_C", "t2m_trend_3h", "t2m_trend_6h",         # temperature (LOW trust); 6h = cold-front signal
       "dewpoint_dep",                                   # T − Td (°C): distance from saturation
       "td_trend_3h",                                    # Td 3h trend: alongside rh_trend_3h (CI decides)
       "td_trend_6h",                                    # Td 6h trend: diurnally-stable moisture advection
       "month_sin", "month_cos",                         # cyclic month (replaces raw month; no 12→1 wrap)
       "hour_sin", "hour_cos"]                           # cyclic RTC hour; replaces raw hour_utc
)


def rh_from_t_td(t2m_k: np.ndarray, d2m_k: np.ndarray) -> np.ndarray:
    """Relative humidity (%) from 2m temperature and dewpoint (Kelvin), Magnus/Tetens formula."""
    t = np.asarray(t2m_k, dtype="float64") - 273.15
    td = np.asarray(d2m_k, dtype="float64") - 273.15
    a, b = 17.625, 243.04  # Alduchov & Eskridge coefficients
    rh = 100.0 * np.exp(a * td / (b + td)) / np.exp(a * t / (b + t))
    return np.clip(rh, 0.0, 100.0)


def td_from_t_rh(t_c: np.ndarray, rh: np.ndarray) -> np.ndarray:
    """Dewpoint temperature (°C) from air temperature (°C) and relative humidity (%), Magnus inverse.

    Inverse of rh_from_t_td: td_from_t_rh(t, rh_from_t_td(t+273.15, td+273.15)) ≈ td.
    Pod computes this on-device from AHT10 (T, RH) to get dewpoint_dep = T − Td.
    """
    t = np.asarray(t_c, dtype="float64")
    r = np.clip(np.asarray(rh, dtype="float64"), 0.001, 100.0)
    a, b = 17.625, 243.04
    gamma = np.log(r / 100.0) + a * t / (b + t)
    return b * gamma / (a - gamma)


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


def raw_signals(ds: xr.Dataset) -> dict[str, Any]:
    """The pod-sensed raw signals, before feature-building.

    The sensor-sim layer degrades THESE (pressure/temp/humidity as the BME280 reads them) so that a
    constant pressure offset correctly cancels in the tendencies and persists only in absolute level.

    Args:
        ds: xarray Dataset with variables sp, t2m, d2m with valid_time coordinate

    Returns:
        dict with keys: time (DatetimeIndex), sp_hPa (ndarray), t2m_C (ndarray), rh (ndarray)
    """
    return {
        "time": pd.to_datetime(ds["valid_time"].values),
        "sp_hPa": ds["sp"].values.astype("float64") / 100.0,    # Pa → hPa
        "t2m_C": ds["t2m"].values.astype("float64") - 273.15,   # K → °C
        "rh": rh_from_t_td(ds["t2m"].values, ds["d2m"].values),
    }


def build_features_from_signals(signals: dict[str, Any]) -> pd.DataFrame:
    """Build the feature vector from (possibly sensor-degraded) raw signals.

    Args:
        signals: dict with keys sp_hPa, t2m_C, rh, time. From raw_signals() or sensor-degraded.

    Returns:
        pd.DataFrame with FEATURE_COLUMNS in order, DatetimeIndex named 'valid_time'.
    """
    sp_hpa, t2m_c, rh = signals["sp_hPa"], signals["t2m_C"], signals["rh"]
    df = pd.DataFrame(index=signals["time"])
    df.index.name = "valid_time"

    df["sp_hPa"] = sp_hpa
    for h in PRESSURE_TREND_HOURS:
        df[f"sp_rate_{h}h"] = trailing_slope(sp_hpa, h + 1)  # h-hour span = h+1 hourly points
    df["sp_accel_nested"] = df["sp_rate_3h"] - df["sp_rate_6h"]
    df["sp_accel_disjoint"] = df["sp_rate_3h"] - df["sp_rate_3h"].shift(3)  # 3h-lagged slope

    df["rh"] = rh
    df["rh_trend_3h"] = trailing_slope(rh, 4)

    df["t2m_C"] = t2m_c
    df["t2m_trend_3h"] = trailing_slope(t2m_c, 4)
    df["t2m_trend_6h"] = trailing_slope(t2m_c, 7)

    td_c = td_from_t_rh(t2m_c, rh)  # dewpoint temperature (°C) — full series for trends
    df["dewpoint_dep"] = t2m_c - td_c
    df["td_trend_3h"] = trailing_slope(td_c, 4)
    df["td_trend_6h"] = trailing_slope(td_c, 7)

    month = df.index.month.astype("float64")
    df["month_sin"] = np.sin(2 * np.pi * month / 12.0)
    df["month_cos"] = np.cos(2 * np.pi * month / 12.0)
    hour = df.index.hour.astype("float64")
    df["hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
    df["hour_cos"] = np.cos(2 * np.pi * hour / 24.0)

    return df[FEATURE_COLUMNS]


def build_features_endpoint(signals: dict[str, Any]) -> dict[str, float]:
    """Just the LAST (endpoint) feature row, as a plain dict — the fast path for per-endpoint builds.

    Must match ``build_features_from_signals(signals).iloc[-1]`` exactly (guarded by a parity test).
    Skips the per-endpoint DataFrame construction that dominates a multi-million-row training build.
    """
    sp, t, rh = signals["sp_hPa"], signals["t2m_C"], signals["rh"]
    last = pd.Timestamp(signals["time"][-1])
    out: dict[str, float] = {"sp_hPa": float(sp[-1])}

    sp_3h_all = trailing_slope(sp, 4)  # keep full array — needed for sp_accel_disjoint
    out["sp_rate_3h"] = float(sp_3h_all[-1])
    for h in PRESSURE_TREND_HOURS[1:]:  # 6, 12, 24, 48, 72
        out[f"sp_rate_{h}h"] = float(trailing_slope(sp, h + 1)[-1])
    out["sp_accel_nested"] = float(out["sp_rate_3h"] - out["sp_rate_6h"])
    # slope 3 steps back (window ending 3h ago); IndexError-safe guard; NaN if warmup not met
    out["sp_accel_disjoint"] = (
        float(sp_3h_all[-1] - sp_3h_all[-4]) if len(sp_3h_all) >= 4 else float("nan")
    )

    out["rh"] = float(rh[-1])
    out["rh_trend_3h"] = float(trailing_slope(rh, 4)[-1])

    out["t2m_C"] = float(t[-1])
    out["t2m_trend_3h"] = float(trailing_slope(t, 4)[-1])
    out["t2m_trend_6h"] = float(trailing_slope(t, 7)[-1])

    td_c = td_from_t_rh(t, rh)  # full series needed for trends
    out["dewpoint_dep"] = float(t[-1] - td_c[-1])
    out["td_trend_3h"] = float(trailing_slope(td_c, 4)[-1])
    out["td_trend_6h"] = float(trailing_slope(td_c, 7)[-1])

    mo = float(last.month)
    out["month_sin"] = float(np.sin(2 * np.pi * mo / 12.0))
    out["month_cos"] = float(np.cos(2 * np.pi * mo / 12.0))
    hr = float(last.hour)
    out["hour_sin"] = float(np.sin(2 * np.pi * hr / 24.0))
    out["hour_cos"] = float(np.cos(2 * np.pi * hr / 24.0))
    return out


def build_features(ds: xr.Dataset) -> pd.DataFrame:
    """Clean features straight from ERA5 (no sensor-sim).

    Args:
        ds: xarray Dataset with variables sp, t2m, d2m, valid_time coordinate

    Returns:
        pd.DataFrame with FEATURE_COLUMNS, DatetimeIndex named 'valid_time'.
    """
    return build_features_from_signals(raw_signals(ds))


if __name__ == "__main__":
    import argparse

    from podml.config import load_config
    from podml.era5_load import load_point_from_grid

    ap = argparse.ArgumentParser()
    ap.add_argument("--point", default=None, help="probe point name (default: verification_point)")
    args = ap.parse_args()

    cfg = load_config()
    name = args.point or cfg.get("verification_point") or next(iter(cfg["probe_points"]))

    print(f"Building features for {name} from ERA5 grid")
    feats = build_features(load_point_from_grid(name, cfg))
    print(f"\nShape: {feats.shape}")
    print(f"\n{feats.describe().round(3).T}")
    print("\nFirst rows with full history (after 6h warmup):")
    print(feats.iloc[6:9].round(3))
