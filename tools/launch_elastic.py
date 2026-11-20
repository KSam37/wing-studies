"""Launch this source checkout using its (or an ancestor's) configured environment."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

root = Path(__file__).resolve().parent.parent
local = Path(os.environ["LOCALAPPDATA"])/"WingStudies"
locations = [local, Path.home()/"AppData"/"Local"/"WingStudies"]
python = None
for checkout in (root,*root.parents):
    key = hashlib.sha256(str(checkout).casefold().encode()).hexdigest()[:16]
    for location in locations:
        pointer = location/"checkouts"/(key+".json")
        if pointer.is_file():
            candidate = Path(json.loads(pointer.read_text())["python"])
            if candidate.is_file():
                python, local = candidate, location
                break
    if python is not None: break
if python is None:
    raise SystemExit("Run Setup Windows.cmd first to register a Ptera environment.")
env = dict(os.environ,NUMBA_CACHE_DIR=str(local/"numba"),OMP_NUM_THREADS="1",OPENBLAS_NUM_THREADS="1",NUMBA_NUM_THREADS="1",MPLBACKEND="Agg")
args = sys.argv[1:] or ["dashboard","--spanwise-bending","--large-deflection","--variant","plate","--workers","4"]
target="wingstudy.elastic_campaign"
if args and args[0]=="--frontier":
    target="wingstudy.span_frontier";args=args[1:]
raise SystemExit(subprocess.call([str(python),"-X","utf8","-u","-m",target,*args],cwd=root,env=env))
