"""Early grid test: probe.py with static features (elevation + climatology).

MVP approach:
  1. Use existing 5 probe points (not full grid yet)
  2. Add elevation + 20yr climatology as features
  3. Re-train on this enriched feature set
  4. Compare skill vs baseline (no static features)

This tests the hypothesis: "Adding geographic context fixes Christchurch bias"

Once ERA5 grid available, scale to 8000+ cells.

Usage:
    python -m podml.probe_with_static           # Train with static features
    python -m podml.probe_with_static --no-static  # Baseline (for comparison)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.metrics import average_precision_score

from podml.config import load_config
from podml.era5_load import load_point_from_grid
from podml.features import build_features_from_signals, raw_signals
from podml.labels import HORIZONS_H, THRESHOLDS_MM_HR, build_labels
from podml.sensorsim import SensorSimParams, degrade_signals
from podml.static_features import add_static_to_features, load_dem_grid

TRAIN_YEARS = range(2010, 2023)
TEST_YEAR = 2024


def brier_score(p: np.ndarray, y: np.ndarray) -> float:
    """Brier Score: mean squared error of probabilities."""
    return float(np.mean((p - y) ** 2))


def operating_point_metrics(y: np.ndarray, p: np.ndarray, target_recall: float = 0.70) -> dict:
    """Confusion metrics at target recall."""
    y = np.asarray(y)
    p = np.asarray(p)
    pos = int(y.sum())
    if pos == 0 or pos == len(y):
        return {}
    order = np.argsort(-p)
    recall_cum = np.cumsum(y[order]) / pos
    k = min(max(int(np.searchsorted(recall_cum, target_recall)) + 1, 1), len(y))
    thr = p[order][k - 1]
    pred = p >= thr
    tp = int((pred & (y == 1)).sum())
    fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum())
    tn = int((~pred & (y == 0)).sum())
    return {
        "precision": tp / (tp + fp) if tp + fp else np.nan,
        "recall": tp / (tp + fn) if tp + fn else np.nan,
        "false_alarm_rate": fp / (fp + tn) if fp + tn else np.nan,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
    }


def probe_point(
    name: str,
    cfg: dict,
    use_static: bool = True,
    sensor_sim: bool = False,
    importances: list | None = None,
) -> pd.DataFrame:
    """Train with optional static features (elevation + climatology).

    Args:
        name: probe point name
        cfg: config dict
        use_static: include elevation + climatology features
        sensor_sim: degrade inputs for deployable skill estimate
        importances: list to accumulate feature importance

    Returns:
        pd.DataFrame with skill metrics for all thresholds/horizons
    """
    ds = load_point_from_grid(name, cfg)
    signals = raw_signals(ds)
    feats_train = build_features_from_signals(signals)

    if sensor_sim:
        seed = 1000 + sorted(cfg["probe_points"]).index(name)
        rng = np.random.default_rng(seed)
        feats_eval = build_features_from_signals(degrade_signals(signals, SensorSimParams(), rng))
    else:
        feats_eval = feats_train

    # Add static features (elevation + climatology)
    if use_static:
        try:
            dem = load_dem_grid()
            pt = cfg["probe_points"][name]
            feats_train = add_static_to_features(feats_train, pt["lat"], pt["lon"], dem=dem)
            feats_eval = add_static_to_features(feats_eval, pt["lat"], pt["lon"], dem=dem)
        except Exception as e:
            print(f"  Warning: could not add static features to {name}: {e}")
            # Continue with dynamic features only

    labels = build_labels(ds, horizons=HORIZONS_H, thresholds=THRESHOLDS_MM_HR)
    train_data = feats_train.join(labels)
    eval_data = feats_eval.join(labels)
    train_mask = train_data.index.year.isin(list(TRAIN_YEARS))
    test_mask = eval_data.index.year == TEST_YEAR

    rows = []
    feature_cols = list(feats_train.columns)

    for h in HORIZONS_H:
        for thr in THRESHOLDS_MM_HR:
            col = f"ge{thr}_h{h}"
            cols = feature_cols + [col]
            tr = train_data.loc[train_mask, cols].dropna()
            te = eval_data.loc[test_mask, cols].dropna()
            ytr, yte = tr[col].to_numpy(), te[col].to_numpy()
            base_rate = float(yte.mean()) if len(yte) else np.nan

            row = {
                "point": name,
                "threshold_mm_hr": thr,
                "horizon_h": h,
                "n_train": len(tr),
                "n_test": len(te),
                "base_rate": base_rate,
                "bss": np.nan,
                "pr_auc": np.nan,
                "pr_auc_lift": np.nan,
                "precision": np.nan,
                "recall": np.nan,
                "false_alarm_rate": np.nan,
                "tp": np.nan,
                "fp": np.nan,
                "fn": np.nan,
                "tn": np.nan,
            }

            if len(te) and 0 < ytr.mean() < 1 and 0 < yte.mean() < 1:
                clim_by_month = tr.groupby(tr.index.month)[col].mean()
                clim_p = te.index.month.map(clim_by_month).to_numpy()
                clim_p = np.where(np.isfinite(clim_p), clim_p, ytr.mean())

                model = LGBMClassifier(
                    n_estimators=300,
                    learning_rate=0.05,
                    num_leaves=31,
                    subsample=0.8,
                    colsample_bytree=0.8,
                    importance_type="gain",
                    random_state=42,
                    verbose=-1,
                )
                model.fit(tr[feature_cols], ytr)
                p = model.predict_proba(te[feature_cols])[:, 1]

                if importances is not None:
                    for feat, gain in zip(feature_cols, model.feature_importances_):
                        importances.append(
                            {
                                "point": name,
                                "threshold_mm_hr": thr,
                                "horizon_h": h,
                                "feature": feat,
                                "gain": float(gain),
                            }
                        )

                bs_model = brier_score(p, yte)
                bs_clim = brier_score(clim_p, yte)
                row["bss"] = 1.0 - bs_model / bs_clim if bs_clim > 0 else np.nan
                row["pr_auc"] = float(average_precision_score(yte, p))
                row["pr_auc_lift"] = row["pr_auc"] / base_rate if base_rate > 0 else np.nan
                row.update(operating_point_metrics(yte, p))

            rows.append(row)

    return pd.DataFrame(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description="Probe skill with optional static features")
    ap.add_argument("--no-static", action="store_true", help="Disable static features (elevation, climatology)")
    ap.add_argument(
        "--sensor-sim",
        action="store_true",
        help="Evaluate on sensor-degraded inputs",
    )
    args = ap.parse_args()

    cfg = load_config()
    points = list(cfg["probe_points"])
    use_static = not args.no_static
    mode = "SENSOR-SIM" if args.sensor_sim else "CLEAN"
    static_mode = "WITH static features (elevation+climatology)" if use_static else "WITHOUT static features"

    print(f"Rain skill probe — {mode} — {static_mode} — {len(points)} points")
    print(f"Train {TRAIN_YEARS.start}-{TRAIN_YEARS.stop - 1} | embargo 2023 | test {TEST_YEAR}\n")

    importances: list = []
    results = pd.concat(
        [probe_point(p, cfg, use_static=use_static, sensor_sim=args.sensor_sim, importances=importances) for p in points],
        ignore_index=True,
    )

    out_dir = Path(__file__).resolve().parents[2] / "outputs"
    out_dir.mkdir(exist_ok=True)
    suffix = f"{'_sim' if args.sensor_sim else ''}{'_static' if use_static else '_no_static'}"
    results.to_csv(out_dir / f"skill_probe{suffix}.csv", index=False)

    print("=== Brier Skill Score vs climatology (positive = beats 'knowing the season') ===")
    for thr in THRESHOLDS_MM_HR:
        sub = results[results.threshold_mm_hr == thr]
        piv = sub.pivot(index="point", columns="horizon_h", values="bss")
        print(f"\n-- rain >= {thr} mm/hr --")
        print(piv.round(3).to_string())

    print("\n\n### Confusion breakdown at ~70% catch (recall held ~0.70) ###")
    for metric, blurb in [
        ("false_alarm_rate", "FALSE-ALARM rate FP/(FP+TN) — cry-wolf, lower better"),
        ("precision", "PRECISION — of warnings, fraction that were real, higher better"),
    ]:
        print(f"\n=== {blurb} ===")
        for thr in THRESHOLDS_MM_HR:
            sub = results[results.threshold_mm_hr == thr]
            piv = sub.pivot(index="point", columns="horizon_h", values=metric)
            print(f"-- rain >= {thr} mm/hr --")
            print(piv.round(3).to_string())

    if importances:
        imp_df = pd.DataFrame(importances)
        imp_df.to_csv(out_dir / f"feature_importance{suffix}.csv", index=False)
        mean_imp = imp_df.groupby("feature")["gain"].mean().sort_values(ascending=False)
        print("\n=== mean feature importance (gain) across all models ===")
        print(mean_imp.round(0).to_string())

    print(f"\nFull results -> {out_dir / f'skill_probe{suffix}.csv'}")


if __name__ == "__main__":
    main()
