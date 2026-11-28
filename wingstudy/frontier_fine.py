"""Re-solve the FAAV thrust/torque frontier on the 21 x 12 mesh.

    python -m wingstudy.frontier_fine [--freqs 0.75 1 1.25] [--top 15] [--workers N] [--out DIR] [--dry]

The studies searched on 8 x 4 panels, which runs about 15 % low on thrust and torque. Rankings hold on finer
meshes, so only wings that could win need re-solving: at each frequency, every verified FAAV wing (0.5 mm sheet on
a stiff leading edge) on the thrust/torque frontier (no other wing gives more thrust for less torque), on all
spans and within one 400 mm sheet, up to 1.1x the largest budget, plus the ``--top`` highest-thrust wings at or below each torque budget in
refine_top.LEVELS, for both span settings.

Each outline is solved exactly as the refinement baselines solve study picks (refine_top --baseline): the same
8-station outline on 3x the stations with straight segments, 21 x 12 panels, 50 steps per cycle, 4 cycles, time
step halved until verified. A wing that does not verify is retried down to a quarter of the time step. Solves are
cached in OUT/cache.jsonl (seeded from the refinement caches); OUT/results.json lists one entry per wing with its
8 x 4 source and the 21 x 12 result, and is what tools/build_site.py reads (copied to atlas/frontier-fine.json).
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from . import elastic_refine as ER
from . import refine_top as RT
from .studies import spec as S

OUT = S.ROOT / "outputs" / "frontier-fine"
FREQS = (0.75, 1.0, 1.25)
QMAX = 1.1 * max(RT.LEVELS)        # frontier wings beyond the largest budget cannot win any budget


def frontier(cases: list[dict]) -> list[dict]:
    """Wings no other wing beats on both thrust (higher) and torque (lower)."""
    out, best = [], -1.0
    for c in sorted(cases, key=lambda c: (c["torque_Nm"], -c["thrust_N"])):
        if c["thrust_N"] > best:
            out.append(c)
            best = c["thrust_N"]
    return out


def select(freq: float, top: int) -> list[dict]:
    cases = RT.atlas_cases(freq)
    sheet = [c for c in cases if RT.effective_span_mm(c) <= RT.SHEET_M * 1000 + 0.5]
    pick = {}
    for group in (cases, sheet):
        for c in frontier([c for c in group if c["torque_Nm"] <= QMAX]):
            pick.setdefault(c["key"], c)
        for B in RT.LEVELS:
            for c in sorted((c for c in group if c["torque_Nm"] <= B), key=lambda c: -c["thrust_N"])[:top]:
                pick.setdefault(c["key"], c)
    return list(pick.values())


def task(c: dict, freq: float, dt=(1, 2)) -> dict:
    ctrl, span = RT.refine_outline(c["chords_mm"], c["half_span_mm"], RT.FACTOR)
    num = RT.numerics_for(len(ctrl), 12, freq=freq)
    if tuple(dt) != (1, 2):
        num["dt_refinements"] = list(dt)
    return {"key": ER.key_of("t0.50", ctrl, span, num), "model": "t0.50", "ctrl": ctrl, "span": span, "numerics": num}


def solve(t: dict) -> dict:
    r = ER._solve(t)
    if r.get("status") not in ("verified", "ok") and t["numerics"].get("dt_refinements") == [1, 2]:
        t2 = dict(t, numerics={**t["numerics"], "dt_refinements": [1, 2, 4]})
        t2["key"] = ER.key_of("t0.50", t2["ctrl"], t2["span"], t2["numerics"])
        r = {**ER._solve(t2), "retry_of": t["key"]}
        r["key"] = t["key"]                       # cached under the first key: one entry per wing
    return r


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m wingstudy.frontier_fine", description=__doc__.split("\n\n")[0])
    ap.add_argument("--freqs", type=float, nargs="+", default=list(FREQS))
    ap.add_argument("--top", type=int, default=10, help="highest-thrust wings per budget and span setting (default 10)")
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    wings = []
    for f in a.freqs:
        sel = select(f, a.top)
        print(f"{f:g} Hz: {len(sel)} wings", flush=True)
        wings += [(c, f, task(c, f)) for c in sel]
    a.out.mkdir(parents=True, exist_ok=True)
    cache_path, cache = a.out / "cache.jsonl", {}
    if not cache_path.exists():                        # seed from the refinement caches (baselines share keys)
        with cache_path.open("w", encoding="utf-8") as fh:
            for p in sorted((S.ROOT / "outputs").glob("refine-*/cache.jsonl")):
                fh.write(p.read_text(encoding="utf-8"))
    for line in cache_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            cache[r["key"]] = r
    todo = {t["key"]: t for _, _, t in wings if t["key"] not in cache}
    print(f"{len(wings)} wings, {len(todo)} to solve ({len(wings) - len(todo)} cached)", flush=True)
    if a.dry:
        return 0
    if todo:
        with ProcessPoolExecutor(max_workers=a.workers) as pool, cache_path.open("a", encoding="utf-8") as fh:
            jobs = [pool.submit(solve, t) for t in sorted(todo.values(), key=lambda t: -t["span"])]
            for n, job in enumerate(as_completed(jobs), 1):
                r = job.result()
                cache[r["key"]] = r
                fh.write(json.dumps(r) + "\n")
                fh.flush()
                print(time.strftime("%H:%M:%S"), f"{n}/{len(todo)}", r["key"], r.get("status"), r.get("thrust"), r.get("torque"), flush=True)
    out = []
    for c, f, t in wings:
        r = cache.get(t["key"]) or {}
        out.append({"key": c["key"], "study": c["study"], "freq": f, "chords_mm": c["chords_mm"], "half_span_mm": c["half_span_mm"],
                    "coarse": {"mesh": "8 x 4", "thrust": c["thrust_N"], "torque": c["torque_Nm"]},
                    "fine": {"mesh": "21 x 12", "key": t["key"], "status": r.get("status"), "thrust": r.get("thrust"),
                             "torque": r.get("torque"), "tip_twist": r.get("tip_twist"), "numerics": t["numerics"]}})
    S.write_json(a.out / "results.json", {"freqs": a.freqs, "top": a.top, "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                          "wings": out})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
