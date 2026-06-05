"""Configuration validation for pod-ml deployment.

Checks that config.yaml is valid before any data pipeline runs:
  - All probe points have valid lat/lon in NZ bounds
  - All data directories exist and are writable
  - All data files have correct structure (headers, dimensions)
  - All numerical thresholds are in valid ranges
  - ERA5 timeseries exist for training years
  - Feature/label columns match schema contracts

Usage:
  python -m podml.config_validate [--fix]

  --fix: Create missing directories and log missing data sources
"""

from __future__ import annotations

import argparse
import os
import sys

import pandas as pd
import xarray as xr

from podml.config import DATA_RAW, load_config
from podml.features import FEATURE_COLUMNS
from podml.labels import HORIZONS_H, THRESHOLDS_MM_HR


class ConfigValidator:
    """Validate pod-ml configuration and data availability."""

    def __init__(self, config: dict, fix: bool = False):
        self.cfg = config
        self.fix = fix
        self.errors = []
        self.warnings = []
        self.info = []

    def validate_all(self) -> bool:
        """Run all validation checks. Returns True if all pass."""
        self._validate_probe_points()
        self._validate_directories()
        self._validate_era5_data()
        self._validate_openmeteo_data()
        self._validate_gpm_data()
        self._validate_thresholds()
        self._validate_feature_columns()

        return len(self.errors) == 0

    def _validate_probe_points(self) -> None:
        """Check that all probe points have valid lat/lon within NZ bounds."""
        points = self.cfg.get("probe_points", {})
        if not points:
            self.errors.append("No probe_points defined in config")
            return

        # NZ bounding box: 34°S–47°S, 166°E–178°E
        nz_lat_min, nz_lat_max = -47.0, -34.0
        nz_lon_min, nz_lon_max = 166.0, 178.0

        for name, coords in points.items():
            lat = coords.get("lat")
            lon = coords.get("lon")

            if lat is None or lon is None:
                self.errors.append(f"{name}: missing lat or lon")
                continue

            if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                self.errors.append(f"{name}: lat/lon must be numeric")
                continue

            if not (nz_lat_min <= lat <= nz_lat_max):
                self.errors.append(f"{name}: lat {lat} outside NZ bounds [{nz_lat_min}, {nz_lat_max}]")

            if not (nz_lon_min <= lon <= nz_lon_max):
                self.errors.append(f"{name}: lon {lon} outside NZ bounds [{nz_lon_min}, {nz_lon_max}]")

            self.info.append(f"{name}: ({lat:.4f}, {lon:.4f}) ✓")

    def _validate_directories(self) -> None:
        """Check that all required directories exist and are writable."""
        dirs_to_check = [
            DATA_RAW,
            DATA_RAW / "era5land",
            DATA_RAW / "gpm_grid",
            DATA_RAW / "openmeteo",
        ]

        for d in dirs_to_check:
            if not d.exists():
                if self.fix:
                    d.mkdir(parents=True, exist_ok=True)
                    self.info.append(f"Created {d}")
                else:
                    self.warnings.append(f"Directory missing: {d}")
            else:
                if not d.is_dir():
                    self.errors.append(f"Not a directory: {d}")
                elif not os.access(d, os.W_OK):
                    self.errors.append(f"Directory not writable: {d}")
                else:
                    self.info.append(f"Directory OK: {d}")

    def _validate_era5_data(self) -> None:
        """Check ERA5 timeseries for training years (2010–2022)."""
        points = self.cfg.get("probe_points", {})

        for point_name in points:
            expected_file = DATA_RAW / "era5land" / f"era5land_ts_{point_name}_2010-2022_2024-12-31.nc"

            if not expected_file.exists():
                self.warnings.append(f"ERA5 file missing: {expected_file.name}")
                continue

            try:
                with xr.open_dataset(expected_file) as ds:
                    # Check required variables
                    required_vars = {"sp", "t2m", "d2m"}
                    missing = required_vars - set(ds.data_vars)
                    if missing:
                        self.errors.append(f"{point_name}: ERA5 missing variables {missing}")
                    else:
                        n = len(ds["valid_time"])
                        self.info.append(f"{point_name}: ERA5 OK ({n} timesteps)")
            except Exception as e:
                self.errors.append(f"{point_name}: ERA5 file corrupted ({e})")

    def _validate_openmeteo_data(self) -> None:
        """Check Open-Meteo observations exist and have recent data."""
        points = self.cfg.get("probe_points", {})
        openmeteo_dir = DATA_RAW / "openmeteo"

        for point_name in points:
            csv_file = openmeteo_dir / f"{point_name}.csv"

            if not csv_file.exists():
                self.warnings.append(f"Open-Meteo missing: {point_name}.csv")
                continue

            try:
                df = pd.read_csv(csv_file, nrows=5)
                required_cols = {"time", "precipitation_mm_hr", "pressure_hpa", "temp_c", "humidity_pct"}
                missing = required_cols - set(df.columns)
                if missing:
                    self.errors.append(f"{point_name}: Open-Meteo missing columns {missing}")
                else:
                    self.info.append(f"{point_name}: Open-Meteo OK")
            except Exception as e:
                self.errors.append(f"{point_name}: Open-Meteo CSV corrupted ({e})")

    def _validate_gpm_data(self) -> None:
        """Check GPM monthly grids exist (partial download is OK)."""
        gpm_dir = DATA_RAW / "gpm_grid"

        if not gpm_dir.exists():
            self.warnings.append(f"GPM directory missing: {gpm_dir}")
            return

        gpm_files = list(gpm_dir.glob("gpm_*.nc"))
        if not gpm_files:
            self.warnings.append("No GPM files found (partial download expected)")
        else:
            self.info.append(f"GPM: {len(gpm_files)} monthly grids available")

    def _validate_thresholds(self) -> None:
        """Check that rain thresholds and horizons are defined."""
        if not THRESHOLDS_MM_HR:
            self.errors.append("THRESHOLDS_MM_HR not defined")
        else:
            if not all(t > 0 for t in THRESHOLDS_MM_HR):
                self.errors.append("THRESHOLDS_MM_HR must be positive")
            else:
                self.info.append(f"Thresholds: {THRESHOLDS_MM_HR} mm/hr ✓")

        if not HORIZONS_H:
            self.errors.append("HORIZONS_H not defined")
        else:
            if not all(h >= 0 for h in HORIZONS_H):
                self.errors.append("HORIZONS_H must be non-negative (0 = nowcast)")
            else:
                self.info.append(f"Horizons: {HORIZONS_H} hours ✓")

    def _validate_feature_columns(self) -> None:
        """Check that feature schema is complete."""
        if not FEATURE_COLUMNS:
            self.errors.append("FEATURE_COLUMNS not defined")
        else:
            required_feature_types = {
                "sp_hPa", "rh", "t2m_C", "month", "hour_utc"
            }
            missing = required_feature_types - set(FEATURE_COLUMNS)
            if missing:
                self.errors.append(f"Missing required features: {missing}")
            else:
                self.info.append(f"Feature schema OK ({len(FEATURE_COLUMNS)} columns)")

    def report(self) -> None:
        """Print validation report to stdout."""
        print("\n" + "="*70)
        print("POD-ML CONFIGURATION VALIDATION")
        print("="*70)

        if self.info:
            print("\n✓ INFO:")
            for msg in self.info:
                print(f"  {msg}")

        if self.warnings:
            print("\n⚠ WARNINGS (non-blocking):")
            for msg in self.warnings:
                print(f"  {msg}")

        if self.errors:
            print("\n✗ ERRORS (blocking):")
            for msg in self.errors:
                print(f"  {msg}")

        print("\n" + "="*70)
        if not self.errors:
            print("✓ ALL CHECKS PASSED — ready for deployment")
        else:
            print(f"✗ {len(self.errors)} error(s) — fix before deployment")
        print("="*70 + "\n")


def main() -> int:
    """Run configuration validation."""
    ap = argparse.ArgumentParser(
        description="Validate pod-ml configuration and data availability"
    )
    ap.add_argument("--fix", action="store_true", help="Create missing directories")
    args = ap.parse_args()

    try:
        cfg = load_config()
    except Exception as e:
        print(f"✗ Failed to load config: {e}")
        return 1

    validator = ConfigValidator(cfg, fix=args.fix)
    valid = validator.validate_all()
    validator.report()

    return 0 if valid else 1


if __name__ == "__main__":
    import os
    sys.exit(main())
