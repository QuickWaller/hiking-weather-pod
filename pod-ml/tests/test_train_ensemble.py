"""Tests for the phase-07 distributional ensemble — metrics, reshape, and calibration checks."""

import numpy as np
import pandas as pd
import pytest

from podml.train_ensemble import (
    ENSEMBLE_HORIZONS, MODEL_NAMES,
    _clim_preds, build_clim_distribution,
    coverage, crps_from_quantiles, crpss, pit_histogram, to_long_format,
)


# ─────────────────────────────────────────────── fixtures ───────────────────────────────────────

def _toy_wide(n: int = 40) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Minimal (X, y, meta) in wide format — enough for to_long_format and metrics tests."""
    rng = np.random.default_rng(0)
    X = pd.DataFrame({"sp_hPa": rng.normal(1000, 5, n)})
    labels = {f"amount_h{h}": rng.exponential(1.0, n) for h in ENSEMBLE_HORIZONS}
    # Introduce some NaN at the end of the series (future extends past GPM)
    for h in [23, 24]:
        labels[f"amount_h{h}"][-3:] = np.nan
    y = pd.DataFrame(labels)
    meta = pd.DataFrame({
        "cell": [f"c{i%5}" for i in range(n)],
        "lat": rng.uniform(-45, -35, n),
        "lon": rng.uniform(166, 178, n),
        "year": [2023] * n,
        "month": rng.integers(1, 13, n),
        "motion": ["walk"] * n,
    })
    return X, y, meta


# ─────────────────────────────────────────────── to_long_format ─────────────────────────────────

def test_long_format_row_count():
    """Each endpoint should appear once per horizon; NaN rows are dropped."""
    X, y, meta = _toy_wide(40)
    X_l, y_l, m_l = to_long_format(X, y, meta)
    # 25 horizons × 40 endpoints minus the 6 NaNs introduced (3 endpoints × 2 horizons)
    expected = 25 * 40 - 6
    assert len(X_l) == expected


def test_long_format_horizon_feature_present():
    X, y, meta = _toy_wide()
    X_l, _, _ = to_long_format(X, y, meta)
    assert "horizon_h" in X_l.columns
    assert set(X_l["horizon_h"].unique()) == set(float(h) for h in ENSEMBLE_HORIZONS)


def test_long_format_y_is_series_named_amount():
    _, y_l, _ = to_long_format(*_toy_wide())
    assert isinstance(y_l, pd.Series)
    assert y_l.name == "amount"


def test_long_format_no_nans_in_output():
    _, y_l, _ = to_long_format(*_toy_wide())
    assert y_l.isna().sum() == 0


def test_long_format_missing_column_raises():
    X, y, meta = _toy_wide()
    y_bad = y.drop(columns=["amount_h5"])
    with pytest.raises(ValueError, match="amount_h5"):
        to_long_format(X, y_bad, meta)


def test_long_format_matches_bruteforce_reference():
    """Per-horizon fill must equal a naive horizon-by-horizon expansion exactly — value and order.

    Rows are horizon-major, and within each horizon ordered by endpoint, NaN-amount rows dropped.
    A feature column with a unique value per endpoint makes the (endpoint, horizon)→row mapping
    unambiguous, so this guards the gather against any off-by-one or reordering.
    """
    n = 40
    X, y, meta = _toy_wide(n)
    X = X.copy()
    X["sp_hPa"] = np.arange(n, dtype="float64")  # unique per endpoint

    ref_X, ref_y, ref_h = [], [], []
    for h in ENSEMBLE_HORIZONS:
        col = y[f"amount_h{h}"].to_numpy()
        for ep in range(n):
            if not np.isnan(col[ep]):
                ref_X.append(X["sp_hPa"].iloc[ep])
                ref_y.append(col[ep])
                ref_h.append(float(h))

    X_l, y_l, _ = to_long_format(X, y, meta)
    assert np.array_equal(X_l["sp_hPa"].to_numpy(), np.array(ref_X, dtype="float32"))
    assert np.array_equal(X_l["horizon_h"].to_numpy(), np.array(ref_h, dtype="float32"))
    assert np.array_equal(y_l.to_numpy(), np.array(ref_y, dtype="float32"))


# ─────────────────────────────────────────────── year split ─────────────────────────────────────

def test_long_format_year_column_splits():
    """meta_long carries the endpoint's year on every horizon row, so a year mask splits cleanly."""
    X, y, meta = _toy_wide(40)
    meta = meta.copy()
    meta["year"] = np.where(np.arange(40) < 25, 2016, 2023)  # 25 endpoints train, 15 val
    _, y_l, m_l = to_long_format(X, y, meta)
    assert set(m_l["year"].unique()) == {2016, 2023}
    # Every endpoint expands to ≤25 horizon rows, so the split sizes stay proportional.
    assert (m_l["year"] == 2016).sum() > (m_l["year"] == 2023).sum()
    assert len(m_l) == len(y_l)


# ─────────────────────────────────────────────── climatology ────────────────────────────────────

def test_climatology_runs_through_long_format():
    """build_clim_distribution groupby + _clim_preds lookup flow on a to_long_format frame."""
    X, y, meta = _toy_wide()
    _, y_l, m_l = to_long_format(X, y, meta)
    table, glob = build_clim_distribution(y_l, m_l, np.ones(len(y_l), dtype=bool))
    preds = _clim_preds(table, glob, m_l)
    assert set(preds) == set(MODEL_NAMES)
    assert all(len(preds[name]) == len(m_l) for name in MODEL_NAMES)


# ─────────────────────────────────────────────── crps_from_quantiles ────────────────────────────

def _toy_preds(n: int = 100, spread: float = 1.0) -> tuple[np.ndarray, dict]:
    rng = np.random.default_rng(1)
    y = rng.exponential(2.0, n)
    preds = {
        "mean": y + rng.normal(0, 0.3, n),
        "q10": y - 2 * spread,
        "q25": y - spread,
        "q75": y + spread,
        "q90": y + 2 * spread,
    }
    return y, preds


def test_crps_is_non_negative():
    y, preds = _toy_preds()
    c = crps_from_quantiles(y, preds)
    assert np.all(c >= 0)


def test_crps_perfect_forecast_near_zero():
    """If every quantile equals the observation, CRPS should be ~0."""
    n = 50
    y = np.ones(n) * 2.0
    preds = {name: np.ones(n) * 2.0 for name in MODEL_NAMES[1:]}
    preds["mean"] = np.ones(n) * 2.0
    c = crps_from_quantiles(y, preds)
    assert np.allclose(c, 0.0, atol=1e-9)


def test_crps_wider_bands_larger():
    """Wider prediction interval → larger CRPS for the same observations."""
    y, preds_narrow = _toy_preds(spread=0.1)
    _, preds_wide   = _toy_preds(spread=5.0)
    c_n = crps_from_quantiles(y, preds_narrow).mean()
    c_w = crps_from_quantiles(y, preds_wide).mean()
    assert c_w > c_n


# ─────────────────────────────────────────────── crpss ──────────────────────────────────────────

def test_crpss_perfect_is_one():
    y = np.array([1.0, 2.0, 3.0])
    clim = y * 10  # bad climatology
    crps_model = np.zeros(3)
    assert crpss(crps_model, y, clim) == pytest.approx(1.0)


def test_crpss_equal_skill_is_zero():
    y = np.array([1.0, 2.0, 3.0])
    clim = y + 0.5
    crps_model = np.abs(y - clim)  # same as climatology baseline
    assert crpss(crps_model, y, clim) == pytest.approx(0.0, abs=1e-9)


def test_crpss_negative_when_model_worse():
    y = np.array([1.0, 2.0, 3.0])
    clim = y + 0.1
    crps_model = np.abs(y - clim) * 3  # much worse than climatology
    assert crpss(crps_model, y, clim) < 0


# ─────────────────────────────────────────────── coverage ───────────────────────────────────────

def test_coverage_all_inside():
    y = np.array([1.0, 2.0, 3.0])
    lo = y - 10
    hi = y + 10
    assert coverage(y, lo, hi) == pytest.approx(1.0)


def test_coverage_none_inside():
    y = np.array([1.0, 2.0, 3.0])
    lo = y + 1
    hi = y + 2
    assert coverage(y, lo, hi) == pytest.approx(0.0)


def test_coverage_half():
    y = np.array([1.0, 2.0, 3.0, 4.0])
    lo = np.array([0.0, 0.0, 5.0, 5.0])
    hi = np.array([2.0, 2.0, 10.0, 10.0])
    assert coverage(y, lo, hi) == pytest.approx(0.5)


# ─────────────────────────────────────────────── pit_histogram ──────────────────────────────────

def test_pit_histogram_bands_sum_to_one():
    y, preds = _toy_preds(200)
    pit = pit_histogram(y, preds)
    assert pit["observed"].sum() == pytest.approx(1.0, abs=1e-9)


def test_pit_histogram_columns():
    y, preds = _toy_preds()
    pit = pit_histogram(y, preds)
    assert list(pit.columns) == ["band", "observed", "expected"]
    assert len(pit) == 5


def test_pit_histogram_expected_sums_to_one():
    y, preds = _toy_preds()
    pit = pit_histogram(y, preds)
    assert pit["expected"].sum() == pytest.approx(1.0, abs=1e-9)


def test_pit_histogram_well_calibrated_is_roughly_uniform():
    """With many samples from the true distribution, PIT should be close to expected."""
    rng = np.random.default_rng(99)
    n = 5000
    y = rng.exponential(2.0, n)
    preds = {
        "mean": y,
        "q10": np.quantile(y, 0.10) * np.ones(n),
        "q25": np.quantile(y, 0.25) * np.ones(n),
        "q75": np.quantile(y, 0.75) * np.ones(n),
        "q90": np.quantile(y, 0.90) * np.ones(n),
    }
    pit = pit_histogram(y, preds)
    # Observed should be within 5 percentage points of expected for each band
    assert np.allclose(pit["observed"], pit["expected"], atol=0.05)
