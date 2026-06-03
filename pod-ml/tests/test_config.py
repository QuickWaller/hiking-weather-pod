"""Config + data-path smoke tests."""

from podml.config import CONFIG_PATH, load_config


def test_config_loads_expected_sections():
    cfg = load_config()
    assert CONFIG_PATH.exists()
    for key in ("domain", "time", "era5_land", "gpm_imerg", "probe_points", "climatology"):
        assert key in cfg, key


def test_probe_points_have_coords():
    cfg = load_config()
    assert len(cfg["probe_points"]) == 5
    for name, p in cfg["probe_points"].items():
        assert {"lat", "lon"} <= set(p), name


def test_climatology_reference_is_train_only():
    # Recent window, but must end before the val year (2023) to avoid leakage.
    cfg = load_config()
    assert cfg["climatology"]["reference_end"] < f"{cfg['time']['val_year']}-01-01"
