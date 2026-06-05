"""Step 4 (dress rehearsal) — binary rain-severity labels from ERA5-Land `tp`.

OPTIMISTIC PLACEHOLDER LABELS: using ERA5 precip as the label is (a) circular — features and labels
both come from ERA5's physics, so skill comes out flatteringly high — and (b) under-counts intensity.
Use only for the first "is there signal?" probe; replace with GPM for the honest number.

Label at time T = 1 if (max hourly rain intensity in the window (T, T+H] >= threshold mm/hr).
Lead = 0 ("the next H hours"); window strictly AFTER T (no leakage from the current hour).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

# Rain-intensity thresholds (mm/hr): light+ (any rain), moderate+, heavy+.
THRESHOLDS_MM_HR = [0.5, 2.5, 7.6]
HORIZONS_H = [0, 6, 12, 24, 48]


def forward_window_max(x: np.ndarray, h: int) -> np.ndarray:
    """Max over the next ``h`` samples strictly after each index.

    out[T] = max(x[T+1 .. T+H]); NaN for the last H samples (incomplete future).
    Special case h=0: returns x[T] (nowcast — is it raining right now?). No NaN tail.
    Features at T are pressure/temp/humidity history, never precip, so no circular leakage.
    """
    x = np.asarray(x, dtype="float64")
    if h == 0:
        return x.copy()
    n = x.size
    out = np.full(n, np.nan)
    if n > h:
        wmax = sliding_window_view(x, h).max(axis=1)  # wmax[i] = max(x[i .. i+h-1])
        out[: n - h] = wmax[1 : n - h + 1]            # out[T] = wmax[T+1] = max(x[T+1 .. T+h])
    return out


def tp_mm_from_ds(ds) -> np.ndarray:  # type: ignore[no-untyped-def]
    """ERA5-Land total precipitation (m, de-accumulated hourly) → mm/hr, negatives clipped to 0.

    Args:
        ds: xarray Dataset with 'tp' variable (in meters)

    Returns:
        np.ndarray of precipitation in mm/hr (non-negative)
    """
    return np.clip(ds["tp"].values.astype("float64") * 1000.0, 0.0, None)


def build_labels(
    ds,  # type: ignore[no-untyped-def]
    horizons: list[int] = HORIZONS_H,
    thresholds: list[float] = THRESHOLDS_MM_HR,
) -> pd.DataFrame:
    """Binary labels indexed by valid_time, one column per (threshold, horizon).

    Args:
        ds: xarray Dataset with 'tp' variable and 'valid_time' coordinate
        horizons: lead times in hours (default [6, 12, 24, 48])
        thresholds: rain intensity thresholds in mm/hr (default [0.5, 2.5, 7.6])

    Returns:
        pd.DataFrame with columns ge{thr}_h{h} (binary 0/1, NaN for incomplete tail)
        Index: DatetimeIndex named 'valid_time'
    """
    t = pd.to_datetime(ds["valid_time"].values)
    tp = tp_mm_from_ds(ds)
    df = pd.DataFrame(index=t)
    df.index.name = "valid_time"
    for h in horizons:
        fmax = forward_window_max(tp, h)
        for thr in thresholds:
            lab = (fmax >= thr).astype("float64")
            lab[np.isnan(fmax)] = np.nan  # tail with incomplete future stays unlabelled
            df[f"ge{thr}_h{h}"] = lab
    return df
