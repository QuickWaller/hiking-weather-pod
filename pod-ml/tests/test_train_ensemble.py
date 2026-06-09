"""Tests for the phase-07 distributional ensemble — metrics, reshape, and calibration checks."""

import numpy as np
import pandas as pd
import pytest

from podml.train_ensemble import (
    ENSEMBLE_FEATURES, ENSEMBLE_HORIZONS, META_KEEP, MODEL_NAMES,
    _clim_preds, _slim_for_expansion, build_clim_distribution,
    coverage, crps_from_quantiles, crpss, expand_split_long, pit_histogram, to_long_format,
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


# ─────────────────────────────────────────────── expand_split_long ──────────────────────────────

def _toy_wide_full(n: int = 60) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Wide (X, y, meta) carrying every ENSEMBLE feature column and two years, for split tests."""
    rng = np.random.default_rng(2)
    feat_cols = [f for f in ENSEMBLE_FEATURES if f != "horizon_h"]
    X = pd.DataFrame({c: rng.normal(size=n).astype("float32") for c in feat_cols})
    labels = {f"amount_h{h}": rng.exponential(1.0, n).astype("float32") for h in ENSEMBLE_HORIZONS}
    labels["amount_h24"][-4:] = np.nan  # future extends past GPM for a few endpoints
    y = pd.DataFrame(labels)
    meta = pd.DataFrame({
        "cell": [f"c{i % 5}" for i in range(n)],
        "month": (np.arange(n) % 12) + 1,
        "year": np.where(np.arange(n) < 40, 2016, 2023),  # 40 train, 20 val
    })
    return X, y, meta


def test_expand_split_selects_only_the_split():
    """Only the masked endpoints are expanded — by row count vs to_long_format on that split."""
    X, y, meta = _toy_wide_full()
    ep = meta["year"].to_numpy() == 2016
    X_l, y_l, m_l = expand_split_long(X, y, meta, ep, ENSEMBLE_FEATURES)
    ref_X, _, _ = to_long_format(X[ep].reset_index(drop=True),
                                 y[ep].reset_index(drop=True),
                                 meta[ep].reset_index(drop=True))
    assert len(X_l) == len(ref_X)
    assert set(m_l["year"].unique()) == {2016}


def test_expand_split_columns_match_feats_exactly():
    """The no-copy contract: expanded columns equal the requested feats (so X[feats] is a no-op)."""
    X, y, meta = _toy_wide_full()
    ep = meta["year"].to_numpy() == 2016
    X_full, _, _ = expand_split_long(X, y, meta, ep, ENSEMBLE_FEATURES)
    assert list(X_full.columns) == list(ENSEMBLE_FEATURES)
    drop_feats = [f for f in ENSEMBLE_FEATURES if f != "rh"]
    X_drop, _, _ = expand_split_long(X, y, meta, ep, drop_feats)
    assert list(X_drop.columns) == drop_feats


def test_expand_split_drop_one_stays_row_aligned():
    """Dropping a feature must not change the row set/order — labels identical to the full set."""
    X, y, meta = _toy_wide_full()
    ep = meta["year"].to_numpy() == 2016
    _, y_full, _ = expand_split_long(X, y, meta, ep, ENSEMBLE_FEATURES)
    X_drop, y_drop, _ = expand_split_long(X, y, meta, ep, [f for f in ENSEMBLE_FEATURES if f != "rh"])
    assert len(y_full) == len(y_drop)
    assert np.array_equal(y_full.to_numpy(), y_drop.to_numpy())
    assert np.array_equal(X_drop["horizon_h"].to_numpy(),
                          expand_split_long(X, y, meta, ep, ENSEMBLE_FEATURES)[0]["horizon_h"].to_numpy())


# ─────────────────────────────────────────────── _slim_for_expansion ────────────────────────────

def _toy_wide_fat(n: int = 60) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Wide frame with the full fat meta (lat/lon/elev/zone/time/motion) the cache really carries."""
    X, y, meta = _toy_wide_full(n)
    rng = np.random.default_rng(7)
    meta["lat"] = rng.uniform(-45, -35, n)
    meta["lon"] = rng.uniform(166, 178, n)
    meta["elevation"] = rng.uniform(0, 2000, n)
    meta["zone"] = rng.integers(0, 4, n)
    meta["time"] = pd.date_range("2016-01-01", periods=n, freq="h")
    meta["motion"] = rng.choice(["still", "walk", "drive"], n)
    return X, y, meta


def test_slim_drops_fat_meta_and_downcasts():
    X, y, meta = _toy_wide_fat()
    Xs, ys, ms = _slim_for_expansion(X, y, meta)
    assert list(ms.columns) == META_KEEP
    assert str(ms["cell"].dtype) == "category"
    assert Xs.to_numpy().dtype == np.float32
    assert ys.to_numpy().dtype == np.float32


def test_slim_then_expand_then_climatology_runs():
    """Categorical cell must survive expansion and flow through the climatology groupby + lookup."""
    X, y, meta = _toy_wide_fat()
    Xs, ys, ms = _slim_for_expansion(X, y, meta)
    ep = ms["year"].to_numpy() == 2016
    X_l, y_l, m_l = expand_split_long(Xs, ys, ms, ep, ENSEMBLE_FEATURES)
    assert "lat" not in m_l.columns  # fat columns gone, not replicated 25×
    train_mask = np.ones(len(y_l), dtype=bool)
    table, glob = build_clim_distribution(y_l, m_l, train_mask)
    preds = _clim_preds(table, glob, m_l)
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
