"""The top FAAV shapes at higher flapping frequencies, on the 8 x 4 search mesh.

    python -m wingstudy.freq_explore [--freqs 1.5 2 5] [--top 5] [--workers N] [--out DIR] [--dry]

Shapes: at each frequency already in the atlas (0.75, 1, 1.25 Hz), every verified FAAV wing on the thrust/torque
frontier and the ``--top`` highest-thrust wings under each torque budget in refine_top.LEVELS, all spans and within
one sheet (frontier_fine.select), plus every optimized wing (atlas/frequency-sweep.json). Outlines met at several
frequencies are taken once. Each shape keeps the torque budget it competes at: the smallest budget at or above its
torque where it was found.

At each new frequency a shape is solved twice (frequency_sweep._project): as found (fixed outline and half-span),
then with its half-span rescaled until peak torque sits on its budget, between 150 mm and one 400 mm sheet (800 mm
for wings found wider than a sheet). Torque grows roughly with frequency squared, so at high frequency many wings
reach the 150 mm floor still over budget; those results are kept and marked by their torque. A solve that fails
(at high frequency the sheet can twist past the torsion model's 80 degree limit) is retried once at the span that
torque ~ f^2 span^2.5 predicts for the budget, so the rescale can still find a span the model handles.

8 x 4 panels, 50 steps per cycle, 4 cycles, time step halved up to twice until verified. Cached in OUT/cache.jsonl;
OUT/results.json lists every wing and is what tools/build_site.py reads (copied to atlas/freq-explore.json).
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from . import elastic_refine as ER
from . import frontier_fine as FF
from . import refine_top as RT
from .frequency_sweep import SHEET_M, SPAN_MAX, _project
from .studies import spec as S

OUT = S.ROOT / "outputs" / "freq-explore"
FREQS = (1.5, 2.0, 5.0)


def numerics(stations: int, freq: float, param: str) -> dict:
    return {"stations": stations, "span_panels": 8, "chord_panels": 4, "steps_per_cycle": 50, "cycles": 4,
            "dt_refinements": [1, 2, 4], "param": param, "freq": freq}


def budget_of(torque: float) -> float:
    return next((B for B in RT.LEVELS if torque <= B + 1e-9), max(RT.LEVELS))


def shapes(top: int) -> list[dict]:
    out = {}
    for f in (0.75, 1.0, 1.25):
        for c in FF.select(f, top):
            ch = [x for x in c["chords_mm"] if x > 0]
            span = RT.effective_span_mm(c)
            k = (tuple(round(x, 1) for x in ch), round(span, 1))
            w = out.get(k)
            if w is None or c["thrust_N"] > w["thrust_N"]:
                out[k] = {"id": c["key"][:12], "source_key": c["key"], "kind": "study", "found_at": f, "study": c["study"],
                          "chords_mm": ch, "half_span_mm": span, "thrust_N": c["thrust_N"], "torque_Nm": c["torque_Nm"],
                          "budget_Nm": budget_of(c["torque_Nm"]), "param": "exact", "ctrl": [x / 1000 for x in ch[1:]],
                          "span": span / 1000, "single_sheet": span <= SHEET_M * 1000 + 0.5}
    sw = ATLAS_SWEEP.read_text(encoding="utf-8") if ATLAS_SWEEP.exists() else None
    for w in (json.loads(sw)["wings"] if sw else []):
        own = next((p for p in w["points"] if p.get("own")), {})
        m = own.get("matched") or own.get("fixed") or {}
        if m.get("thrust") is None:
            continue
        out[("opt", w["id"])] = {"id": w["id"], "source_key": w.get("final_key"), "kind": "optimized", "found_at": w["freq"],
                                 "study": "optimized", "chords_mm": w["chords_mm"], "half_span_mm": m["half_span_mm"],
                                 "thrust_N": m["thrust"], "torque_Nm": m["torque"], "budget_Nm": w["budget_Nm"], "param": "pchip",
                                 "ctrl": w["ctrl"], "span": m["half_span_mm"] / 1000, "single_sheet": w.get("single_sheet", True)}
    return list(out.values())


ATLAS_SWEEP = S.ROOT / "atlas" / "frequency-sweep.json"


def task(w: dict, f: float) -> dict:
    st = len(w["chords_mm"]) if w["param"] == "exact" else 9
    num = numerics(st, f, w["param"])
    return {"key": ER.key_of("t0.50", w["ctrl"], w["span"], num), "model": "t0.50", "ctrl": w["ctrl"], "span": w["span"],
            "numerics": num, "budget": w["budget_Nm"], "span_max": SHEET_M if w["single_sheet"] else SPAN_MAX,
            # torque ~ f^2 span^2.5: the span that keeps the found torque at the new frequency, scaled to the budget
            "span_guess": round(w["span"] * (w["found_at"] / f) ** 0.8 * (w["budget_Nm"] / w["torque_Nm"]) ** 0.4, 4)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m wingstudy.freq_explore", description=__doc__.split("\n\n")[0])
    ap.add_argument("--freqs", type=float, nargs="+", default=list(FREQS))
    ap.add_argument("--top", type=int, default=5, help="highest-thrust wings per budget and span setting (default 5)")
    ap.add_argument("--workers", type=int, default=17)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    W = shapes(a.top)
    jobs = [(w, f, task(w, f)) for w in W for f in a.freqs]
    print(f"{len(W)} shapes ({sum(w['kind'] == 'optimized' for w in W)} optimized) x {len(a.freqs)} frequencies = {len(jobs)} jobs", flush=True)
    a.out.mkdir(parents=True, exist_ok=True)
    cache_path, cache = a.out / "cache.jsonl", {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                cache[r["key"]] = r
    todo = {t["key"]: t for _, _, t in jobs if t["key"] not in cache}
    print(f"{len(todo)} to run ({len(jobs) - len(todo)} cached)", flush=True)
    if a.dry:
        return 0
    if todo:
        with ProcessPoolExecutor(max_workers=a.workers) as pool, cache_path.open("a", encoding="utf-8") as fh:
            futs = [pool.submit(_project, t) for t in sorted(todo.values(), key=lambda t: -t["span"] * t["numerics"]["freq"])]
            for n, fu in enumerate(as_completed(futs), 1):
                r = fu.result()
                cache[r["key"]] = r
                fh.write(json.dumps(r) + "\n")
                fh.flush()
                m = r.get("matched") or {}
                print(time.strftime("%H:%M:%S"), f"{n}/{len(todo)}", r["key"], (r.get("fixed") or {}).get("status"),
                      "matched", m.get("thrust"), m.get("torque"), m.get("span"), flush=True)
    out = []
    for w, f, t in jobs:
        r = cache.get(t["key"]) or {}

        def pick(x):
            if not x:
                return None
            ok = x.get("status") in ("ok", "verified")
            return {"status": x.get("status"), "thrust": x.get("thrust") if ok else None, "torque": x.get("torque") if ok else None,
                    "tip_twist": x.get("tip_twist"), "half_span_mm": round(1000 * x["span"], 1),
                    "key": ER.key_of("t0.50", w["ctrl"], x["span"], t["numerics"])}
        out.append({**{k: w[k] for k in ("id", "source_key", "kind", "found_at", "study", "chords_mm", "budget_Nm", "single_sheet")},
                    "found": {"thrust": w["thrust_N"], "torque": w["torque_Nm"], "half_span_mm": round(w["half_span_mm"], 1)},
                    "freq": f, "fixed": pick(r.get("fixed")), "matched": pick(r.get("matched")), "solves": r.get("solves")})
    S.write_json(a.out / "results.json", {"freqs": a.freqs, "top": a.top, "mesh": "8 x 4, 50 steps per cycle, 4 cycles",
                                          "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "results": out})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
