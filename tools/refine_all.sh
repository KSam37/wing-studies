#!/usr/bin/env bash
# Refine every Top-tab standout: each torque budget (0.5-2 N·m), one-sheet and free-span, at 0.75, 1 and 1.25 Hz.
# Three stages per frequency, as for the earlier refinement runs:
#   1. tripled chord stations on 21 x 4 (refine_top --atlas --free-span)
#   2. 21 x 12 recheck, then a 6-control-chord smooth curve searched on 21 x 12 (--from ... --curve 6)
#   3. the study picks' own outlines on 21 x 12 (--baseline)
# Earlier refinement caches are copied in first, so seeds that were already refined cost nothing.
#   PY=path/to/python bash tools/refine_all.sh [WORKERS]
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-python}
W=${1:-20}
export NUMBA_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONUNBUFFERED=1
seed_cache() { mkdir -p "$1"; [ -s "$1/cache.jsonl" ] || cat outputs/refine-top*/cache.jsonl > "$1/cache.jsonl" 2>/dev/null || true; }
for f in 1.25 0.75 1; do
  o=outputs/refine-all-f$f
  echo "== $f Hz: stage 1 $(date +%T)"
  seed_cache "$o"
  "$PY" -m wingstudy.refine_top --atlas --freq "$f" --free-span --workers "$W" --out "$o"
  echo "== $f Hz: stage 2 $(date +%T)"
  seed_cache "$o-curve"
  "$PY" -m wingstudy.refine_top --from "$o/summary.json" --freq "$f" --chord-panels 12 --curve 6 --workers "$W" --out "$o-curve"
  echo "== $f Hz: baseline $(date +%T)"
  seed_cache "$o-baseline"
  "$PY" -m wingstudy.refine_top --from "$o/summary.json" --freq "$f" --chord-panels 12 --baseline --workers "$W" --out "$o-baseline"
done
echo "== animations $(date +%T)"
"$PY" -m wingstudy.top_media atlas/refine-top/*/stage2.json outputs/refine-all-f*-curve/summary.json --workers 4
echo "== done $(date +%T)"
