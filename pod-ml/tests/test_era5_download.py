"""Tests for ERA5 download retry logic, rate-limit detection, and log output.

Mocks the CDS client — no real API calls. Pins the behaviours Nepter modifies:
  - _is_rate_limited: RATE_LIMIT_HINTS matching (PRs #1, #14)
  - download_batch: rate-limit vs genuine-error branching + log lines (PR #14),
                    cached-month skip, multi-month batching
  - _record_failure: writes full context to FAILURE_LOG
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from podml.download_era5_grid import (
    ERA5_MAX_ATTEMPTS,
    RATE_LIMIT_MAX_ATTEMPTS,
    _classify_403,
    _is_rate_limited,
    _record_failure,
    download_batch,
)

_VARS = ["total_precipitation"]  # minimal variable list for tests


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

    def test_false_for_403(self):
        # 403 is NOT handled by _is_rate_limited — it goes through _classify_403 instead.
        assert _is_rate_limited(Exception("403 Client Error: Forbidden")) is False

    def test_checks_response_text_not_just_exc_str(self):
        # Rate-limit hint may appear only in the HTTP response body, not in str(exc).
        exc = Exception("HTTP 400")
        exc.response = MagicMock()
        exc.response.text = "the job has been rejected: queued requests temporarily limited"
        assert _is_rate_limited(exc) is True

    def test_no_response_attribute_does_not_crash(self):
        assert _is_rate_limited(Exception("some random failure")) is False


class TestClassify403:
    def _make_403(self, body: str) -> Exception:
        exc = Exception("403 Client Error: Forbidden")
        exc.response = MagicMock()
        exc.response.status_code = 403
        exc.response.text = body
        return exc

    def test_license_body(self):
        assert _classify_403(self._make_403("required licences not accepted")) == "license"

    def test_license_us_spelling(self):
        assert _classify_403(self._make_403("required licenses not accepted")) == "license"

    def test_maintenance_body(self):
        assert _classify_403(self._make_403("Download form temporarily closed due to maintenance")) == "maintenance"

    def test_unknown_403_treated_as_maintenance(self):
        # Unknown 403 reason — treated as transient so we don't silently abandon months.
        assert _classify_403(self._make_403("some other 403 reason")) == "maintenance"

    def test_non_403_returns_none(self):
        exc = Exception("500 Internal Server Error")
        exc.response = MagicMock()
        exc.response.status_code = 500
        exc.response.text = ""
        assert _classify_403(exc) is None

    def test_no_response_returns_none(self):
        assert _classify_403(Exception("connection error")) is None


class TestDownloadBatch:
    def test_returns_cached_immediately_for_all_cached(self, tmp_path, capsys):
        cache = tmp_path / "cache"
        cache.mkdir()
        # Pre-create both month files
        (cache / "era5land_nz_2020-01.nc").touch()
        (cache / "era5land_nz_2020-02.nc").touch()
        with patch("podml.download_era5_grid._client") as mock_factory:
            results = download_batch([(2020, 1), (2020, 2)], variables=_VARS, cache_dir=cache)
        mock_factory.assert_not_called()
        assert all("cached" in r for r in results)

    def test_skips_cached_months_within_batch(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        # Only month 1 is cached; month 2 should still be requested
        (cache / "era5land_nz_2020-01.nc").touch()
        with patch("podml.download_era5_grid.FAILURE_LOG", tmp_path / "fail.log"), \
             patch("podml.download_era5_grid.time.sleep"), \
             patch("podml.download_era5_grid._client") as mock_factory:
            mock_factory.return_value.retrieve.side_effect = Exception("some failure")
            with pytest.raises(RuntimeError):
                download_batch([(2020, 1), (2020, 2)], variables=_VARS, cache_dir=cache)
        # retrieve was called (month 2 needed fetching)
        mock_factory.return_value.retrieve.assert_called()

    def _make_403(self, body: str) -> Exception:
        exc = Exception("403 Client Error: Forbidden")
        exc.response = MagicMock()
        exc.response.status_code = 403
        exc.response.text = body
        return exc

    def test_403_licence_raises_immediately_without_retrying(self, tmp_path, capsys):
        # License 403 must stop immediately — it will never self-heal; retrying burns time.
        cache = tmp_path / "cache"
        cache.mkdir()
        licence_exc = self._make_403("required licences not accepted")
        with patch("podml.download_era5_grid.FAILURE_LOG", tmp_path / "fail.log"), \
             patch("podml.download_era5_grid.time.sleep"), \
             patch("podml.download_era5_grid._client") as mock_factory:
            mock_factory.return_value.retrieve.side_effect = licence_exc
            with pytest.raises(RuntimeError, match="LICENCE ERROR"):
                download_batch([(2020, 1)], variables=_VARS, cache_dir=cache)
        # Only one attempt — no retries on licence errors
        assert mock_factory.return_value.retrieve.call_count == 1
        assert "LICENCE ERROR" in capsys.readouterr().out

    def test_403_maintenance_retries_like_rate_limit(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        maint_exc = self._make_403("temporarily closed due to maintenance")
        with patch("podml.download_era5_grid.FAILURE_LOG", tmp_path / "fail.log"), \
             patch("podml.download_era5_grid.time.sleep"), \
             patch("podml.download_era5_grid._client") as mock_factory:
            mock_factory.return_value.retrieve.side_effect = maint_exc
            with pytest.raises(RuntimeError, match="rate-limit waits"):
                download_batch([(2020, 1)], variables=_VARS, cache_dir=cache)
        assert mock_factory.return_value.retrieve.call_count == RATE_LIMIT_MAX_ATTEMPTS + 1

    def test_rate_limit_prints_retry_log_line(self, tmp_path, capsys):
        cache = tmp_path / "cache"
        cache.mkdir()
        with patch("podml.download_era5_grid.FAILURE_LOG", tmp_path / "fail.log"), \
             patch("podml.download_era5_grid.time.sleep"), \
             patch("podml.download_era5_grid._client") as mock_factory:
            mock_factory.return_value.retrieve.side_effect = Exception("temporarily limited")
            with pytest.raises(RuntimeError):
                download_batch([(2020, 1)], variables=_VARS, cache_dir=cache)
        assert "rate-limited retry" in capsys.readouterr().out

    def test_rate_limit_exhausts_after_max_attempts(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        with patch("podml.download_era5_grid.FAILURE_LOG", tmp_path / "fail.log"), \
             patch("podml.download_era5_grid.time.sleep"), \
             patch("podml.download_era5_grid._client") as mock_factory:
            mock_factory.return_value.retrieve.side_effect = Exception("temporarily limited")
            with pytest.raises(RuntimeError, match="rate-limit waits"):
                download_batch([(2020, 1)], variables=_VARS, cache_dir=cache)
            assert mock_factory.return_value.retrieve.call_count == RATE_LIMIT_MAX_ATTEMPTS + 1

    def test_genuine_error_prints_error_log_line(self, tmp_path, capsys):
        # PR #14 added this log line; before the fix workers vanished silently.
        cache = tmp_path / "cache"
        cache.mkdir()
        with patch("podml.download_era5_grid.FAILURE_LOG", tmp_path / "fail.log"), \
             patch("podml.download_era5_grid.time.sleep"), \
             patch("podml.download_era5_grid._client") as mock_factory:
            mock_factory.return_value.retrieve.side_effect = Exception("some unknown failure")
            with pytest.raises(RuntimeError):
                download_batch([(2020, 1)], variables=_VARS, cache_dir=cache)
        out = capsys.readouterr().out
        assert "error" in out and f"/{ERA5_MAX_ATTEMPTS}" in out

    def test_genuine_error_exhausts_after_max_attempts(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        with patch("podml.download_era5_grid.FAILURE_LOG", tmp_path / "fail.log"), \
             patch("podml.download_era5_grid.time.sleep"), \
             patch("podml.download_era5_grid._client") as mock_factory:
            mock_factory.return_value.retrieve.side_effect = Exception("some unknown failure")
            with pytest.raises(RuntimeError, match="failed after"):
                download_batch([(2020, 1)], variables=_VARS, cache_dir=cache)
            assert mock_factory.return_value.retrieve.call_count == ERA5_MAX_ATTEMPTS

    def test_rate_limit_and_genuine_errors_counted_separately(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        rate_exc = Exception("temporarily limited")
        genuine_exc = Exception("unknown failure")
        side_effects = [rate_exc, rate_exc] + [genuine_exc] * ERA5_MAX_ATTEMPTS
        with patch("podml.download_era5_grid.FAILURE_LOG", tmp_path / "fail.log"), \
             patch("podml.download_era5_grid.time.sleep"), \
             patch("podml.download_era5_grid._client") as mock_factory:
            mock_factory.return_value.retrieve.side_effect = side_effects
            with pytest.raises(RuntimeError) as exc_info:
                download_batch([(2020, 1)], variables=_VARS, cache_dir=cache)
        assert "2 rate-limit waits" in str(exc_info.value)
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
