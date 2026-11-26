"""Convergence studies: re-solve chosen designs on a refinement ladder, as in an FEA mesh study.

A convergence study is an ordinary design-set study whose ``numerics`` hold more than one
setting. ``make_spec`` writes one from finished studies: each search's top designs, a seeded
random sample of the other verified designs (so the check is not only of the winners), and
any extra keys (favourites, say), all re-solved on ``LADDER``:

    base      8 x 4 panels,  50 steps/cycle   the setting every search ran on
    medium   12 x 6 panels,  75 steps/cycle   uniform refinement, ratio r = 1.5
    fine     18 x 9 panels, 112 steps/cycle   uniform refinement, ratio r = 1.5 again
    span x2  16 x 4,  50                      one parameter at a time, from base
    chord x2  8 x 8,  50
    time x2   8 x 4, 100

``metrics`` reads the results back. From the three uniform levels it gives, for thrust and
torque, the observed order p, the Richardson-extrapolated value and the fine-grid
convergence index (Roache's GCI, safety factor 1.25), and the base setting's error against
the extrapolated value: how far the searches' own numbers are from the mesh-independent
answer. Across all wings it gives the rank correlation of base against fine thrust, which
is what an optimization needs: if the ranking holds, the search picked the right designs
even where the absolute numbers move. The one-at-a-time levels say which refinement
moves the result. Standard library only (the site build uses it).
"""
from __future__ import annotations

import math
import random

from . import spec as S

R = 1.5
LADDER = [
    ("base", {"span_panels": 8, "chord_panels": 4, "steps_per_cycle": 50, "cycles": 4}),
    ("medium", {"span_panels": 12, "chord_panels": 6, "steps_per_cycle": 75, "cycles": 4}),
    ("fine", {"span_panels": 18, "chord_panels": 9, "steps_per_cycle": 112, "cycles": 4}),
    ("span x2", {"span_panels": 16, "chord_panels": 4, "steps_per_cycle": 50, "cycles": 4}),
    ("chord x2", {"span_panels": 8, "chord_panels": 8, "steps_per_cycle": 50, "cycles": 4}),
    ("time x2", {"span_panels": 8, "chord_panels": 4, "steps_per_cycle": 100, "cycles": 4}),
]
P_RANGE = (0.5, 6.0)          # observed orders outside this are reported but clamped for the GCI
GOOD = ("verified", "ok")
KEYS = ("span_panels", "chord_panels", "steps_per_cycle")


def is_convergence(spec: dict) -> bool:
    return spec.get("kind") == "design-set" and len(spec.get("numerics") or []) >= 2


# ----------------------------------------------------------------------------- selection
def _good(c: dict) -> bool:
    return c.get("status") in GOOD and c.get("thrust_N") is not None and c.get("torque_Nm") is not None


def select(sources: list[dict], top: int = 3, sample: int = 30, seed: int = 0, keys=(),
           torque_window=None, structure="chordwise") -> list[dict]:
    """[{role, key, case}] from finished study results: per search, the ``top`` best lineage
    results (winner first); then ``sample`` random other verified designs; then ``keys``."""
    by_key, out, seen = {}, [], set()
    for r in sources:
        for c in r["cases"]:
            if c.get("structure", "chordwise") == structure:
                by_key.setdefault(c["key"], c)

    def add(role, k):
        if k in by_key and k not in seen and _good(by_key[k]):
            seen.add(k)
            out.append({"role": role, "key": k, "case": by_key[k]})
    for r in sources:
        for s in r.get("searches") or []:
            bests = sorted(((l.get("best_score"), l["best"]) for l in s.get("lineages") or []
                            if l.get("best") and l.get("best_score") is not None), reverse=True)
            if s.get("winner"):
                add("top", s["winner"])
            for _, k in bests[:max(top - 1, 0)]:
                add("top", k)
    pool = sorted(k for k, c in by_key.items() if k not in seen and _good(c)
                  and (torque_window is None or torque_window[0] <= c["torque_Nm"] <= torque_window[1]))
    for k in random.Random(seed).sample(pool, min(sample, len(pool))):
        add("sample", k)
    for k in keys:
        add("pick", k)
    return out


def make_spec(study_id: str, sources: list[dict], picks: list[dict], author: str = "", extra_atlas=()) -> dict:
    if not picks and not extra_atlas:
        raise ValueError("nothing selected: no verified designs in the source studies")
    models = sorted({p["case"]["model"] for p in picks}) or ["t0.50"]
    freqs = sorted({p["case"]["freq"] for p in picks}) or [1.0]
    designs = [{"name": f"{p['role']} {p['key']}", "chords_mm": [round(c, 6) for c in p["case"]["chords_mm"]],
                "half_span_mm": p["case"]["half_span_mm"]} for p in picks]
    n_top = sum(p["role"] == "top" for p in picks)
    n_sample = sum(p["role"] == "sample" for p in picks)
    ids = ", ".join(r["study"] for r in sources)
    spec = {"schema": S.SPEC_SCHEMA, "id": study_id,
            "title": f"Convergence check: {len(designs) + len(extra_atlas)} designs on a 6-level refinement ladder"[:120],
            "author": author or "sam",
            "question": (f"Are the designs found by {ids} converged in mesh and time step? Re-solving {n_top} top designs and "
                         f"{n_sample} randomly sampled ones on a uniform refinement ladder (r = {R:g}) and one parameter at a "
                         "time: how far are the searches' 8 x 4 / 50 numbers from the extrapolated values, and does the "
                         "thrust ranking hold?")[:600],
            "kind": "design-set", "structure": "chordwise", "models": models, "frequencies_hz": freqs,
            "numerics": [dict(n) for _, n in LADDER],
            "wings": {"designs": designs, **({"from_atlas": list(extra_atlas)} if extra_atlas else {})},
            "notes": ("Ladder: " + "; ".join(f"{name} {n['span_panels']} x {n['chord_panels']} panels, {n['steps_per_cycle']} "
                      "steps per cycle" for name, n in LADDER) + ". Wing names carry the source design's key. "
                      "Every model x frequency of the sources is solved for every design."),
            }
    if len(models) * len(freqs) > 1:
        spec["notes"] += " Sources mix models or frequencies, so each design is also solved off its own condition."
    spec["budget"] = {"max_cases": S.case_count(spec)}
    return spec


# ----------------------------------------------------------------------------- analysis
def _level(n: dict) -> str | None:
    n = S.numerics_of(n)
    for name, x in LADDER:
        if all(n[k] == x[k] for k in KEYS):
            return name
    return None


def richardson(f1: float, f2: float, f3: float, r: float = R) -> dict:
    """Fine f1, medium f2, coarse f3 on a constant ratio r (Roache / Celik et al. 2008)."""
    e21, e32 = f1 - f2, f2 - f3
    out = {"fine": f1, "medium": f2, "coarse": f3}
    if abs(e21) <= 1e-9 * max(abs(f1), 1e-12):
        return {**out, "behaviour": "converged", "p": None, "extrapolated": f1, "gci_pct": 0.0}
    if e32 == 0 or e21 * e32 < 0:
        band = (max(f1, f2, f3) - min(f1, f2, f3)) / 2
        return {**out, "behaviour": "oscillatory", "p": None, "extrapolated": None,
                "gci_pct": 100 * band / abs(f1) if f1 else None}
    p = abs(math.log(abs(e32 / e21))) / math.log(r)
    pc = min(max(p, P_RANGE[0]), P_RANGE[1])
    rp = r ** pc
    ext = (rp * f1 - f2) / (rp - 1)
    return {**out, "behaviour": "monotone", "p": p, "p_clamped": pc != p, "extrapolated": ext,
            "gci_pct": 100 * 1.25 * abs(e21 / f1) / (rp - 1) if f1 else None}


def _rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    rk = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        for k in range(i, j + 1):
            rk[order[k]] = (i + j) / 2
        i = j + 1
    return rk


def spearman(a, b):
    if len(a) < 3:
        return None
    ra, rb = _rank(a), _rank(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else None


def metrics(spec: dict, results: dict) -> dict:
    """Per-design convergence and the study-wide summary (see the module docstring)."""
    groups = {}
    for c in results["cases"]:
        g = groups.setdefault((c["wing"], c["model"], c["freq"]), {"wing": c["wing"], "model": c["model"], "freq": c["freq"],
                                                                     "chords_mm": c["chords_mm"],
                                                                     "half_span_mm": c["half_span_mm"], "levels": {},
                                                                     **({"atlas_key": c["atlas_key"]} if c.get("atlas_key") else {})})
        name = _level(c["numerics"]) or "{span_panels}x{chord_panels}/{steps_per_cycle}".format(**S.numerics_of(c["numerics"]))
        g["levels"][name] = {"key": c["key"], "status": c.get("status"), "thrust_N": c.get("thrust_N"),
                             "torque_Nm": c.get("torque_Nm"), "numerics": S.numerics_of(c["numerics"]),
                             "elapsed_s": c.get("elapsed_s")}
    wings = []
    for g in groups.values():
        tag, _, src = g["wing"].rpartition(" ")
        g["role"] = tag if S.KEY_RE.fullmatch(src) else "design"
        g["source_key"] = src if S.KEY_RE.fullmatch(src) else (g.get("atlas_key") or (g["levels"].get("base") or {}).get("key"))
        L = g["levels"]
        ok = {k: v for k, v in L.items() if v["status"] in GOOD and v["thrust_N"] is not None}
        base = ok.get("base")
        for q, f in (("thrust", "thrust_N"), ("torque", "torque_Nm")):
            if all(k in ok for k in ("base", "medium", "fine")):
                rr = richardson(ok["fine"][f], ok["medium"][f], ok["base"][f])
                ext = rr["extrapolated"]
                rr["base_error_pct"] = 100 * (ok["base"][f] - ext) / abs(ext) if ext else None
                g[q] = rr
            if base:
                g[q + "_change_pct"] = {k: 100 * (v[f] - base[f]) / abs(base[f]) for k, v in ok.items()
                                        if k != "base" and base[f]}
        g["complete"] = len(ok) == len(L)
        wings.append(g)
    wings.sort(key=lambda g: (g["role"] != "top", -((g["levels"].get("base") or {}).get("thrust_N") or 0)))
    pairs = [(g["levels"]["base"]["thrust_N"], g["levels"]["fine"]["thrust_N"]) for g in wings
             if all((g["levels"].get(k) or {}).get("status") in GOOD for k in ("base", "fine"))]
    errs = [abs(g["thrust"]["base_error_pct"]) for g in wings if g.get("thrust") and g["thrust"].get("base_error_pct") is not None]
    terrs = [abs(g["torque"]["base_error_pct"]) for g in wings if g.get("torque") and g["torque"].get("base_error_pct") is not None]
    gcis = [g["thrust"]["gci_pct"] for g in wings if g.get("thrust") and g["thrust"].get("gci_pct") is not None]

    def med(x):
        x = sorted(x)
        return None if not x else (x[len(x) // 2] if len(x) % 2 else (x[len(x) // 2 - 1] + x[len(x) // 2]) / 2)
    summary = {"designs": len(wings), "complete": sum(g["complete"] for g in wings),
               "ladder": [{"name": n, **x} for n, x in LADDER], "ratio": R,
               "rank_correlation_base_fine": spearman([a for a, _ in pairs], [b for _, b in pairs]),
               "median_abs_base_error_thrust_pct": med(errs), "max_abs_base_error_thrust_pct": max(errs) if errs else None,
               "median_abs_base_error_torque_pct": med(terrs), "max_abs_base_error_torque_pct": max(terrs) if terrs else None,
               "median_gci_thrust_pct": med(gcis),
               "behaviour": {b: sum(1 for g in wings if (g.get("thrust") or {}).get("behaviour") == b)
                             for b in ("monotone", "oscillatory", "converged")}}
    for q, f in (("thrust", "thrust_N"), ("torque", "torque_Nm")):
        for k in ("span x2", "chord x2", "time x2", "medium", "fine"):
            v = [abs(g[q + "_change_pct"][k]) for g in wings if k in (g.get(q + "_change_pct") or {})]
            if v:
                summary.setdefault(f"median_abs_change_{q}_pct", {})[k] = med(v)
    return {"study": spec["id"], "summary": summary, "wings": wings}


def report(m: dict) -> str:
    s, lines = m["summary"], []
    f = lambda v, d=2: "–" if v is None else f"{v:.{d}f}"
    lines.append(f"{m['study']}: {s['designs']} designs, {s['complete']} with every level solved")
    lines.append(f"  thrust ranking, base vs fine (Spearman): {f(s['rank_correlation_base_fine'], 3)}")
    lines.append(f"  base-setting error vs extrapolated: thrust median {f(s['median_abs_base_error_thrust_pct'])} % "
                 f"(max {f(s['max_abs_base_error_thrust_pct'])} %), torque median {f(s['median_abs_base_error_torque_pct'])} % "
                 f"(max {f(s['max_abs_base_error_torque_pct'])} %)")
    lines.append(f"  fine-grid GCI, thrust: median {f(s['median_gci_thrust_pct'])} %; behaviour {s['behaviour']}")
    for q in ("thrust", "torque"):
        ch = s.get(f"median_abs_change_{q}_pct") or {}
        if ch:
            lines.append(f"  median |change| from base, {q}: " + ", ".join(f"{k} {v:.2f} %" for k, v in ch.items()))
    lines.append("")
    lines.append(f"  {'role':<7}{'source':<14}{'span':>6}{'T base':>9}{'T fine':>9}{'T ext':>9}{'err %':>8}{'GCI %':>7}{'p':>6}{'Q base':>8}{'Q err %':>8}")
    for g in m["wings"]:
        t, q, b = g.get("thrust") or {}, g.get("torque") or {}, g["levels"].get("base") or {}
        lines.append(f"  {g['role']:<7}{(g['source_key'] or '')[:12]:<14}{g['half_span_mm']:>6.0f}{f(b.get('thrust_N'), 3):>9}"
                     f"{f(t.get('fine'), 3):>9}{f(t.get('extrapolated'), 3):>9}{f(t.get('base_error_pct')):>8}"
                     f"{f(t.get('gci_pct')):>7}{f(t.get('p'), 1):>6}{f(b.get('torque_Nm'), 3):>8}{f(q.get('base_error_pct')):>8}")
    return "\n".join(lines)
