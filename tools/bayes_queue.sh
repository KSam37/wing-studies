#!/usr/bin/env bash
# Bayesian optimization pilot, queued behind every other run on this machine.
#
#   bash tools/bayes_queue.sh [WORKERS] [SOLVES]
#
# Waits until no "python -m wingstudy..." process is running at two checks 5 minutes apart (so it starts whether the
# runs ahead of it finish or crash), then runs wingstudy.bayes_search at 1, 1.25 and 0.75 Hz, one after another, and
# copies each results.json to atlas/bayes/<name>.json for tools/build_site.py. A rerun resumes from each trace.jsonl.
set -u
cd "$(dirname "$0")/.."
W=${1:-21}
N=${2:-1000}
PY=${PY:-/c/Users/SamKi/AppData/Local/WingStudies/environments/2e1977f87f88a0c1/Scripts/python.exe}
export PYTHONPATH=. PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1 NUMBA_CACHE_DIR="${LOCALAPPDATA:-}/WingStudies/numba"
export NUMBA_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1

busy() {
  powershell.exe -NoProfile -Command "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\").CommandLine" 2>/dev/null \
    | grep -- "-m wingstudy" | grep -v "bayes_search" | grep -c .
}
echo "$(date '+%F %T') waiting for other wingstudy runs"
quiet=0
while [ $quiet -lt 2 ]; do
  if [ "$(busy)" -eq 0 ]; then quiet=$((quiet + 1)); else quiet=0; fi
  [ $quiet -lt 2 ] && sleep 300
done
echo "$(date '+%F %T') machine free; starting"
mkdir -p atlas/bayes
for f in 1.0 1.25 0.75; do
  name=$(printf 'f%.2f' "$f" | tr . p)
  "$PY" -m wingstudy.bayes_search --freq "$f" --solves "$N" --workers "$W" > "outputs/bayes-$name.log" 2>&1
  echo "$(date '+%F %T') $name exit $?: $(tail -1 "outputs/bayes-$name.log")"
  [ -f "outputs/bayes/$name/results.json" ] && cp "outputs/bayes/$name/results.json" "atlas/bayes/$name.json"
done
echo "$(date '+%F %T') all done"
