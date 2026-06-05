"""Unit tests for label construction — the leakage-critical forward window."""

import numpy as np
import pandas as pd
import xarray as xr

from podml.labels import build_labels, forward_window_max, tp_mm_from_ds


def test_forward_max_basic():
    # out[T] = max(x[T+1 .. T+2]); last 2 are NaN
    out = forward_window_max([0, 1, 2, 3, 4], 2)
    assert np.array_equal(out[:3], [2.0, 3.0, 4.0])
    assert np.all(np.isnan(out[3:]))


def test_forward_max_excludes_current_hour():
    # A huge spike at T must NOT leak into the label at T (only the future counts).
    out = forward_window_max([10.0, 0.0, 0.0, 0.0], 2)
    assert out[0] == 0.0  # max of x[1], x[2] = 0, not the 10 at T=0


def test_forward_max_tail_is_nan():
    out = forward_window_max(np.arange(10.0), 3)
    assert np.all(np.isnan(out[-3:]))
    assert not np.any(np.isnan(out[:-3]))


def _toy_ds(tp_mm):
    n = len(tp_mm)
    t = pd.date_range("2020-06-01", periods=n, freq="h")
    return xr.Dataset(
        {"tp": ("valid_time", np.asarray(tp_mm, dtype="float64") / 1000.0)},  # mm → m
        coords={"valid_time": t},
    )


def test_tp_conversion_and_clip():
    tp = tp_mm_from_ds(_toy_ds([0.0, 5.0, -0.0001 * 1000]))  # last is a tiny negative in mm
    assert tp[1] == 5.0
    assert tp[2] == 0.0  # negative clipped


def test_build_labels_threshold_and_window():
    # rain spike of 5 mm/hr at hour index 2
    df = build_labels(_toy_ds([0, 0, 5, 0, 0, 0]), horizons=[2], thresholds=[2.5])
    col = "ge2.5_h2"
    # T=0: max(tp[1],tp[2]) = 5 ≥ 2.5 → 1 ; T=1: max(tp[2],tp[3]) = 5 → 1 ; T=2: max(tp[3],tp[4]) = 0 → 0
    assert df[col].iloc[0] == 1.0
    assert df[col].iloc[1] == 1.0
    assert df[col].iloc[2] == 0.0


def test_build_labels_columns_cover_all_combos():
    df = build_labels(_toy_ds([0.0] * 60), horizons=[6, 12], thresholds=[0.5, 2.5])
    assert set(df.columns) == {"ge0.5_h6", "ge2.5_h6", "ge0.5_h12", "ge2.5_h12"}


def test_forward_max_nowcast_h0():
    # h=0: returns x itself, no NaN tail (no forward window needed for nowcast)
    out = forward_window_max([0.0, 3.0, 1.0, 5.0], 0)
    np.testing.assert_array_equal(out, [0.0, 3.0, 1.0, 5.0])
    assert not np.any(np.isnan(out))


def test_build_labels_nowcast_column():
    # h=0 label = is it raining AT time T (not in the next H hours)
    df = build_labels(_toy_ds([0, 0, 5, 0, 0, 0]), horizons=[0], thresholds=[2.5])
    col = "ge2.5_h0"
    assert df[col].iloc[2] == 1.0   # spike at T=2 → nowcast fires
    assert df[col].iloc[0] == 0.0   # dry hour → no label
    assert not df[col].isna().any() # no NaN tail — nowcast never looks ahead


def test_default_horizons_include_nowcast():
    from podml.labels import HORIZONS_H
    assert 0 in HORIZONS_H
