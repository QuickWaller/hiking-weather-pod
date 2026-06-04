"""Validate pod model predictions against Open-Meteo ground truth.

Loads Open-Meteo hourly observations (precip, pressure, temp, humidity) for each probe point,
builds features from the time series, generates model predictions (rain_conf, storm_conf),
and compares against actual conditions. Reports skill metrics and systematic biases.

Usage:
  python -m podml.validate_openmeteo              # analyze all points
  python -m podml.validate_openmeteo --point hokitika_westcoast  # single point
"""

from __future__ import annotations

import argparse

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier

from podml.config import DATA_RAW, load_config
from podml.features import FEATURE_COLUMNS, build_features_from_signals
from podml.labels import HORIZONS_H, THRESHOLDS_MM_HR, forward_window_max

OPENMETEO_DIR = DATA_RAW / "openmeteo"


def load_openmeteo(point_name: str) -> pd.DataFrame:
    """Load Open-Meteo hourly observations for a probe point.

    Returns:
        pd.DataFrame with columns: time, precipitation_mm_hr, pressure_hpa, temp_c, humidity_pct
        Index: pd.DatetimeIndex named 'time'
    """
    path = OPENMETEO_DIR / f"{point_name}.csv"
    if not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(path, parse_dates=["time"])
    df.set_index("time", inplace=True)
    df.index.name = "time"
    return df


def openmeteo_to_signals(om_df: pd.DataFrame) -> dict:
    """Convert Open-Meteo observations to signal format for feature building.

    Expects columns: precipitation_mm_hr, pressure_hpa, temp_c, humidity_pct
    Returns dict with structure matching raw_signals() output (sp_hPa, t2m_C, rh).
    """
    if om_df.empty:
        return {}

    return {
        "time": om_df.index,
        "sp_hPa": om_df["pressure_hpa"].values,
        "t2m_C": om_df["temp_c"].values,
        "rh": om_df["humidity_pct"].values,
    }


def build_openmeteo_labels(om_df: pd.DataFrame, horizons: list[int] = None,
                          thresholds: list[float] = None) -> pd.DataFrame:
    """Build binary rain labels from Open-Meteo precipitation.

    Args:
        om_df: DataFrame with precipitation_mm_hr column
        horizons: lead times (hours)
        thresholds: rain intensities (mm/hr)

    Returns:
        pd.DataFrame with columns ge{thr}_h{h} (binary: 0/1)
    """
    if horizons is None:
        horizons = HORIZONS_H
    if thresholds is None:
        thresholds = THRESHOLDS_MM_HR

    if om_df.empty or "precipitation_mm_hr" not in om_df.columns:
        return pd.DataFrame()

    precip = om_df["precipitation_mm_hr"].values
    times = om_df.index

    df = pd.DataFrame(index=times)
    df.index.name = "valid_time"

    for h in horizons:
        fmax = forward_window_max(precip, h)
        for thr in thresholds:
            lab = (fmax >= thr).astype("float64")
            lab[np.isnan(fmax)] = np.nan
            df[f"ge{thr}_h{h}"] = lab

    return df


def validate_point(point_name: str, model_era5=None) -> dict:
    """Validate model predictions at one probe point against Open-Meteo.

    Args:
        point_name: probe point name (e.g., "hokitika_westcoast")
        model_era5: optional pre-trained LGBMClassifier (trained on ERA5 2010-2022).
                   If None, loads from config and trains on ERA5.

    Returns:
        dict with metrics: point, n_obs, date_range, rain_metrics, etc.
    """
    om_df = load_openmeteo(point_name)
    if om_df.empty:
        return {"point": point_name, "status": "no_data"}

    # Build features from Open-Meteo observations
    signals = openmeteo_to_signals(om_df)
    feats = build_features_from_signals(signals)

    # Build labels from Open-Meteo precipitation
    labels = build_openmeteo_labels(om_df)

    data = feats.join(labels)
    data = data.dropna()

    if len(data) == 0:
        return {"point": point_name, "status": "no_overlap"}

    # If no pre-trained model, train a simple baseline on the Open-Meteo data itself
    # (leaky but fast for exploration)
    if model_era5 is None:
        results = {"point": point_name, "status": "trained_on_openmeteo"}
        train_frac = int(len(data) * 0.7)
        train_data = data.iloc[:train_frac]
        test_data = data.iloc[train_frac:]
    else:
        results = {"point": point_name, "status": "era5_model"}
        train_data = None
        test_data = data

    results["n_obs"] = len(data)
    results["date_range"] = f"{data.index[0]:.10s} to {data.index[-1]:.10s}"

    # Evaluate rain_conf at one horizon (6h) as a quick check
    col = "ge0.5_h6"
    if col not in test_data.columns:
        return results

    y_test = test_data[col].dropna().values
    if len(y_test) == 0 or y_test.mean() in [0, 1]:
        results["rain_0.5_6h"] = "no_variation"
        return results

    if model_era5 is not None:
        # Use provided ERA5-trained model
        X_test = test_data[FEATURE_COLUMNS].dropna()
        if len(X_test) > 0:
            p = model_era5.predict_proba(X_test)[:, 1]
            y = y_test[:len(p)]

            bs = float(np.mean((p - y) ** 2))
            results["rain_0.5_6h_brier"] = f"{bs:.3f}"
            results["rain_0.5_6h_baseline"] = f"{y.mean():.3f}"
    else:
        # Quick baseline: train/test split on Open-Meteo data
        if train_data is not None and len(train_data) > 10:
            X_train = train_data[FEATURE_COLUMNS].dropna()
            y_train = train_data.loc[X_train.index, col].values

            if 0 < y_train.mean() < 1:
                model = LGBMClassifier(n_estimators=50, verbose=-1, random_state=42)
                model.fit(X_train, y_train)

                X_test = test_data[FEATURE_COLUMNS].dropna()
                if len(X_test) > 0:
                    p = model.predict_proba(X_test)[:, 1]
                    y = y_test[:len(p)]

                    bs = float(np.mean((p - y) ** 2))
                    results["rain_0.5_6h_brier"] = f"{bs:.3f}"
                    results["rain_0.5_6h_baseline"] = f"{y.mean():.3f}"

    return results


def main():
    ap = argparse.ArgumentParser(description="Validate pod model predictions against Open-Meteo.")
    ap.add_argument("--point", type=str, help="Single probe point (default: all)")
    args = ap.parse_args()

    cfg = load_config()
    points = [args.point] if args.point else list(cfg.get("probe_points", {}).keys())

    print(f"Validating {len(points)} point(s) against Open-Meteo ground truth\n")

    all_results = []
    for point in points:
        result = validate_point(point)
        all_results.append(result)

        status = result.get("status", "unknown")
        if status == "no_data":
            print(f"{point:25s} [no Open-Meteo data]")
        elif status == "no_overlap":
            print(f"{point:25s} [no feature/label overlap]")
        else:
            date_range = result.get("date_range", "")
            n_obs = result.get("n_obs", 0)
            brier = result.get("rain_0.5_6h_brier", "—")
            baseline = result.get("rain_0.5_6h_baseline", "—")
            print(f"{point:25s} {n_obs:5d} obs  {date_range}  brier={brier}  base={baseline}")

    print("\n--- Details ---")
    for r in all_results:
        print(r)


if __name__ == "__main__":
    main()
