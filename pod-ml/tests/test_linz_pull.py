"""Tests for linz_pull.py — all offline (no network calls)."""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

# Allow importing from scripts/linz
_LINZ_DIR = Path(__file__).parent.parent / "scripts" / "linz"
sys.path.insert(0, str(_LINZ_DIR))

# Set key before module-level _load_key() runs at import time
os.environ.setdefault("LINZ_KEY", "test-key-abc")

import layer_config as _lc_mod  # noqa: E402
import linz_pull as _lp_mod  # noqa: E402


# ---------------------------------------------------------------------------
# layer_config sanity
# ---------------------------------------------------------------------------

class TestLayerConfig:
    def test_all_layers_have_required_fields(self):
        required = {"linz_id", "name", "cadence_days", "description"}
        for layer_name, cfg in _lc_mod.LAYERS.items():
            missing = required - cfg.keys()
            assert not missing, f"{layer_name} missing: {missing}"

    def test_layer_ids_are_strings(self):
        for name, cfg in _lc_mod.LAYERS.items():
            assert isinstance(cfg["linz_id"], str), f"{name}.linz_id must be str"

    def test_cadence_days_positive(self):
        for name, cfg in _lc_mod.LAYERS.items():
            assert cfg["cadence_days"] > 0

    def test_expected_layers_present(self):
        expected = {"contours", "tracks", "roads", "lakes", "rivers", "coastline", "peaks", "glaciers"}
        assert expected == set(_lc_mod.LAYERS)

    def test_base_dir_is_string(self):
        assert isinstance(_lc_mod.BASE_DIR, str)


# ---------------------------------------------------------------------------
# read_status / write_status
# ---------------------------------------------------------------------------

class TestStatusIO:
    def test_read_status_missing_returns_empty(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_lp_mod, "BASE_DIR", str(tmp_path))
        assert _lp_mod.read_status("contours") == {}

    def test_write_then_read_roundtrip(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_lp_mod, "BASE_DIR", str(tmp_path))
        data = {"state": "complete", "last_revision": 12345, "file_size_mb": 150.3}
        _lp_mod.write_status("contours", data)
        result = _lp_mod.read_status("contours")
        assert result["state"] == "complete"
        assert result["last_revision"] == 12345
        assert result["file_size_mb"] == 150.3
        assert "updated_at" in result

    def test_write_status_creates_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_lp_mod, "BASE_DIR", str(tmp_path))
        assert not (tmp_path / "glaciers").exists()
        _lp_mod.write_status("glaciers", {"state": "complete"})
        assert (tmp_path / "glaciers" / "status.json").exists()

    def test_write_status_updated_at_is_utc_iso(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_lp_mod, "BASE_DIR", str(tmp_path))
        _lp_mod.write_status("lakes", {"state": "complete"})
        st = _lp_mod.read_status("lakes")
        # Should parse without error and be recent
        ts = datetime.fromisoformat(st["updated_at"])
        age = abs((datetime.now(timezone.utc) - ts).total_seconds())
        assert age < 5


# ---------------------------------------------------------------------------
# is_due
# ---------------------------------------------------------------------------

class TestIsDue:
    def _write_complete(self, tmp_path, name, age_days, cadence_days):
        last = (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat()
        d = tmp_path / name
        d.mkdir(exist_ok=True)
        (d / "status.json").write_text(json.dumps({
            "state": "complete",
            "last_updated": last,
            "cadence_days": cadence_days,
        }))

    def test_not_started_is_due(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_lp_mod, "BASE_DIR", str(tmp_path))
        assert _lp_mod.is_due("tracks")

    def test_error_state_is_due(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_lp_mod, "BASE_DIR", str(tmp_path))
        d = tmp_path / "tracks"
        d.mkdir()
        (d / "status.json").write_text(json.dumps({"state": "error"}))
        assert _lp_mod.is_due("tracks")

    def test_fresh_complete_is_not_due(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_lp_mod, "BASE_DIR", str(tmp_path))
        self._write_complete(tmp_path, "tracks", age_days=5, cadence_days=30)
        assert not _lp_mod.is_due("tracks")

    def test_stale_complete_is_due(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_lp_mod, "BASE_DIR", str(tmp_path))
        self._write_complete(tmp_path, "tracks", age_days=31, cadence_days=30)
        assert _lp_mod.is_due("tracks")

    def test_force_overrides_freshness(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_lp_mod, "BASE_DIR", str(tmp_path))
        self._write_complete(tmp_path, "tracks", age_days=1, cadence_days=90)
        assert _lp_mod.is_due("tracks", force=True)

    def test_exact_cadence_age_is_due(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_lp_mod, "BASE_DIR", str(tmp_path))
        self._write_complete(tmp_path, "contours", age_days=90, cadence_days=90)
        assert _lp_mod.is_due("contours")

    def test_one_day_short_of_cadence_is_not_due(self, tmp_path, monkeypatch):
        monkeypatch.setattr(_lp_mod, "BASE_DIR", str(tmp_path))
        self._write_complete(tmp_path, "contours", age_days=89, cadence_days=90)
        assert not _lp_mod.is_due("contours")


# ---------------------------------------------------------------------------
# _load_key
# ---------------------------------------------------------------------------

class TestLoadKey:
    def test_reads_from_env(self, monkeypatch):
        monkeypatch.setenv("LINZ_KEY", "env-key-xyz")
        assert _lp_mod._load_key() == "env-key-xyz"

    def test_reads_from_file_when_no_env(self, tmp_path, monkeypatch):
        monkeypatch.delenv("LINZ_KEY", raising=False)
        key_file = tmp_path / ".linz_key"
        key_file.write_text("file-key-abc\n")
        with patch("pathlib.Path.home", return_value=tmp_path):
            assert _lp_mod._load_key() == "file-key-abc"

    def test_exits_when_no_key_and_no_file(self, tmp_path, monkeypatch):
        monkeypatch.delenv("LINZ_KEY", raising=False)
        with patch("pathlib.Path.home", return_value=tmp_path):
            with pytest.raises(SystemExit):
                _lp_mod._load_key()
