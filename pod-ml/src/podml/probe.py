"""Step 5 (dress rehearsal) — point skill probe.

Question: does a single point's sensor state (pressure/temp/humidity tendencies) beat *climatology*
at predicting rain, and at which horizon? Reports Brier Skill Score (BSS) vs a month-of-year
climatology baseline — the honest "does the sensor beat just knowing the season" number.

OPTIMISTIC: ERA5 labels (circular) + clean features (no sensor-sim). This is the ceiling, not the
deployable number. If skill is absent *here*, GPM won't rescue it; if present, GPM confirms it honestly.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.metrics import average_precision_score

from podml.config import DATA_RAW, load_config
from podml.dataio import load_timeseries
from podml.features import FEATURE_COLUMNS, build_features_from_signals, raw_signals
from podml.labels import HORIZONS_H, THRESHOLDS_MM_HR, build_labels
from podml.sensorsim import SensorSimParams, degrade_signals

TRAIN_YEARS = range(2010, 2023)  # 2010–2022
TEST_YEAR = 2024                 # 2023 is left as an embargo gap (>> any horizon)


def brier_score(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def _point_path(name: str, cfg: dict) -> "object":
    t = cfg["time"]
    tag = f"{t['acquisition_start']}_{t['test_year']}-12-31"
    return DATA_RAW / f"era5land_ts_{name}_{tag}.nc"


def probe_point(name: str, cfg: dict, importances: list | None = None,
                sensor_sim: bool = False) -> pd.DataFrame:
    ds = load_timeseries(_point_path(name, cfg))
    signals = raw_signals(ds)
    feats_train = build_features_from_signals(signals)  # lab conditions: clean ERA5
    if sensor_sim:
        # Deployment: evaluate on sensor-degraded inputs — the honest sim-to-real gap.
        seed = 1000 + sorted(cfg["probe_points"]).index(name)
        rng = np.random.default_rng(seed)
        feats_eval = build_features_from_signals(degrade_signals(signals, SensorSimParams(), rng))
    else:
        feats_eval = feats_train
    labels = build_labels(ds, horizons=HORIZONS_H, thresholds=THRESHOLDS_MM_HR)
    train_data = feats_train.join(labels)
    eval_data = feats_eval.join(labels)
    train_mask = train_data.index.year.isin(list(TRAIN_YEARS))
    test_mask = eval_data.index.year == TEST_YEAR

    rows = []
    for h in HORIZONS_H:
        for thr in THRESHOLDS_MM_HR:
            col = f"ge{thr}_h{h}"
            cols = FEATURE_COLUMNS + [col]
            tr = train_data.loc[train_mask, cols].dropna()
            te = eval_data.loc[test_mask, cols].dropna()
            ytr, yte = tr[col].to_numpy(), te[col].to_numpy()
            base_rate = float(yte.mean()) if len(yte) else np.nan

            row = {"point": name, "threshold_mm_hr": thr, "horizon_h": h,
                   "n_train": len(tr), "n_test": len(te), "base_rate": base_rate,
                   "bss": np.nan, "pr_auc": np.nan, "pr_auc_lift": np.nan}

            # Need both classes present in train, and a non-degenerate test set.
            if len(te) and 0 < ytr.mean() < 1 and 0 < yte.mean() < 1:
                # Climatology baseline = month-of-year positive rate learned on TRAIN.
                clim_by_month = tr.groupby(tr.index.month)[col].mean()
                clim_p = te.index.month.map(clim_by_month).to_numpy()
                clim_p = np.where(np.isfinite(clim_p), clim_p, ytr.mean())

                # No scale_pos_weight: keep probabilities CALIBRATED so Brier/BSS is honest.
                # (The rehearsal's negative BSS was that weight inflating probs; PR-AUC was fine.)
                model = LGBMClassifier(
                    n_estimators=300, learning_rate=0.05, num_leaves=31,
                    subsample=0.8, colsample_bytree=0.8,
                    importance_type="gain", random_state=42, verbose=-1,
                )
                model.fit(tr[FEATURE_COLUMNS], ytr)
                p = model.predict_proba(te[FEATURE_COLUMNS])[:, 1]
                if importances is not None:
                    for feat, gain in zip(FEATURE_COLUMNS, model.feature_importances_):
                        importances.append({"point": name, "threshold_mm_hr": thr,
                                            "horizon_h": h, "feature": feat, "gain": float(gain)})

                bs_model = brier_score(p, yte)
                bs_clim = brier_score(clim_p, yte)
                row["bss"] = 1.0 - bs_model / bs_clim if bs_clim > 0 else np.nan
                row["pr_auc"] = float(average_precision_score(yte, p))
                row["pr_auc_lift"] = row["pr_auc"] / base_rate if base_rate > 0 else np.nan
            rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    import argparse
    from pathlib import Path

    ap = argparse.ArgumentParser(description="Point skill probe (dress rehearsal).")
    ap.add_argument("--sensor-sim", action="store_true",
                    help="evaluate on sensor-degraded inputs (deployable number, not the clean ceiling)")
    args = ap.parse_args()

    cfg = load_config()
    points = list(cfg["probe_points"])
    suffix = "_sim" if args.sensor_sim else ""
    mode = "SENSOR-SIM (train clean / test degraded)" if args.sensor_sim else "CLEAN (optimistic ceiling)"
    print(f"Dress-rehearsal skill probe — {mode} — {len(points)} points")
    print(f"Train {TRAIN_YEARS.start}-{TRAIN_YEARS.stop - 1} | embargo 2023 | test {TEST_YEAR}\n")

    importances: list = []
    results = pd.concat([probe_point(p, cfg, importances, args.sensor_sim) for p in points],
                        ignore_index=True)

    out_dir = Path(__file__).resolve().parents[2] / "outputs"
    out_dir.mkdir(exist_ok=True)
    results.to_csv(out_dir / f"skill_probe{suffix}.csv", index=False)

    print("=== Brier Skill Score vs climatology (positive = beats 'knowing the season') ===")
    for thr in THRESHOLDS_MM_HR:
        sub = results[results.threshold_mm_hr == thr]
        piv = sub.pivot(index="point", columns="horizon_h", values="bss")
        print(f"\n-- threshold >= {thr} mm/hr --")
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
