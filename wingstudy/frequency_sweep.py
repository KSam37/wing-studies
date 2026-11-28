"""Frequency sweep of the optimized FAAV wings: each outline solved at every flapping frequency.

    python -m wingstudy.frequency_sweep SUMMARY... [--freqs 0.75 1 1.25] [--mesh SPAN CHORD] [--workers N] [--out DIR]

SUMMARY files are second-stage ``wingstudy.refine_top`` summaries (smooth-curve finals). Every final within
its own torque budget is taken once (outlines that appear in several summaries are merged) and solved, with its
geometry fixed, at each frequency on the search mesh it was optimized on (21 x 12 panels, 50 steps per cycle,
4 cycles). The frequency it was optimized at comes straight from the summary.

``--mesh 8 4`` solves on the 8 x 4 search mesh instead, the basis every atlas wing is compared on: the smooth
outline is sampled at 9 stations (straight segments between them), and the wing's own frequency is solved too.
Free-span wings (``single_sheet`` false) may rescale up to refine_top.SPAN_LIMITS rather than one sheet.

Two results per wing and frequency:
  fixed    the outline exactly as optimized; its torque changes with frequency.
  matched  the same shape with its half-span rescaled (secant on torque ~ span^2.5) until peak torque sits on
           the wing's own budget, capped at the 400 mm sheet, so shapes are compared at equal torque.
The first solve of each rescale is the fixed result. Every point is cached in OUT/cache.jsonl; OUT/sweep.json
holds one entry per wing.
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from . import elastic_refine as ER
from .mesh_ladder import numerics
from .studies import spec as S

FREQS = (0.75, 1.0, 1.25)
SHEET_M = 0.400
SPAN_MAX = 0.800                                                  # refine_top.SPAN_LIMITS[1]


def _project(task):
    """Fixed-outline solve, then rescale the half-span until peak torque sits on the budget."""
    budget, tol = task["budget"], 0.002
    target = budget - 0.002
    lo, hi = 0.150, task.get("span_max", SHEET_M)                  # refine_top.SPAN_LIMITS floor, one sheet
    span, pts, recs, best, guess = task["span"], [], [], None, task.get("span_guess")
    for _ in range(7):
        span = round(min(hi, max(lo, span)), 4)
        rec = ER._solve({k: v for k, v in task.items() if k not in ("budget", "span_max", "span_guess")} | {"span": span, "fixed_span": True})
        recs.append(rec)
        if rec["status"] not in ("ok", "verified") or rec["torque"] is None:
            # a failed solve (e.g. twist past the model's limit) gets one retry at the guessed on-budget span
            g = None if guess is None else round(min(hi, max(lo, guess)), 4)
            if g is not None and abs(g - span) > 1e-3 and not pts:
                span, guess = g, None
                continue
            break
        if rec["torque"] <= budget and (best is None or rec["thrust"] > best["thrust"]):
            best = rec
        if abs(rec["torque"] - target) < tol:
            break
        pts.append((span, rec["torque"]))
        if len(pts) == 1:
            new = span * (target / rec["torque"]) ** (1 / 2.5)
        else:
            (s0, q0), (s1, q1) = pts[-2], pts[-1]
            new = s1 + (target - q1) * (s1 - s0) / (q1 - q0) if q1 != q0 else s1
        if abs(new - span) < 2e-4 or (span >= hi - 1e-9 and new > span) or (span <= lo + 1e-9 and new < span):
            break
        span = new
    return {"key": task["key"], "fixed": recs[0], "matched": best, "solves": len(recs)}
OUT = S.ROOT / "outputs" / "frequency-sweep"


def wings(paths: list[Path], min_thrust: float = 0.0) -> list[dict]:
    """Distinct within-budget smooth-curve finals over all summaries."""
    out = {}
    for p in paths:
        for x in S.read_json(p)["seeds"]:
            f = x.get("final") or {}
            freq = x.get("freq", (x.get("numerics") or {}).get("freq", 1.0))
            if f.get("thrust") is None or f.get("torque") is None or f["torque"] > x["budget_Nm"] + 1e-9 or not f.get("ctrl"):
                continue
            if f["thrust"] < min_thrust:
                continue
            ctrl, span = tuple(round(v, 5) for v in f["ctrl"]), round(f["span"], 5)
            k = (round(freq, 4), ctrl, span)
            if k not in out:
                out[k] = {"id": x["id"], "freq": freq, "budget_Nm": x["budget_Nm"], "ctrl": list(ctrl), "span": span,
                          "single_sheet": x.get("single_sheet", True),
                          "final_key": next((h["key"] for h in reversed(x.get("history") or []) if h.get("ctrl")
                                             and [round(v, 5) for v in h["ctrl"]] == list(ctrl) and abs(h["span"] - f["span"]) < 1e-6), None),
                          "final": f, "numerics": x.get("numerics") or {}, "summary": str(p),
                          "chords_mm": x.get("final_chords_mm")}
    return sorted(out.values(), key=lambda w: (w["freq"], w["budget_Nm"], -w["final"]["thrust"]))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m wingstudy.frequency_sweep", description=__doc__.split("\n\n")[0])
    ap.add_argument("summaries", type=Path, nargs="+", help="second-stage refine_top summaries")
    ap.add_argument("--freqs", type=float, nargs="+", default=list(FREQS))
    ap.add_argument("--min-thrust", type=float, default=0.0, help="skip finals below this thrust (N) at their own frequency")
    ap.add_argument("--mesh", type=int, nargs=2, metavar=("SPAN", "CHORD"), help="solve every wing on this mesh (default: its own)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    W = wings(a.summaries, a.min_thrust)
    for w in W:
        print(f"{w['id']}: optimized at {w['freq']:g} Hz, <= {w['budget_Nm']:g} N·m, {w['final']['thrust']:.3f} N, "
              f"{1000 * w['span']:.0f} mm")
    tasks = []
    for w in W:
        base = w["numerics"]
        for fq in a.freqs:
            if abs(fq - w["freq"]) < 1e-9 and not a.mesh:
                continue
            num = numerics(*(a.mesh or (base.get("span_panels", 21), base.get("chord_panels", 12))), fq)
            if a.mesh:
                num["dt_refinements"] = [1, 2, 4]                 # cheap on 8 x 4; long free-span wings need dt/4
            tasks.append({"key": ER.key_of("t0.50", w["ctrl"], w["span"], num), "model": "t0.50", "ctrl": w["ctrl"],
                          "span": w["span"], "numerics": num, "tag": f"{fq:g} Hz", "wing": w["id"], "freq": fq,
                          "budget": w["budget_Nm"], "span_max": SHEET_M if w["single_sheet"] else SPAN_MAX})
    print(f"{len(W)} wings x {len(a.freqs)} frequencies: {len(tasks)} new solves")
    if a.dry or not W:
        return 0
    a.out.mkdir(parents=True, exist_ok=True)
    cache_path, cache = a.out / "cache.jsonl", {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                cache[r["key"]] = r
    todo = [{k: v for k, v in t.items() if k not in ("wing", "freq", "tag")} for t in tasks if t["key"] not in cache]
    todo.sort(key=lambda t: -t["span"] * t["numerics"].get("freq", 1.0))                    # longest first
    print(time.strftime("%H:%M:%S"), f"{len(todo)} solves to run ({len(tasks) - len(todo)} cached)", flush=True)
    if todo:
        with ProcessPoolExecutor(max_workers=a.workers) as pool, cache_path.open("a", encoding="utf-8") as fh:
            for r in pool.map(_project, todo):
                cache[r["key"]] = r
                fh.write(json.dumps(r) + "\n")
                fh.flush()
                fx, mt = r["fixed"], r["matched"] or {}
                print(time.strftime("%H:%M:%S"), r["key"], fx.get("status"), "fixed", fx.get("thrust"), fx.get("torque"),
                      "matched", mt.get("thrust"), mt.get("torque"), mt.get("span"), r["solves"], flush=True)
    out = []
    for w in W:
        f = w["final"]
        pts = []
        for fq in a.freqs:
            if abs(fq - w["freq"]) < 1e-9 and not a.mesh:
                own = {"status": f.get("status"), "thrust": f["thrust"], "torque": f["torque"], "tip_twist": f.get("tip_twist"),
                       "half_span_mm": round(1000 * w["span"], 1)}
                pts.append({"freq": fq, "own": True, "fixed": own, "matched": own})
                continue
            t = next(t for t in tasks if t["wing"] == w["id"] and abs(t["freq"] - fq) < 1e-9)
            r = cache.get(t["key"]) or {}

            def pick(x):
                if not x:
                    return None
                ok = x.get("status") in ("ok", "verified")
                return {"status": x.get("status"), "thrust": x.get("thrust") if ok else None, "torque": x.get("torque") if ok else None,
                        "tip_twist": x.get("tip_twist"), "half_span_mm": round(1000 * x["span"], 1),
                        "key": ER.key_of("t0.50", w["ctrl"], x["span"], t["numerics"])}      # one key per solved span
            pts.append({"freq": fq, "key": t["key"], "own": abs(fq - w["freq"]) < 1e-9, "fixed": pick(r.get("fixed")),
                        "matched": pick(r.get("matched")), "solves": r.get("solves")})
        st = (a.mesh[0] + 1) if a.mesh else None
        out.append({"id": w["id"], "freq": w["freq"], "budget_Nm": w["budget_Nm"], "half_span_mm": round(1000 * w["span"], 1),
                    "single_sheet": w["single_sheet"], "optimized": {"thrust": f["thrust"], "torque": f["torque"],
                                                                     "mesh": "{} x {}".format(w["numerics"].get("span_panels"), w["numerics"].get("chord_panels"))},
                    "ctrl": w["ctrl"], "chords_mm": [round(1000 * c, 2) for c in ER.chords_from_ctrl(w["ctrl"], st, "pchip")] if st else w["chords_mm"],
                    "summary": w["summary"], "final_key": w["final_key"], "points": pts})
    mesh = "{} x {}".format(*a.mesh) if a.mesh else "21 x 12"
    S.write_json(a.out / "sweep.json", {"freqs": a.freqs, "mesh": mesh + ", 50 steps per cycle, 4 cycles",
                                        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "wings": out})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
