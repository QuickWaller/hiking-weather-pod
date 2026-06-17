#!/bin/bash
# Overnight bake-off: train rain-emphasised (E) + not-emphasised (N) at production scale, score each
# 4 ways (quantile heads vs Tweedie-CDF read-off), pick the winner, build the referee + figures.
# Detached + robust: a failed step still leaves the prior artefacts. Reports land in experiments/v2_report.
set -u
cd ~/cyber-deck-and-weather-station/pod-ml
PY=.venv/bin/python
CACHE=outputs/ensemble/dataset_v2
TF=0.7        # train-frac (fits 13GB+swap, close to full)
BAG=0.4       # bagging_fraction — makes the quantile heads tractable via per-tree subsample
ED=outputs/bakeoff_E
ND=outputs/bakeoff_N
OUT=outputs/bakeoff

echo "=== OVERNIGHT BAKEOFF START $(date) ==="
rm -f bakeoff_pipeline.done

train_and_stash () {   # $1=label $2=extra-flags $3=dest-dir $4=log
  echo "=== train $1 $(date) ==="
  $PY -m podml.train_ensemble --from-cache --cache-dir "$CACHE" --conformal \
      --train-frac $TF --bagging $BAG $2 --seed 42 > "$4" 2>&1
  rm -rf "$3"; mkdir -p "$3"
  cp -r outputs/ensemble/models "$3/models" 2>/dev/null
  cp outputs/ensemble/cell_weights.json outputs/ensemble/conformal_corrections.json \
     outputs/ensemble/metrics_overall.csv outputs/ensemble/coverage.csv \
     outputs/ensemble/confusion_sweep.csv outputs/ensemble/confusion_fixed.csv "$3/" 2>/dev/null
  echo "=== $1 done $(date) ==="; tail -3 "$4"
}

# 1. rain-emphasised (harvest ON)
train_and_stash "E (rain-emphasised)" "" "$ED" bakeoff_E.log
# 2. not-emphasised (harvest weights zeroed)
train_and_stash "N (not-emphasised)" "--no-harvest" "$ND" bakeoff_N.log

# 3. 4-way bake-off + pick winner
echo "=== bake-off eval $(date) ==="
$PY experiments/bakeoff_eval.py --e-dir "$ED" --n-dir "$ND" --cache-dir "$CACHE" --out "$OUT" \
    > bakeoff_eval.log 2>&1
cat bakeoff_eval.log

# 4. referee + figures on the winning model (falls back to E if the pick failed)
WINDIR=$($PY -c "import json;print(json.load(open('$OUT/winner.json'))['model_dir'])" 2>/dev/null || echo "$ED")
[ -d "$WINDIR/models" ] || WINDIR=$ED
echo "=== reports on winner $WINDIR $(date) ==="
$PY -m podml.report_v2 --out-dir "$WINDIR" --cache-dir "$CACHE" --fig-dir experiments/v2_report \
    > report_v2.log 2>&1
tail -14 report_v2.log

echo "ALL DONE $(date)" | tee bakeoff_pipeline.done
