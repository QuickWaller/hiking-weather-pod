"""Unit tests for the GPM Late Run fine-label downloader (pure logic; no network)."""

import pandas as pd
import pytest

from podml.download_gpm_late import granule_start, load_queries


def test_granule_start_floors_to_half_hour():
    # period-beginning: a query mid-window maps to that window's start
    assert granule_start("2026-06-11T21:14:59") == pd.Timestamp("2026-06-11T21:00")
    assert granule_start("2026-06-11T21:45:00") == pd.Timestamp("2026-06-11T21:30")


def test_granule_start_on_boundary_is_identity():
    assert granule_start("2026-06-11T21:30:00") == pd.Timestamp("2026-06-11T21:30")


def test_granule_start_normalises_tz_to_utc():
    # 09:14 NZST 12-Jun (UTC+12) == 21:14 UTC 11-Jun (crosses midnight back) → floors to the 21:00 granule
    assert granule_start("2026-06-12T09:14:00+12:00") == pd.Timestamp("2026-06-11T21:00")


def test_load_queries_minimal_autonames(tmp_path):
    p = tmp_path / "q.csv"
    p.write_text("time,lat,lon\n2026-06-11T21:00,-36.66,174.73\n")
    df = load_queries(p)
    assert list(df.columns) == ["time", "lat", "lon", "name"]
    assert df.loc[0, "time"] == pd.Timestamp("2026-06-11T21:00")
    assert df.loc[0, "name"] == "q0"  # auto-named when no name column


def test_load_queries_keeps_name_and_normalises_tz(tmp_path):
    p = tmp_path / "q.csv"
    p.write_text("name,time,lat,lon\nlong_bay,2026-06-12T09:00:00+12:00,-36.66,174.73\n")
    df = load_queries(p)
    assert df.loc[0, "name"] == "long_bay"
    assert df.loc[0, "time"] == pd.Timestamp("2026-06-11T21:00")  # 09:00 NZST → naive UTC (prev day)


def test_load_queries_rejects_missing_columns(tmp_path):
    p = tmp_path / "q.csv"
    p.write_text("time,latitude,lon\n2026-06-11T21:00,-36.66,174.73\n")  # 'lat' missing
    with pytest.raises(ValueError, match="lat"):
        load_queries(p)
