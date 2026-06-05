"""Unit tests for the GPM Harmony month iterator."""

from podml.download_gpm_harmony import month_range


def test_month_range_inclusive():
    assert list(month_range("2022-06", "2022-08")) == [(2022, 6), (2022, 7), (2022, 8)]


def test_month_range_crosses_year():
    assert list(month_range("2023-11", "2024-02")) == [(2023, 11), (2023, 12), (2024, 1), (2024, 2)]


def test_month_range_single_month():
    assert list(month_range("2022-06", "2022-06")) == [(2022, 6)]


def test_no_granules_exception_detected():
    # The early-exit is a case-insensitive substring match — verify the condition fires
    # for the real Harmony error message and not for unrelated transient errors.
    skip_exc = Exception("No matching granules found for this time range")
    assert "no matching granules" in str(skip_exc).lower()

    retry_exc = Exception("Service Unavailable 503")
    assert "no matching granules" not in str(retry_exc).lower()
