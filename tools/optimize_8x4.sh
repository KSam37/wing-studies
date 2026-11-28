#!/usr/bin/env bash
# Optimize every Top-tab winner on the 8 x 4 search mesh, starting from the exact wing (refine_top --search-mesh),
# after the higher-frequency sweep (wingstudy.freq_explore) has finished.
#   1. pooled: the best wing under each budget at whichever frequency, one sheet and any span (the Top tab's
#      "All frequencies" cards)
#   2. per frequency: the best wing under each budget at each frequency (the Top tab's frequency chips); seeds
#      already optimized in step 1 come from the shared cache
# Results: outputs/optimize-8x4/<run>/summary.json, published to atlas/optimize-8x4/<run>/summary.json.
#   PY=path/to/python bash tools/optimize_8x4.sh [WORKERS]
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-python}
W=${1:-17}
export NUMBA_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONUNBUFFERED=1
FREQS="0.75 1 1.25 1.5 2 5"
until [ -s outputs/freq-explore/results.json ]; do sleep 120; done
cp outputs/freq-explore/results.json atlas/freq-explore.json
EXTRA="atlas/freq-explore.json atlas/frequency-sweep.json"
O=outputs/optimize-8x4
mkdir -p "$O/pooled"
echo "== pooled $(date +%T)"
"$PY" -m wingstudy.refine_top --atlas --free-span --search-mesh --pool-freqs $FREQS --extra-cases $EXTRA --workers "$W" --out "$O/pooled"
mkdir -p atlas/optimize-8x4/pooled && cp "$O/pooled/summary.json" atlas/optimize-8x4/pooled/
for f in $FREQS; do
  echo "== $f Hz $(date +%T)"
  mkdir -p "$O/f$f"
  [ -s "$O/f$f/cache.jsonl" ] || cp "$O/pooled/cache.jsonl" "$O/f$f/cache.jsonl"
  "$PY" -m wingstudy.refine_top --atlas --free-span --search-mesh --freq "$f" --extra-cases $EXTRA --workers "$W" --out "$O/f$f"
  mkdir -p "atlas/optimize-8x4/f$f" && cp "$O/f$f/summary.json" "atlas/optimize-8x4/f$f/"
  cat "$O/f$f/cache.jsonl" >> "$O/pooled/cache.jsonl"
done
echo "== done $(date +%T)"
