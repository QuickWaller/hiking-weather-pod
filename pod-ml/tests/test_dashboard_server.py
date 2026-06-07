"""Tests for dashboard_server.py parsing functions.

dashboard_server.py is a standalone script, not a package module, so we add
scripts/ to sys.path before importing. No server is started on import.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import dashboard_server as ds  # noqa: E402


class TestParseEra5Workers:
    def _write_log(self, tmp_path: Path, lines: list[str]) -> Path:
        log = tmp_path / "era5.log"
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return log

    def test_completed_worker_not_shown_as_submitting(self, tmp_path):
        # Regression: worker whose last log line is a completion (Ns NMB) was previously
        # reported as 'submitting' because the parser skipped the completion without
        # marking the worker seen, then found the earlier 'submitting' line and returned it.
        log = self._write_log(tmp_path, [
            "[W00] 2010-[12] started (1 months)",
            "[W00] 2010-[12] submitting (attempt 1)",
            "[W00] [2010-12] 3677s 22MB",
            "[W00] [2010-12] 3677s 22MB",  # duplicate line as seen in real logs
            "All months cached.",
        ])
        workers = ds._parse_era5_workers(log)
        assert workers == [], f"expected no active workers, got {workers}"

    def test_active_submitting_worker_is_shown(self, tmp_path):
        log = self._write_log(tmp_path, [
            "[W00] 2012-[05] started (1 months)",
            "[W00] 2012-[05] submitting (attempt 1)",
        ])
        workers = ds._parse_era5_workers(log)
        assert len(workers) == 1
        assert workers[0]["stage"] == "submitting"

    def test_only_active_workers_shown_when_mixed(self, tmp_path):
        # W00 completed, W01 still submitting — only W01 should appear.
        log = self._write_log(tmp_path, [
            "[W00] 2012-[05] submitting (attempt 1)",
            "[W01] 2012-[06] submitting (attempt 1)",
            "[W00] [2012-05] 3000s 20MB",
        ])
        workers = ds._parse_era5_workers(log)
        ids = [w["id"] for w in workers]
        assert "W00" not in ids, "completed worker should not appear"
        assert "W01" in ids, "active worker should appear"

    def test_failed_worker_not_shown(self, tmp_path):
        log = self._write_log(tmp_path, [
            "[W00] 2012-[05] submitting (attempt 1)",
            "[W00] [2012-05] FAILED: CDS request timed out",
        ])
        workers = ds._parse_era5_workers(log)
        assert workers == [], f"failed worker should not appear, got {workers}"

    def test_empty_log_returns_empty(self, tmp_path):
        log = self._write_log(tmp_path, [])
        assert ds._parse_era5_workers(log) == []
