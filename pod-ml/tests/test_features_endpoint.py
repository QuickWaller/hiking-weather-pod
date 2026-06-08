"""Parity test: the fast endpoint feature path must match the full feature builder's last row.

build_features_endpoint skips the per-endpoint DataFrame (the bottleneck in million-row training builds),
so it must produce *exactly* what build_features_from_signals(...).iloc[-1] would — guarded here.
"""

import numpy as np
import pandas as pd
import pytest

from podml.features import FEATURE_COLUMNS, build_features_endpoint, build_features_from_signals


def _signals(n=80, seed=0):
    r = np.random.default_rng(seed)
    return {
        "time": pd.date_range("2020-03-15 13:00", periods=n, freq="h"),
        "sp_hPa": 1000.0 + np.cumsum(r.normal(0, 0.5, n)),
        "t2m_C": 10.0 + r.normal(0, 1.0, n),
        "rh": np.clip(60.0 + r.normal(0, 5.0, n), 0, 100),
    }


@pytest.mark.parametrize("seed", [0, 1, 7])
def test_endpoint_matches_full_builder_last_row(seed):
    sig = _signals(seed=seed)
    full_last = build_features_from_signals(sig).iloc[-1]
    ep = build_features_endpoint(sig)
    assert set(ep) == set(FEATURE_COLUMNS)
    for col in FEATURE_COLUMNS:
        assert np.isclose(ep[col], float(full_last[col])), col


def test_endpoint_values_are_plain_floats():
    ep = build_features_endpoint(_signals())
    assert all(isinstance(v, float) for v in ep.values())
