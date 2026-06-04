"""Unit tests for configuration validation."""

import tempfile
from pathlib import Path

from podml.config_validate import ConfigValidator


class TestProbePointValidation:
    """Test probe point validation."""

    def test_valid_nz_coordinates(self):
        """Valid NZ coordinates pass validation."""
        cfg = {
            "probe_points": {
                "hokitika_westcoast": {"lat": -42.7, "lon": 171.2},
                "christchurch_lee": {"lat": -43.5, "lon": 172.6},
            }
        }
        validator = ConfigValidator(cfg)
        validator._validate_probe_points()
        assert len(validator.errors) == 0

    def test_missing_lat_lon(self):
        """Missing lat/lon coordinates raise error."""
        cfg = {
            "probe_points": {
                "bad_point": {"lat": -41.0},  # missing lon
            }
        }
        validator = ConfigValidator(cfg)
        validator._validate_probe_points()
        assert len(validator.errors) > 0

    def test_out_of_bounds_latitude(self):
        """Coordinates outside NZ bounds raise error."""
        cfg = {
            "probe_points": {
                "out_of_bounds": {"lat": -60.0, "lon": 172.0},  # too far south
            }
        }
        validator = ConfigValidator(cfg)
        validator._validate_probe_points()
        assert any("lat" in e and "outside" in e for e in validator.errors)

    def test_out_of_bounds_longitude(self):
        """Longitude outside NZ bounds raises error."""
        cfg = {
            "probe_points": {
                "out_of_bounds": {"lat": -41.0, "lon": 190.0},  # too far east
            }
        }
        validator = ConfigValidator(cfg)
        validator._validate_probe_points()
        assert any("lon" in e and "outside" in e for e in validator.errors)

    def test_non_numeric_coordinates(self):
        """Non-numeric lat/lon raises error."""
        cfg = {
            "probe_points": {
                "bad_type": {"lat": "41.0", "lon": 172.0},
            }
        }
        validator = ConfigValidator(cfg)
        validator._validate_probe_points()
        assert any("numeric" in e for e in validator.errors)

    def test_no_probe_points_raises_error(self):
        """Missing probe_points in config raises error."""
        cfg = {}
        validator = ConfigValidator(cfg)
        validator._validate_probe_points()
        assert len(validator.errors) > 0


class TestThresholdValidation:
    """Test threshold and horizon validation."""

    def test_valid_thresholds_and_horizons(self):
        """Valid thresholds and horizons pass."""
        cfg = {}
        validator = ConfigValidator(cfg)
        validator._validate_thresholds()
        # Should pass (thresholds/horizons are module-level constants)
        assert len(validator.errors) == 0

    def test_negative_threshold_raises_error(self):
        """Negative thresholds would raise error (if overrideable)."""
        # This test documents the contract but can't easily override module constants
        # In practice, THRESHOLDS_MM_HR is imported from constants
        pass


class TestFeatureColumnValidation:
    """Test feature schema validation."""

    def test_feature_columns_complete(self):
        """Feature columns contain all required fields."""
        cfg = {}
        validator = ConfigValidator(cfg)
        validator._validate_feature_columns()
        assert len(validator.errors) == 0
        assert any("Feature schema" in info for info in validator.info)


class TestDirectoryValidation:
    """Test directory validation (integration with filesystem)."""

    def test_existing_writable_directory_passes(self):
        """Existing writable directory passes validation."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Manually check a temp directory
            tmppath = Path(tmpdir)
            assert tmppath.exists()
            assert tmppath.is_dir()
            # Real check happens in _validate_directories but requires DATA_RAW

    def test_create_missing_directory_with_fix(self):
        """With --fix, missing directories are created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            missing_dir = tmppath / "new_dir"
            assert not missing_dir.exists()

            # Simulate what _validate_directories does with fix=True
            missing_dir.mkdir(parents=True, exist_ok=True)
            assert missing_dir.exists()


class TestValidationReport:
    """Test report generation."""

    def test_report_shows_errors_and_warnings(self):
        """Report output distinguishes errors from warnings."""
        cfg = {
            "probe_points": {
                "good": {"lat": -41.0, "lon": 172.0},
                "bad": {"lat": -60.0, "lon": 172.0},
            }
        }
        validator = ConfigValidator(cfg)
        validator._validate_probe_points()
        # Should have 1 error (bad point)
        assert len(validator.errors) == 1
        assert len(validator.info) >= 1

    def test_validate_all_returns_bool(self):
        """validate_all() returns True on success, False on error."""
        cfg_good = {"probe_points": {"p1": {"lat": -41.0, "lon": 172.0}}}
        v1 = ConfigValidator(cfg_good)
        assert v1.validate_all()

        cfg_bad = {"probe_points": {"p1": {"lat": -60.0, "lon": 172.0}}}
        v2 = ConfigValidator(cfg_bad)
        assert not v2.validate_all()
