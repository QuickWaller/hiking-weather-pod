"""Tests for GPM Harmony download retry logic, skip conditions, and log output.

Mocks the Harmony client — no real API calls. Pins the behaviours Nepter modifies:
  - _run_job: timeout, paused-resume, terminal status handling
  - build_grid: no-granules early exit, retry on transient errors, incomplete-steps retry,
                SKIPPED log after exhausting GPM_MAX_ATTEMPTS, already-cached skip
  - _acquire_lock: stale vs live lock detection
"""
from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

import pytest

from podml.download_gpm_harmony import (
    GPM_MAX_ATTEMPTS,
    _acquire_lock,
    _run_job,
    build_grid,
)


class TestRunJob:
    def test_returns_job_on_successful_status(self):
        client = MagicMock()
        client.submit.return_value = "job-1"
        client.status.return_value = {"status": "successful"}
        with patch("podml.download_gpm_harmony.time.sleep"):
            result = _run_job(client, MagicMock())
        assert result == "job-1"

    def test_resumes_paused_job_then_returns(self):
        client = MagicMock()
        client.submit.return_value = "job-2"
        # paused on first poll, successful on second
        client.status.side_effect = [{"status": "paused"}, {"status": "successful"}]
        with patch("podml.download_gpm_harmony.time.sleep"):
            result = _run_job(client, MagicMock())
        client.resume.assert_called_once_with("job-2")
        assert result == "job-2"

    def test_raises_timeout_error(self):
        client = MagicMock()
        client.submit.return_value = "job-3"
        client.status.return_value = {"status": "running"}
        # Make time advance past timeout immediately on second check
        start = time.time()
        with patch("podml.download_gpm_harmony.time.sleep"), \
             patch("podml.download_gpm_harmony.time.time", side_effect=[start, start, start + 1801]):
            with pytest.raises(TimeoutError, match="exceeded"):
                _run_job(client, MagicMock(), timeout_sec=1800)

    def test_returns_on_failed_status(self):
        client = MagicMock()
        client.submit.return_value = "job-4"
        client.status.return_value = {"status": "failed"}
        with patch("podml.download_gpm_harmony.time.sleep"):
            result = _run_job(client, MagicMock())
        assert result == "job-4"

    def test_returns_on_complete_with_errors(self):
        client = MagicMock()
        client.submit.return_value = "job-5"
        client.status.return_value = {"status": "complete_with_errors"}
        with patch("podml.download_gpm_harmony.time.sleep"):
            result = _run_job(client, MagicMock())
        assert result == "job-5"


class TestBuildGrid:
    """Tests for build_grid control flow — _process_month creates its own Client() per thread."""

    def _make_client(self, *, job_status="successful", download_files=None, submit_exc=None):
        client = MagicMock()
        if submit_exc:
            client.submit.side_effect = submit_exc
        else:
            client.submit.return_value = "job-x"
            client.status.return_value = {"status": job_status}
            futures = [MagicMock(result=MagicMock(return_value=f)) for f in (download_files or [])]
            client.download_all.return_value = futures
        return client

    def test_skips_already_cached_month(self, tmp_path):
        grid_dir = tmp_path / "gpm_grid"
        grid_dir.mkdir()
        (grid_dir / "gpm_2024-01.nc").touch()
        client = self._make_client()
        with patch("podml.download_gpm_harmony.GRID_DIR", grid_dir), \
             patch("harmony.Client", return_value=client), \
             patch("harmony.Request"), \
             patch("podml.download_gpm_harmony.time.sleep"):
            build_grid("2024-01", "2024-01", MagicMock(), MagicMock(), month_workers=1)
        # Already-cached months are filtered out before any thread starts — no submit
        client.submit.assert_not_called()

    def test_no_granules_skips_immediately_without_retrying(self, tmp_path, capsys):
        # IMERG Final lag: Harmony raises "No matching granules found" — must skip on the
        # first attempt and NOT burn through GPM_MAX_ATTEMPTS retries.
        grid_dir = tmp_path / "gpm_grid"
        grid_dir.mkdir()
        client = self._make_client(submit_exc=Exception("No matching granules found"))
        with patch("podml.download_gpm_harmony.GRID_DIR", grid_dir), \
             patch("harmony.Client", return_value=client), \
             patch("harmony.Request"), \
             patch("podml.download_gpm_harmony.time.sleep"):
            build_grid("2024-01", "2024-01", MagicMock(), MagicMock(), month_workers=1)
        # Only one submit call — no retries
        assert client.submit.call_count == 1
        out = capsys.readouterr().out
        assert "no granules available" in out
        # Month must NOT appear as SKIPPED (last_exc was cleared)
        assert "SKIPPED" not in out

    def test_transient_error_retries_up_to_max_attempts(self, tmp_path, capsys):
        grid_dir = tmp_path / "gpm_grid"
        grid_dir.mkdir()
        client = self._make_client(submit_exc=Exception("Service Unavailable 503"))
        with patch("podml.download_gpm_harmony.GRID_DIR", grid_dir), \
             patch("harmony.Client", return_value=client), \
             patch("harmony.Request"), \
             patch("podml.download_gpm_harmony.time.sleep"):
            build_grid("2024-01", "2024-01", MagicMock(), MagicMock(), month_workers=1)
        assert client.submit.call_count == GPM_MAX_ATTEMPTS
        assert "SKIPPED" in capsys.readouterr().out

    def test_incomplete_steps_triggers_retry(self, tmp_path, capsys):
        # If stacked granule count < 95% of file count, the month is holey → retry.
        import numpy as np
        import pandas as pd
        import xarray as xr

        grid_dir = tmp_path / "gpm_grid"
        grid_dir.mkdir()

        # Build a tiny month dataset with only 1 timestep (far below 95% of 10 "granules")
        times = pd.date_range("2024-01-01", periods=1, freq="30min")
        ds = xr.Dataset(
            {"precipitation": (["time", "lon", "lat"], np.zeros((1, 2, 2)))},
            coords={"time": times, "lon": [170.0, 171.0], "lat": [-42.0, -41.0]},
        )

        # stack_month returns our thin dataset; download_all claims 10 "files"
        ten_file_futures = [MagicMock(result=MagicMock(return_value=f"f{i}")) for i in range(10)]
        client = MagicMock()
        client.submit.return_value = "job-x"
        client.status.return_value = {"status": "successful"}
        client.download_all.return_value = ten_file_futures

        with patch("podml.download_gpm_harmony.GRID_DIR", grid_dir), \
             patch("harmony.Client", return_value=client), \
             patch("podml.download_gpm_harmony.time.sleep"), \
             patch("podml.download_gpm_harmony.stack_month", return_value=ds), \
             patch("harmony.Request"):
            build_grid("2024-01", "2024-01", MagicMock(), MagicMock(), month_workers=1)

        assert client.submit.call_count == GPM_MAX_ATTEMPTS
        assert "INCOMPLETE" in capsys.readouterr().out


class TestAcquireLock:
    def test_creates_lock_with_current_pid(self, tmp_path):
        grid_dir = tmp_path / "gpm_grid"
        grid_dir.mkdir()
        with patch("podml.download_gpm_harmony.GRID_DIR", grid_dir):
            _acquire_lock()
        lock = grid_dir / ".pull.lock"
        assert lock.exists()
        assert int(lock.read_text().strip()) == os.getpid()

    def test_takes_over_stale_lock(self, tmp_path):
        grid_dir = tmp_path / "gpm_grid"
        grid_dir.mkdir()
        lock = grid_dir / ".pull.lock"
        lock.write_text("999999999")
        # os.kill raises ProcessLookupError on Linux for a dead PID; mock it so the
        # test is platform-independent (Windows raises OSError instead).
        with patch("podml.download_gpm_harmony.GRID_DIR", grid_dir), \
             patch("podml.download_gpm_harmony.os.kill", side_effect=ProcessLookupError):
            _acquire_lock()  # should not raise
        assert int(lock.read_text().strip()) == os.getpid()

    def test_refuses_if_live_process_holds_lock(self, tmp_path):
        grid_dir = tmp_path / "gpm_grid"
        grid_dir.mkdir()
        lock = grid_dir / ".pull.lock"
        lock.write_text(str(os.getpid()))  # our own PID is definitely alive
        with patch("podml.download_gpm_harmony.GRID_DIR", grid_dir):
            with pytest.raises(SystemExit, match="already running"):
                _acquire_lock()
