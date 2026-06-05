"""Tests for ERA5 download retry logic, rate-limit detection, and log output.

Mocks the CDS client — no real API calls. Pins the behaviours Nepter modifies:
  - _is_rate_limited: RATE_LIMIT_HINTS matching (PRs #1, #14)
  - download_month: rate-limit vs genuine-error branching + log lines (PR #14)
  - _record_failure: writes full context to FAILURE_LOG
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from podml.download_era5_grid import (
    ERA5_MAX_ATTEMPTS,
    RATE_LIMIT_MAX_ATTEMPTS,
    _is_rate_limited,
    _record_failure,
    download_month,
)


class TestIsRateLimited:
    def test_temporarily_limited(self):
        assert _is_rate_limited(Exception("the request is temporarily limited")) is True

    def test_has_been_rejected(self):
        assert _is_rate_limited(Exception("the job has been rejected")) is True

    def test_queued_requests(self):
        assert _is_rate_limited(Exception("Number queued requests for this dataset")) is True

    def test_unknown_api_state_rejected(self):
        # PR #14: cdsapi raises "Unknown API state [rejected]" for CDS queue cap.
        # This string didn't match any previous hint — workers silently fell into the
        # genuine-error path and gave up instead of waiting out the transient limit.
        assert _is_rate_limited(Exception("Unknown API state [rejected]")) is True

    def test_case_insensitive(self):
        assert _is_rate_limited(Exception("QUEUED REQUESTS TEMPORARILY LIMITED")) is True

    def test_false_for_connection_error(self):
        assert _is_rate_limited(Exception("Connection refused")) is False

    def test_false_for_timeout(self):
        assert _is_rate_limited(Exception("socket timeout")) is False

    def test_false_for_generic_http_error(self):
        assert _is_rate_limited(Exception("500 Internal Server Error")) is False

    def test_checks_response_text_not_just_exc_str(self):
        # Rate-limit hint may appear only in the HTTP response body, not in str(exc).
        exc = Exception("HTTP 400")
        exc.response = MagicMock()
        exc.response.text = "the job has been rejected: queued requests temporarily limited"
        assert _is_rate_limited(exc) is True

    def test_no_response_attribute_does_not_crash(self):
        assert _is_rate_limited(Exception("some random failure")) is False


def _patch_download(tmp_path):
    """Context-manager stack of patches needed to exercise download_month in isolation."""
    import contextlib
    cache = tmp_path / "cache"
    cache.mkdir()
    return contextlib.ExitStack(), cache, [
        patch("podml.download_era5_grid.CACHE", cache),
        patch("podml.download_era5_grid.FAILURE_LOG", tmp_path / "failures.log"),
        patch("podml.download_era5_grid.time.sleep"),
    ]


class TestDownloadMonthRetry:
    def test_returns_cached_immediately(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        # Pre-create the cache file so download_month should skip without calling _client.
        cached = cache / "era5land_nz_2020-01.nc"
        cached.touch()
        with patch("podml.download_era5_grid.CACHE", cache), \
             patch("podml.download_era5_grid._client") as mock_factory:
            result = download_month(2020, 1)
        assert "cached" in result
        mock_factory.assert_not_called()

    def test_rate_limit_prints_retry_log_line(self, tmp_path, capsys):
        cache = tmp_path / "cache"
        cache.mkdir()
        with patch("podml.download_era5_grid.CACHE", cache), \
             patch("podml.download_era5_grid.FAILURE_LOG", tmp_path / "fail.log"), \
             patch("podml.download_era5_grid.time.sleep"), \
             patch("podml.download_era5_grid._client") as mock_factory:
            mock_factory.return_value.retrieve.side_effect = Exception("temporarily limited")
            with pytest.raises(RuntimeError):
                download_month(2020, 1)
        out = capsys.readouterr().out
        assert "rate-limited retry" in out

    def test_rate_limit_exhausts_after_max_attempts(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        with patch("podml.download_era5_grid.CACHE", cache), \
             patch("podml.download_era5_grid.FAILURE_LOG", tmp_path / "fail.log"), \
             patch("podml.download_era5_grid.time.sleep"), \
             patch("podml.download_era5_grid._client") as mock_factory:
            mock_factory.return_value.retrieve.side_effect = Exception("temporarily limited")
            with pytest.raises(RuntimeError, match="rate-limit waits"):
                download_month(2020, 1)
            # RATE_LIMIT_MAX_ATTEMPTS retries + the initial attempt that triggers break
            assert mock_factory.return_value.retrieve.call_count == RATE_LIMIT_MAX_ATTEMPTS + 1

    def test_genuine_error_prints_error_log_line(self, tmp_path, capsys):
        # PR #14 added this log line; before the fix workers vanished silently.
        cache = tmp_path / "cache"
        cache.mkdir()
        with patch("podml.download_era5_grid.CACHE", cache), \
             patch("podml.download_era5_grid.FAILURE_LOG", tmp_path / "fail.log"), \
             patch("podml.download_era5_grid.time.sleep"), \
             patch("podml.download_era5_grid._client") as mock_factory:
            mock_factory.return_value.retrieve.side_effect = Exception("some unknown failure")
            with pytest.raises(RuntimeError):
                download_month(2020, 1)
        out = capsys.readouterr().out
        assert "error" in out and f"/{ERA5_MAX_ATTEMPTS}" in out

    def test_genuine_error_exhausts_after_max_attempts(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        with patch("podml.download_era5_grid.CACHE", cache), \
             patch("podml.download_era5_grid.FAILURE_LOG", tmp_path / "fail.log"), \
             patch("podml.download_era5_grid.time.sleep"), \
             patch("podml.download_era5_grid._client") as mock_factory:
            mock_factory.return_value.retrieve.side_effect = Exception("some unknown failure")
            with pytest.raises(RuntimeError, match="failed after"):
                download_month(2020, 1)
            assert mock_factory.return_value.retrieve.call_count == ERA5_MAX_ATTEMPTS

    def test_rate_limit_and_genuine_errors_are_counted_separately(self, tmp_path, capsys):
        # Rate-limit errors should NOT burn through ERA5_MAX_ATTEMPTS.
        # Hit rate-limit twice, then genuine errors to exhaustion — genuine tries = ERA5_MAX_ATTEMPTS.
        cache = tmp_path / "cache"
        cache.mkdir()
        rate_exc = Exception("temporarily limited")
        genuine_exc = Exception("unknown failure")
        side_effects = [rate_exc, rate_exc] + [genuine_exc] * ERA5_MAX_ATTEMPTS
        with patch("podml.download_era5_grid.CACHE", cache), \
             patch("podml.download_era5_grid.FAILURE_LOG", tmp_path / "fail.log"), \
             patch("podml.download_era5_grid.time.sleep"), \
             patch("podml.download_era5_grid._client") as mock_factory:
            mock_factory.return_value.retrieve.side_effect = side_effects
            with pytest.raises(RuntimeError, match="2 rate-limit waits") as exc_info:
                download_month(2020, 1)
        assert f"{ERA5_MAX_ATTEMPTS} retries" in str(exc_info.value)


class TestRecordFailure:
    def test_writes_to_failure_log(self, tmp_path):
        log = tmp_path / "failures.log"
        with patch("podml.download_era5_grid.FAILURE_LOG", log):
            _record_failure(2020, 1, Exception("something went wrong"))
        assert log.exists()
        text = log.read_text()
        assert "2020-01" in text
        assert "something went wrong" in text

    def test_includes_response_body_when_present(self, tmp_path):
        log = tmp_path / "failures.log"
        exc = Exception("HTTP 400")
        exc.response = MagicMock()
        exc.response.text = "CDS detailed error: quota exceeded"
        with patch("podml.download_era5_grid.FAILURE_LOG", log):
            summary = _record_failure(2020, 1, exc)
        assert "CDS detailed error" in summary
        assert "CDS detailed error" in log.read_text()
