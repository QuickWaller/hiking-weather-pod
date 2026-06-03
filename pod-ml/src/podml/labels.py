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
HORIZONS_H = [6, 12, 24, 48]


def forward_window_max(x: np.ndarray, h: int) -> np.ndarray:
    """Max over the next ``h`` samples strictly after each index.

    out[T] = max(x[T+1 .. T+H]); NaN for the last H samples (incomplete future).
    The *strictly after* part is what keeps the current hour out of the label (no leakage).
    """
    x = np.asarray(x, dtype="float64")
    n = x.size
    out = np.full(n, np.nan)
    if n > h:
        wmax = sliding_window_view(x, h).max(axis=1)  # wmax[i] = max(x[i .. i+h-1])
        out[: n - h] = wmax[1 : n - h + 1]            # out[T] = wmax[T+1] = max(x[T+1 .. T+h])
    return out


def tp_mm_from_ds(ds) -> np.ndarray:
    """ERA5-Land total precipitation (m, de-accumulated hourly) → mm/hr, negatives clipped to 0."""
    return np.clip(ds["tp"].values.astype("float64") * 1000.0, 0.0, None)


def build_labels(ds, horizons=HORIZONS_H, thresholds=THRESHOLDS_MM_HR) -> pd.DataFrame:
    """Binary labels indexed by valid_time, one column per (threshold, horizon)."""
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
