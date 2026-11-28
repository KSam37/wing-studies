#!/usr/bin/env bash
# Optimize the Top-tab winners: on the 8 x 4 search mesh first (the basis every wing is compared on), then the
# pooled winners again on 21 x 12 for the Top tab.
#   1. per frequency except 1.25 Hz, once the higher-frequency sweep (wingstudy.freq_explore) has finished:
#      the best wing under each budget at each frequency (the Top tab's frequency chips), 8 x 4, from the exact wing
#   2. after the 1.25 Hz budget sweep (studies/2026-11-27-budgets-1p25hz): 1.25 Hz, then pooled (the best wing under
#      each budget at whichever frequency, one sheet and any span: the Top tab's "All frequencies" cards)
#   3. fine: each pooled 8 x 4 final on 3x the stations, searched as a smooth curve (6 control chords) on 21 x 12
#      panels under the same budget, torque measured on that mesh; plus the study picks on 21 x 12 (baseline)
# 200 mm-root wings only (refine_top.pick_seeds). The 8 x 4 runs share one cache.
# Results: outputs/optimize-8x4/<run>/summary.json -> atlas/optimize-8x4/<run>/,
#          outputs/fine-top/{pooled,pooled-baseline}/ -> atlas/fine-top/pooled/{summary,baseline}.json
#   PY=path/to/python bash tools/optimize_8x4.sh [WORKERS]
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-python}
W=${1:-17}
export NUMBA_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONUNBUFFERED=1
FREQS="0.75 1 1.25 1.5 2 5"
O=outputs/optimize-8x4
mkdir -p "$O/shared"
touch "$O/shared/cache.jsonl"

run8() {   # run8 NAME ARGS...: one 8 x 4 run on the shared cache, published to atlas/optimize-8x4/NAME
  local name=$1; shift
  echo "== $name $(date +%T)"
  mkdir -p "$O/$name"
  cp "$O/shared/cache.jsonl" "$O/$name/cache.jsonl"
  "$PY" -m wingstudy.refine_top --atlas --free-span --search-mesh --extra-cases $EXTRA --workers "$W" --out "$O/$name" "$@"
  mkdir -p "atlas/optimize-8x4/$name" && cp "$O/$name/summary.json" "atlas/optimize-8x4/$name/"
  sort -u "$O/$name/cache.jsonl" "$O/shared/cache.jsonl" -o "$O/shared/cache.jsonl"
}

until [ -s outputs/freq-explore/results.json ]; do sleep 120; done
cp outputs/freq-explore/results.json atlas/freq-explore.json
EXTRA="atlas/freq-explore.json atlas/frequency-sweep.json"
for f in 0.75 1 1.5 2 5; do run8 "f$f" --freq "$f"; done

until [ -s studies/2026-11-27-budgets-1p25hz/results.json ]; do sleep 120; done
run8 f1.25 --freq 1.25
run8 pooled --pool-freqs $FREQS

F=outputs/fine-top
mkdir -p "$F/pooled" "$F/pooled-baseline"
echo "== fine $(date +%T)"
"$PY" -m wingstudy.refine_top --from "$O/pooled/summary.json" --chord-panels 12 --curve 6 --workers "$W" --out "$F/pooled"
echo "== fine baseline $(date +%T)"
"$PY" -m wingstudy.refine_top --from "$O/pooled/summary.json" --baseline --chord-panels 12 --workers "$W" --out "$F/pooled-baseline"
mkdir -p atlas/fine-top/pooled
cp "$F/pooled/summary.json" atlas/fine-top/pooled/summary.json
cp "$F/pooled-baseline/baseline.json" atlas/fine-top/pooled/baseline.json
echo "== done $(date +%T)"
