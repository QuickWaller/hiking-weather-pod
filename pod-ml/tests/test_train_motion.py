"""Unit tests for podml.train_motion metric + climatology helpers.

The heavy build_dataset/train_and_eval paths are integration-checked by the VM smoke runs (they need
ERA5/GPM on disk); here we unit-test the pure pieces: Brier, operating-point sweep, reliability bins, and
the train-only climatology baseline/features.
"""

import numpy as np
import pandas as pd
import pytest

from podml.train_motion import (
    ALL_FEATURES,
    STATIC_COLS,
    _brier,
    _operating_points,
    _reliability,
    add_cell_climatology,
    cell_month_climatology,
)
from podml.features import FEATURE_COLUMNS


def test_all_features_is_dynamic_plus_static():
    assert ALL_FEATURES == list(FEATURE_COLUMNS) + STATIC_COLS


def test_brier_matches_definition():
    p = np.array([0.2, 0.8, 0.5])
    y = np.array([0.0, 1.0, 1.0])
    assert _brier(p, y) == pytest.approx(np.mean((p - y) ** 2))


def test_operating_points_monotonic():
    p = np.array([0.1, 0.4, 0.6, 0.9])
    y = np.array([0.0, 0.0, 1.0, 1.0])
    op = _operating_points(p, y, n=19)
    # raising the decision threshold can only lower recall and the false-alarm rate
    assert np.all(np.diff(op["recall"].to_numpy()) <= 1e-9)
    assert np.all(np.diff(op["false_alarm_rate"].to_numpy()) <= 1e-9)
    assert np.allclose(op["miss_rate"], 1.0 - op["recall"])
    assert op["recall"].max() == pytest.approx(1.0)  # at the lowest decision both positives caught


def test_reliability_bins_within_range_and_count_conserved():
    rng = np.random.default_rng(0)
    p = rng.uniform(0, 1, 500)
    y = (rng.uniform(0, 1, 500) < p).astype(float)  # well-calibrated by construction
    rel = _reliability(p, y, n_bins=10)
    assert rel["n"].sum() == 500
    assert (rel["pred_mean"].between(0, 1)).all() and (rel["obs_freq"].between(0, 1)).all()


def _meta(cells, months, years):
    return pd.DataFrame({"cell": cells, "month": months, "year": years})


def test_cell_month_climatology_uses_train_means_with_global_fallback():
    # cell A month 1 trains at rate 0.5; an unseen (cell B, month 2) row falls back to global train rate.
    meta = _meta(["A", "A", "A", "B"], [1, 1, 1, 2], [2016, 2016, 2024, 2024])
    y = pd.Series([1.0, 0.0, np.nan, np.nan])
    train_mask = np.array([True, True, False, False])
    base = cell_month_climatology(y, meta, train_mask)
    assert base[2] == pytest.approx(0.5)         # (A,1) test row → train mean 0.5
    assert base[3] == pytest.approx(0.5)         # (B,2) unseen → global train rate (also 0.5 here)


def test_add_cell_climatology_appends_train_only_means():
    X = pd.DataFrame({c: np.zeros(4) for c in FEATURE_COLUMNS})
    X["sp_hPa"] = [1000.0, 1010.0, 999.0, 0.0]
    X["t2m_C"] = [10.0, 12.0, 5.0, 0.0]
    X["rh"] = [60.0, 80.0, 50.0, 0.0]
    meta = pd.DataFrame({"cell": ["A", "A", "B", "B"]})
    train_mask = np.array([True, True, True, False])  # last row excluded from the means
    add_cell_climatology(X, meta, train_mask)
    for col in ("pressure_mean", "temp_mean", "precip_mean"):
        assert col in X.columns
    # cell A pressure_mean = mean(1000, 1010) = 1005 for both A rows
    assert X.loc[0, "pressure_mean"] == pytest.approx(1005.0)
    # cell B uses only its single train row (999), not the excluded last row
    assert X.loc[2, "pressure_mean"] == pytest.approx(999.0)
