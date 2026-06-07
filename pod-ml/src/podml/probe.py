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

from podml.config import load_config
from podml.era5_load import load_point_from_grid
from podml.features import FEATURE_COLUMNS, build_features_from_signals, raw_signals
from podml.labels import HORIZONS_H, THRESHOLDS_MM_HR, build_labels
from podml.labels_gpm import build_labels_gpm
from podml.sensorsim import SensorSimParams, degrade_signals

TRAIN_YEARS = range(2010, 2023)  # 2010–2022
TEST_YEAR = 2024                 # 2023 is left as an embargo gap (>> any horizon)


def brier_score(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def operating_point_metrics(y: np.ndarray, p: np.ndarray, target_recall: float = 0.70) -> dict:
    """At the threshold that catches ~target_recall of events, return the confusion breakdown.

    Answers the safety question BSS can't: to catch most dangerous spells, how many warnings are
    false (cry-wolf)? precision = of warnings, how many real · recall = of events, how many caught ·
    false_alarm_rate = of calm periods, how many wrongly warned (FP/(FP+TN)).
    """
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
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
    }


def probe_point(name: str, cfg: dict, importances: list | None = None,
                sensor_sim: bool = False, label_source: str = "era5") -> pd.DataFrame:
    ds = load_point_from_grid(name, cfg)
    signals = raw_signals(ds)
    feats_train = build_features_from_signals(signals)  # lab conditions: clean ERA5
    if sensor_sim:
        # Deployment: evaluate on sensor-degraded inputs — the honest sim-to-real gap.
        seed = 1000 + sorted(cfg["probe_points"]).index(name)
        rng = np.random.default_rng(seed)
        feats_eval = build_features_from_signals(degrade_signals(signals, SensorSimParams(), rng))
    else:
        feats_eval = feats_train

    # Load labels: ERA5 for training (2010–2022), selected source for testing (2024).
    # This tests whether ERA5-trained models transfer to honest labels.
    labels_train = build_labels(ds, horizons=HORIZONS_H, thresholds=THRESHOLDS_MM_HR)
    if label_source == "gpm":
        pt = cfg["probe_points"][name]
        labels_test = build_labels_gpm(lat=pt["lat"], lon=pt["lon"],
                                       horizons=HORIZONS_H, thresholds=THRESHOLDS_MM_HR)
    else:
        labels_test = labels_train

    train_data = feats_train.join(labels_train)
    eval_data = feats_eval.join(labels_test)
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
                   "bss": np.nan, "pr_auc": np.nan, "pr_auc_lift": np.nan,
                   "precision": np.nan, "recall": np.nan, "false_alarm_rate": np.nan,
                   "tp": np.nan, "fp": np.nan, "fn": np.nan, "tn": np.nan}

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
                row.update(operating_point_metrics(yte, p))
            rows.append(row)
    return pd.DataFrame(rows)


def main() -> None:
    import argparse
    from pathlib import Path

    ap = argparse.ArgumentParser(description="Point skill probe (dress rehearsal).")
    ap.add_argument("--sensor-sim", action="store_true",
                    help="evaluate on sensor-degraded inputs (deployable number, not the clean ceiling)")
    ap.add_argument("--label-source", choices=["era5", "gpm"], default="era5",
                    help="ERA5 = optimistic (circular, same physics as features); GPM = honest (satellite-measured)")
    args = ap.parse_args()

    cfg = load_config()
    points = list(cfg["probe_points"])
    suffix = f"{'_sim' if args.sensor_sim else ''}_{args.label_source}"
    mode = "SENSOR-SIM (train clean / test degraded)" if args.sensor_sim else "CLEAN (optimistic ceiling)"
    labels_mode = "GPM (satellite-measured, honest)" if args.label_source == "gpm" else "ERA5 (optimistic, circular)"
    print(f"Rain skill probe — {mode} — {labels_mode} — {len(points)} points")
    print(f"Train {TRAIN_YEARS.start}-{TRAIN_YEARS.stop - 1} | embargo 2023 | test {TEST_YEAR}\n")

    importances: list = []
    results = pd.concat([probe_point(p, cfg, importances, args.sensor_sim, args.label_source)
                        for p in points],
                        ignore_index=True)

    out_dir = Path(__file__).resolve().parents[2] / "outputs"
    out_dir.mkdir(exist_ok=True)
    results.to_csv(out_dir / f"skill_probe{suffix}.csv", index=False)

    print("=== Brier Skill Score vs climatology (positive = beats 'knowing the season') ===")
    for thr in THRESHOLDS_MM_HR:
        sub = results[results.threshold_mm_hr == thr]
        piv = sub.pivot(index="point", columns="horizon_h", values="bss")
        print(f"\n-- rain >= {thr} mm/hr --")
        print(piv.round(3).to_string())

    print("\n\n### Confusion breakdown at ~70% catch (recall held ~0.70; raw TP/FP/FN/TN in the CSV) ###")
    for metric, blurb in [("false_alarm_rate", "FALSE-ALARM rate FP/(FP+TN) — cry-wolf, lower better"),
                          ("precision", "PRECISION — of warnings, fraction that were real, higher better")]:
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
