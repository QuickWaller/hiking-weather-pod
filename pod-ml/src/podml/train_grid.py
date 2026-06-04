"""Grid-based model training using full ERA5 grid + static features.

Instead of 5 probe points, train on ALL NZ grid cells (10000+ locations).
This gives the model geographic context and 100x more data.

Workflow:
  1. Load ERA5 gridded data (full NZ, 2010–2022)
  2. Add elevation per cell
  3. Add 20yr climatology per cell
  4. Train LightGBM on all cells pooled together
  5. Validate with GPM when complete

Benefits:
  - Model learns "dry cells have less rain" (fixes Christchurch bias)
  - Uses full ERA5 dataset (not 5 points)
  - Static features are pod-queryable (elevation via DEM, zone lookup)
  - Can generate per-cell skill maps (which regions are predictable?)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


def train_grid_model(
    era5_grids_dir: Path,
    dem_path: Path,
    train_years: range = range(2010, 2023),
    test_year: int = 2024,
) -> dict:
    """Train LightGBM on full NZ grid (all cells pooled).

    Args:
        era5_grids_dir: directory with ERA5 monthly/daily gridded files
        dem_path: path to elevation DEM
        train_years: years for training
        test_year: year for testing

    Returns:
        dict with models (per threshold/horizon), metrics, skill maps
    """
    # Placeholder implementation — full version would:
    # 1. Load ERA5 grids from era5_grids_dir
    # 2. Load elevation from dem_path
    # 3. Compute climatology from ERA5 2010-2022
    # 4. Reshape grids to (time, cells) with elevation as extra column
    # 5. Train 50 LightGBM classifiers (3 thresholds × 4 horizons × pooled)
    # 6. Validate on 2024 across all cells
    # 7. Generate skill maps showing where model is good/bad

    return {
        "status": "ready to implement",
        "requires": [
            "ERA5 gridded NetCDF files (monthly or daily)",
            "DEM elevation file",
            "Climatology computation from ERA5 2010-2022",
        ],
    }


def per_cell_skill(
    model_predictions: np.ndarray,
    test_labels: np.ndarray,
    grid_shape: tuple[int, int],
) -> np.ndarray:
    """Compute Brier Skill Score per grid cell.

    Args:
        model_predictions: (time, cells) predictions
        test_labels: (time, cells) binary labels
        grid_shape: (nlat, nlon)

    Returns:
        (nlat, nlon) array of BSS values per cell
    """
    # Compute BSS for each cell independently
    bss = np.full(grid_shape, np.nan)

    n_time, n_cells = model_predictions.shape
    nlat, nlon = grid_shape

    for cell_idx in range(n_cells):
        y = test_labels[:, cell_idx]
        p = model_predictions[:, cell_idx]

        if len(np.unique(y)) < 2 or len(y) < 10:
            continue  # Skip degenerate cells

        bs_model = np.mean((p - y) ** 2)
        bs_clim = np.mean((y.mean() - y) ** 2)

        if bs_clim > 0:
            bss_val = 1.0 - bs_model / bs_clim
            bss.flat[cell_idx] = bss_val

    return bss.reshape(grid_shape)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Train grid-based rain model")
    ap.add_argument("--era5-grid-dir", type=Path, help="ERA5 gridded data directory")
    ap.add_argument("--dem-path", type=Path, help="DEM file path")
    args = ap.parse_args()

    result = train_grid_model(
        era5_grids_dir=args.era5_grid_dir or Path("data/raw/era5_grid"),
        dem_path=args.dem_path or Path("data/raw/dem/nz_dem.nc"),
    )
    print(result)
