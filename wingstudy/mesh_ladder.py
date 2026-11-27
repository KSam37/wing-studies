"""Mesh-convergence ladder for the recommended (optimized) FAAV wings.

    python -m wingstudy.mesh_ladder SUMMARY... [--levels 21x12 32x18 47x27] [--workers N] [--out DIR]

SUMMARY files are second-stage ``wingstudy.refine_top`` summaries (smooth-curve finals). For each
frequency and torque budget the best final within budget is taken, the recommended wing, and solved on
systematically refined meshes: span panels x chord panels, with the PCHIP outline sampled at one station
per span panel, 50 steps per cycle and 4 cycles. The first level is the search mesh (21 x 12), whose result
comes straight from the summary; the later levels are about 1.5x finer in each direction (r = 1.5).

From the three finest levels the observed order p, the Richardson-extrapolated value and the fine-mesh GCI
are computed with the procedure of Celik et al. (2008), ASME J. Fluids Eng. 130, 078001, which allows a
non-constant refinement ratio (r = sqrt(N_fine / N_coarse) for N panels on the wing). Every solve is cached
in OUT/cache.jsonl; OUT/ladder.json holds the levels and the convergence metrics per wing.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from . import elastic_refine as ER
from .studies import spec as S

LEVELS = ("21x12", "32x18", "47x27")
OUT = S.ROOT / "outputs" / "mesh-ladder"


def numerics(span_panels: int, chord_panels: int, freq: float = 1.0) -> dict:
    out = {"stations": span_panels + 1, "span_panels": span_panels, "chord_panels": chord_panels, "steps_per_cycle": 50,
           "cycles": 4, "dt_refinements": [1, 2], "param": "pchip"}
    if abs(freq - 1.0) > 1e-9:
        out["freq"] = freq
    return out


def recommended(paths: list[Path]) -> list[dict]:
    """Best smooth-curve final within budget per (frequency, budget) over all summaries."""
    best = {}
    for p in paths:
        for x in S.read_json(p)["seeds"]:
            f = x.get("final") or {}
            freq = x.get("freq", (x.get("numerics") or {}).get("freq", 1.0))
            if f.get("thrust") is None or f.get("torque") is None or f["torque"] > x["budget_Nm"] + 1e-9 or not f.get("ctrl"):
                continue
            k = (round(freq, 4), x["budget_Nm"])
            if k not in best or f["thrust"] > best[k]["final"]["thrust"]:
                best[k] = {"id": x["id"], "freq": freq, "budget_Nm": x["budget_Nm"], "final": f,
                           "numerics": x.get("numerics"), "summary": str(p)}
    return [best[k] for k in sorted(best)]


def celik(levels: list[dict], key: str) -> dict:
    """Observed order, extrapolated value and GCI from the three finest levels (Celik et al. 2008)."""
    pts = [(lv["panels"], lv.get(key)) for lv in levels if lv.get(key) is not None]
    if len(pts) < 3:
        return {}
    (n3, f3), (n2, f2), (n1, f1) = pts[-3:]                          # 3 coarse ... 1 fine
    r21, r32 = math.sqrt(n1 / n2), math.sqrt(n2 / n3)
    e21, e32 = f2 - f1, f3 - f2
    out = {"fine": f1, "change_last_pct": 100 * abs(e21 / f1) if f1 else None}
    if e21 == 0 or e32 == 0:
        return {**out, "behaviour": "converged", "p": None, "extrapolated": f1, "gci_pct": 0.0}
    s = 1.0 if e32 / e21 > 0 else -1.0
    p = abs(math.log(abs(e32 / e21))) / math.log(r21)
    for _ in range(100):                                              # fixed point for non-constant r
        q = math.log((r21 ** p - s) / (r32 ** p - s))
        p_new = abs(math.log(abs(e32 / e21)) + q) / math.log(r21)
        if abs(p_new - p) < 1e-8:
            break
        p = p_new
    ext = (r21 ** p * f1 - f2) / (r21 ** p - 1)
    return {**out, "behaviour": "monotone" if s > 0 else "oscillatory", "p": p, "extrapolated": ext,
            "gci_pct": 100 * 1.25 * abs(e21 / f1) / (r21 ** p - 1), "fine_error_pct": 100 * (f1 / ext - 1)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m wingstudy.mesh_ladder", description=__doc__.split("\n\n")[0])
    ap.add_argument("summaries", type=Path, nargs="+", help="second-stage refine_top summaries")
    ap.add_argument("--levels", nargs="+", default=list(LEVELS), help="span x chord panels, coarse to fine; the first is the search mesh")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    wings = recommended(a.summaries)
    levels = [tuple(int(v) for v in lv.lower().split("x")) for lv in a.levels]
    for w in wings:
        print(f"{w['id']}: {w['freq']:g} Hz, <= {w['budget_Nm']:g} N·m, {w['final']['thrust']:.3f} N at {w['final']['torque']:.3f} N·m")
    print(f"{len(wings)} wings x {len(levels) - 1} new levels: {', '.join(a.levels[1:])}")
    if a.dry or not wings:
        return 0
    a.out.mkdir(parents=True, exist_ok=True)
    cache_path, cache = a.out / "cache.jsonl", {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                cache[r["key"]] = r
    tasks = []
    for w in wings:
        ctrl, span = [round(x, 5) for x in w["final"]["ctrl"]], round(w["final"]["span"], 5)
        for sp, ch in levels[1:]:
            num = numerics(sp, ch, w["freq"])
            tasks.append({"key": ER.key_of("t0.50", ctrl, span, num), "model": "t0.50", "ctrl": ctrl, "span": span,
                          "numerics": num, "tag": f"{sp} x {ch}", "wing": w["id"]})
    todo = [t for t in tasks if t["key"] not in cache]
    todo.sort(key=lambda t: -t["numerics"]["span_panels"] * t["numerics"]["chord_panels"])   # longest first
    print(time.strftime("%H:%M:%S"), f"{len(todo)} solves to run ({len(tasks) - len(todo)} cached)", flush=True)
    if todo:
        with ProcessPoolExecutor(max_workers=a.workers) as pool, cache_path.open("a", encoding="utf-8") as fh:
            for r in pool.map(ER._solve, todo):
                cache[r["key"]] = r
                fh.write(json.dumps(r) + "\n")
                fh.flush()
                print(time.strftime("%H:%M:%S"), r["key"], r.get("status"), r.get("thrust"), r.get("torque"), r.get("elapsed"), flush=True)
    out = []
    for w in wings:
        sp0, ch0 = levels[0]
        f = w["final"]
        lv = [{"mesh": f"{sp0} x {ch0}", "span_panels": sp0, "chord_panels": ch0, "panels": sp0 * ch0,
               "status": f.get("status"), "thrust": f["thrust"], "torque": f["torque"], "tip_twist": f.get("tip_twist")}]
        for t in tasks:
            if t["wing"] != w["id"]:
                continue
            r = cache.get(t["key"]) or {}
            ok = r.get("status") in ("ok", "verified")
            n = t["numerics"]
            lv.append({"mesh": t["tag"], "span_panels": n["span_panels"], "chord_panels": n["chord_panels"],
                       "panels": n["span_panels"] * n["chord_panels"], "status": r.get("status"), "key": t["key"],
                       "thrust": r.get("thrust") if ok else None, "torque": r.get("torque") if ok else None,
                       "tip_twist": r.get("tip_twist"), "elapsed_s": r.get("elapsed")})
        out.append({**{k: w[k] for k in ("id", "freq", "budget_Nm", "summary")}, "half_span_mm": round(1000 * f["span"], 1),
                    "ctrl": f["ctrl"], "levels": lv, "thrust": celik(lv, "thrust"), "torque": celik(lv, "torque")})
        th = out[-1]["thrust"]
        if th.get("extrapolated") is not None:
            print(f"{w['id']}: thrust p = {th.get('p') or 0:.2f}, extrapolated {th['extrapolated']:.3f} N, GCI {th['gci_pct']:.1f} %, "
                  f"last change {th['change_last_pct']:.1f} %")
    S.write_json(a.out / "ladder.json", {"levels": a.levels, "method": "Celik et al. 2008 (ASME JFE 130:078001), r = sqrt(N1/N2)",
                                         "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "wings": out})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
