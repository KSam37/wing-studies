"""How far the 8 x 4 search mesh is from convergence: every wing solved on 8 x 4 and on a finer mesh, paired.

    python -m wingstudy.mesh_pairs [--out atlas/mesh-pairs.json]

No new solves. The pairs come from runs already made:
  picks      study picks (8 x 4, 8 straight-segment chords) re-solved with the same outline on tripled stations:
             21 x 4 (refine_top stage-1 start, including the stopped all-shapes run) and 21 x 12 (refine_top --baseline).
             Same geometry, so the difference is the mesh alone.
  optimized  optimized smooth-curve wings on 21 x 12 (refine_top finals and the 21 x 12 frequency sweep) against the
             same control chords on 8 x 4 (frequency_sweep --mesh 8 4, sampled at 9 stations). The outline sampling
             changes with the mesh, so this is the error a user of the 8 x 4 atlas actually sees.
  ladder     the 9 recommended wings (mesh_ladder: 21 x 12, 32 x 18, 47 x 27, Richardson-extrapolated) against their
             8 x 4 solve: 8 x 4 against converged.
Ratios are fine / 8 x 4. Writes atlas/mesh-pairs.json, which tools/build_site.py loads for the Convergence tab.
"""
from __future__ import annotations

import argparse
import json
import statistics as st
import time
from pathlib import Path

from . import elastic_refine as ER
from . import refine_top as RT
from .studies import spec as S

ATLAS = S.ROOT / "atlas"
OK = ("verified", "ok")


def _ok(r):
    return r and r.get("status") in OK and r.get("thrust") is not None and r.get("torque") is not None


def _pair(kind, wid, freq, coarse, fine, mesh, extra=None):
    return {"kind": kind, "id": wid, "freq": freq, "mesh": mesh,
            "coarse": {"thrust": coarse[0], "torque": coarse[1]}, "fine": {"thrust": fine[0], "torque": fine[1]},
            "thrust_ratio": round(fine[0] / coarse[0], 5), "torque_ratio": round(fine[1] / coarse[1], 5), **(extra or {})}


def _cache(paths):
    out = {}
    for p in paths:
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if _ok(r):
                    out.setdefault(r["key"], r)
    return out


def picks() -> list[dict]:
    out, seen = [], set()
    for run in sorted((ATLAS / "refine-top").glob("*/")):
        s1, bl = S.read_json(run / "stage1.json") if (run / "stage1.json").exists() else None, \
            S.read_json(run / "baseline.json") if (run / "baseline.json").exists() else None
        base = {b["id"]: b for b in (bl or {}).get("seeds", [])}
        for x in (s1 or {}).get("seeds", []):
            src, f = x.get("source") or {}, x.get("freq", (x.get("numerics") or {}).get("freq", 1.0))
            if not src.get("thrust_N"):
                continue
            c = (src["thrust_N"], src["torque_Nm"])
            if _ok(x.get("start")) and (src["key"], "21 x 4") not in seen:
                seen.add((src["key"], "21 x 4"))
                out.append(_pair("picks", src["key"], f, c, (x["start"]["thrust"], x["start"]["torque"]), "21 x 4"))
            b = base.get(x["id"])
            if _ok(b) and (src["key"], "21 x 12") not in seen:
                seen.add((src["key"], "21 x 12"))
                out.append(_pair("picks", src["key"], f, c, (b["thrust"], b["torque"]), "21 x 12"))
    # the stopped all-shapes optimizer: its seeds' first solves are the picks on 21 x 4
    cache = _cache(sorted(S.ROOT.glob("outputs/refine-all-*/cache.jsonl")))
    for f in (0.75, 1.0, 1.25):
        for s in RT.pick_seeds(RT.atlas_cases(f), RT.LEVELS, freq=f, free_span=True):
            c = s["case"]
            if (c["key"], "21 x 4") in seen:
                continue
            ctrl, span = RT.refine_outline(c["chords_mm"], c["half_span_mm"], RT.FACTOR)
            r = cache.get(ER.key_of("t0.50", ctrl, span, RT.numerics_for(len(ctrl), 4, freq=f)))
            if r:
                seen.add((c["key"], "21 x 4"))
                out.append(_pair("picks", c["key"], f, (c["thrust_N"], c["torque_Nm"]), (r["thrust"], r["torque"]), "21 x 4"))
    return out


def optimized(sweep8: dict, sweep21: dict | None) -> list[dict]:
    out, fine = [], {}
    for w in (sweep21 or {}).get("wings", []):
        for p in w["points"]:
            if _ok(p.get("fixed")):
                fine[(w["id"], p["freq"])] = p["fixed"]
    for w in sweep8["wings"]:
        for p in w["points"]:
            c = p.get("fixed")
            if not _ok(c):
                continue
            fz = fine.get((w["id"], p["freq"]))
            if fz is None and p.get("own"):
                fz = w["optimized"]
            if _ok(fz) or (fz and fz.get("thrust") is not None):
                out.append(_pair("optimized", w["id"], p["freq"], (c["thrust"], c["torque"]), (fz["thrust"], fz["torque"]), "21 x 12",
                                 {"own": bool(p.get("own"))}))
    return out


def ladder(sweep8: dict, lad: dict) -> list[dict]:
    out, by = [], {w["id"]: w for w in sweep8["wings"]}
    for w in lad.get("wings", []):
        s = by.get(w["id"])
        p = next((p for p in (s or {}).get("points", []) if p.get("own")), None)
        t, q = (w.get("thrust") or {}).get("extrapolated"), (w.get("torque") or {}).get("extrapolated")
        if not p or not _ok(p.get("fixed")) or t is None or q is None:
            continue
        lv = {l["mesh"]: {"thrust": l["thrust"], "torque": l["torque"]} for l in w["levels"] if _ok(l)}
        out.append(_pair("ladder", w["id"], w["freq"], (p["fixed"]["thrust"], p["fixed"]["torque"]), (t, q), "converged",
                         {"budget_Nm": w["budget_Nm"], "levels": lv}))
    return out


def stats(rows: list[dict]) -> dict:
    if not rows:
        return {}
    def s(k):
        v = sorted(100 * (r[k] - 1) for r in rows)
        q = lambda f: v[min(len(v) - 1, max(0, round(f * (len(v) - 1))))]
        return {"median_pct": round(st.median(v), 2), "p10_pct": round(q(0.1), 2), "p90_pct": round(q(0.9), 2),
                "min_pct": round(v[0], 2), "max_pct": round(v[-1], 2)}
    def rank(xs):
        o = sorted(range(len(xs)), key=lambda i: xs[i])
        r = [0.0] * len(xs)
        for k, i in enumerate(o):
            r[i] = k
        return r
    a, b = rank([r["coarse"]["thrust"] for r in rows]), rank([r["fine"]["thrust"] for r in rows])
    n = len(rows)
    rho = 1 - 6 * sum((x - y) ** 2 for x, y in zip(a, b)) / (n * (n * n - 1)) if n > 2 else None
    return {"n": n, "thrust": s("thrust_ratio"), "torque": s("torque_ratio"), "thrust_rank_rho": round(rho, 4) if rho is not None else None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m wingstudy.mesh_pairs", description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=ATLAS / "mesh-pairs.json")
    a = ap.parse_args(argv)
    sweep8 = S.read_json(ATLAS / "frequency-sweep.json")
    if not str(sweep8.get("mesh", "")).startswith("8 x 4"):
        raise SystemExit("atlas/frequency-sweep.json is not the 8 x 4 sweep (frequency_sweep --mesh 8 4)")
    p21 = S.ROOT / "outputs" / "frequency-sweep" / "sweep.json"
    sweep21 = S.read_json(p21) if p21.exists() else None
    rows = picks() + optimized(sweep8, sweep21) + ladder(sweep8, S.read_json(ATLAS / "mesh-ladder.json"))
    groups = {}
    for r in rows:
        groups.setdefault(f"{r['kind']}|{r['mesh']}", []).append(r)
    summary = {k: stats(v) for k, v in groups.items()}
    for k, v in summary.items():
        print(f"{k:22s} n={v['n']:3d}  thrust {v['thrust']['median_pct']:+6.2f} % ({v['thrust']['p10_pct']:+.1f} to {v['thrust']['p90_pct']:+.1f})"
              f"  torque {v['torque']['median_pct']:+6.2f} % ({v['torque']['p10_pct']:+.1f} to {v['torque']['p90_pct']:+.1f})  rho {v['thrust_rank_rho']}")
    S.write_json(a.out, {"about": __doc__.split("\n\n")[0], "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                         "summary": summary, "pairs": rows})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
