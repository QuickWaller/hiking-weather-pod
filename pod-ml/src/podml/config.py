"""Shared project paths and config loading (single source of truth for both)."""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config" / "nz_domain.yaml"
DATA_RAW = ROOT / "data" / "raw"


def load_config() -> dict:
    """Load the NZ domain / pipeline config."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)
