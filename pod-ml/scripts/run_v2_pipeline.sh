#!/bin/bash
# v2 stratified-model pipeline — waits for the build, then trains full + no-harvest, detached.
# Non-destructive: backs up the §1b baseline models/plumes before v2 overwrites outputs/ensemble.
set -u
cd ~/cyber-deck-and-weather-station/pod-ml
PY=.venv/bin/python
BUILD_PID="${1:-}"
CACHE=outputs/ensemble/dataset_v2

echo "pipeline start $(date)"

# 1. wait for the build process to exit (if a PID was given)
if [ -n "$BUILD_PID" ]; then
  while kill -0 "$BUILD_PID" 2>/dev/null; do sleep 30; done
  echo "build finished $(date)"
fi
tail -3 v2_build.log

# 2. bail if the cache didn't build
if [ ! -d "$CACHE" ] || [ -z "$(ls -A $CACHE/X_*.parquet 2>/dev/null)" ]; then
  echo "ABORT: no v2 cache at $CACHE"; exit 1
fi

# 3. back up the §1b baseline (models + plumes are intact; CSVs already archived locally)
if [ ! -d outputs/ensemble_v1_baseline ]; then
  mkdir -p outputs/ensemble_v1_baseline
  cp -r outputs/ensemble/models outputs/ensemble_v1_baseline/models 2>/dev/null
  cp outputs/ensemble/plumes.json outputs/ensemble_v1_baseline/ 2>/dev/null
  echo "baseline backed up $(date)"
fi

# 4. v2 FULL train (mean + q50/q75/q90, conformal, confusion matrix, plumes; NO binary)
echo "=== v2 full train $(date) ==="
$PY -m podml.train_ensemble --from-cache --cache-dir "$CACHE" \
    --conformal --train-frac 0.3 --seed 42 > v2_train_full.log 2>&1
mkdir -p outputs/ensemble_v2_full
cp outputs/ensemble/metrics_overall.csv outputs/ensemble/coverage.csv \
   outputs/ensemble/pit_histogram.csv outputs/ensemble/importance.csv \
   outputs/ensemble/confusion_sweep.csv outputs/ensemble/confusion_fixed.csv \
   outputs/ensemble/cell_weights.json outputs/ensemble/conformal_corrections.json \
   outputs/ensemble_v2_full/ 2>/dev/null
cp -r outputs/ensemble/models outputs/ensemble_v2_full/models 2>/dev/null
echo "=== full train done $(date) ===" ; tail -2 v2_train_full.log

# 5. v2 NO-HARVEST train (harvest-sensitivity ablation; don't overwrite the saved v2 models)
echo "=== v2 no-harvest train $(date) ==="
$PY -m podml.train_ensemble --from-cache --cache-dir "$CACHE" \
    --conformal --train-frac 0.3 --no-harvest --no-save-models --plumes-file plumes_v2_nh.json --seed 42 \
    > v2_train_noharvest.log 2>&1
mkdir -p outputs/ensemble_v2_noharvest
cp outputs/ensemble/metrics_overall.csv outputs/ensemble/confusion_fixed.csv \
   outputs/ensemble/confusion_sweep.csv outputs/ensemble/coverage.csv \
   outputs/ensemble_v2_noharvest/ 2>/dev/null
echo "=== no-harvest done $(date) ===" ; tail -2 v2_train_noharvest.log

echo "ALL DONE $(date)" | tee v2_pipeline.done
