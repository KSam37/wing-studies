#!/usr/bin/env bash
# Optimize the Top-tab winners on 21 x 12 panels. The best wing under each budget (0.75, 1, 1.25, 1.5 N·m) is picked
# on the 8 x 4 search mesh every atlas wing is compared on, at whichever frequency gives the most thrust, one sheet
# and any span, any root chord. Each pick is put on 3x the stations, solved as is on 21 x 12 (recheck), then searched
# as a smooth curve through 6 control chords plus the half-span on 21 x 12, with torque measured on that mesh.
# Waits for the runs that add seeds: the 1.25 Hz budget sweep, the small-root study and the 1.5 and 2 Hz runs
# (outputs/freq-explore for 2 Hz, outputs/freq-explore-1p5 for 1.5 Hz), whose results are merged into
# atlas/freq-explore.json first.
# Result: outputs/fine-top/pooled/summary.json -> atlas/fine-top/pooled/summary.json
#   PY=path/to/python bash tools/optimize_fine.sh [WORKERS]
set -euo pipefail
cd "$(dirname "$0")/.."
PY=${PY:-python}
W=${1:-21}
export NUMBA_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 PYTHONUNBUFFERED=1
for f in studies/2026-11-27-budgets-1p25hz/results.json studies/2026-11-27-small-root/results.json \
         outputs/freq-explore/results.json outputs/freq-explore-1p5/results.json; do
  until [ -s "$f" ]; do sleep 120; done
done
"$PY" - <<'PYEOF'
import json
a, b = (json.load(open(p, encoding="utf-8")) for p in ("outputs/freq-explore/results.json", "outputs/freq-explore-1p5/results.json"))
a["freqs"] = sorted(set(a["freqs"]) | set(b["freqs"]))
a["results"] = a["results"] + b["results"]
json.dump(a, open("atlas/freq-explore.json", "w", encoding="utf-8"), indent=1)
print("atlas/freq-explore.json:", a["freqs"], len(a["results"]), "results")
PYEOF
O=outputs/fine-top/pooled
mkdir -p "$O"
echo "== fine $(date +%T)"
"$PY" -m wingstudy.refine_top --atlas --free-span --pool-freqs 0.75 1 1.25 1.5 2 --levels 0.75 1 1.25 1.5 \
  --extra-cases atlas/freq-explore.json atlas/frequency-sweep.json --chord-panels 12 --curve 6 --workers "$W" --out "$O"
mkdir -p atlas/fine-top/pooled
cp "$O/summary.json" atlas/fine-top/pooled/summary.json
echo "== done $(date +%T)"
