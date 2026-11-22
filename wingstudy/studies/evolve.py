"""Evolutionary studies: the campaigns' coordinate climb, driven from a study spec.

Each (model, frequency, objective) is one search. Every search starts the same lineages:
one per seed half-span x seed family (the campaigns' family seeds, 200 mm root) plus one
per seed wing. A lineage is ``coordinate_search.climb`` unchanged: it tries +/- one chord
step on each station in turn, keeps a step only if the objective improves, gets exactly
one half-step retry per station, and stops when every station is retired or it has used
``solves_per_lineage`` solves. With ``span_step_mm`` > 0 the half-span is one more
coordinate (tried first each pass, same rules, within ``half_span_limits_mm``), so a
lineage's span can grow or shrink. Objectives, as in the campaigns:

    torque_budget_Nm = B   maximize mean thrust subject to peak root torque <= B
                           (seeds above B first walk down in torque, then climb thrust)
    lambda = x             S = T/Tref - x * M/Mref, Tref and Mref fixed from that
                           search's own seeds

Only verified elastic (or settled rigid) results can become parents. Lineages advance
in lockstep waves so a wave's solves run in parallel. With structure "matched" the climb
runs on chordwise elasticity and each search's winner is re-solved as a matched pair.
"""
from __future__ import annotations

import math

from . import spec as S

TYPICAL_SOLVES_PER_LINEAGE = 22      # campaigns' measured mean (elastic_campaign est_evals_per_lineage)


def objective_name(o: dict) -> str:
    return f"lambda_{o['lambda']:g}" if "lambda" in o else f"torque_{o['torque_budget_Nm']:g}Nm"


def objective_label(o: dict) -> str:
    return f"λ = {o['lambda']:g}" if "lambda" in o else f"max thrust with peak torque ≤ {o['torque_budget_Nm']:g} N·m"


def rules(search: dict, objective: dict, root_mm: float) -> dict:
    step, mn, root = search["step_mm"] / 1000, search["min_chord_mm"] / 1000, root_mm / 1000
    bounds = [{"min_m": root, "max_m": root, "step_m": step}]
    bounds += [{"min_m": mn if i < 2 else 0.0, "max_m": S.CHORD_RANGE[1] / 1000, "step_m": step} for i in range(1, S.NODES)]
    out = {"node_count": S.NODES, "bounds": bounds, "root_chord_m": root, "tip_chord_m": mn, "minimum_chord_m": mn,
           "decreasing": bool(search["decreasing"]), "tradeoff_lambda": float(objective.get("lambda", 0.0)),
           "score_tolerance": 1e-6, "objective": objective_name(objective)}
    if search.get("span_step_mm"):
        lo, hi = search["half_span_limits_mm"]
        out.update(span_step_m=search["span_step_mm"] / 1000, span_min_m=lo / 1000, span_max_m=hi / 1000)
    return out


def seeds(spec: dict) -> list[dict]:
    """Every lineage's starting outline: family seeds first, then seed wings."""
    from .. import adaptive
    s = S.search_of(spec)
    out = []
    for hs in s["seed_half_spans_mm"]:
        for fam in s["seed_families"]:
            r = rules(s, {"lambda": 0.0}, S.SEED_ROOT_MM)
            out.append({"label": f"{fam} seed, {hs:g} mm", "family": fam, "half_span_mm": float(hs),
                        "chords_mm": [round(c * 1000, 6) for c in adaptive.seed(r, fam)]})
    if spec.get("wings"):
        for w in S.wings_of(dict(spec, kind="design-set")):
            out.append({"label": w["name"], "family": "wing", "half_span_mm": float(w["half_span_mm"]),
                        "chords_mm": [float(c) for c in w["chords_mm"]], **({"atlas_key": w["atlas_key"]} if w.get("atlas_key") else {})})
    for x in out:
        r = rules(s, {"lambda": 0.0}, x["chords_mm"][0])
        if not adaptive.valid([c / 1000 for c in x["chords_mm"]], r):
            raise ValueError(f"seed {x['label']!r} does not obey the search rules (minimum chord, decreasing chords)")
        lo, hi = s["half_span_limits_mm"]
        if not lo <= x["half_span_mm"] <= hi:
            raise ValueError(f"seed {x['label']!r}: half-span {x['half_span_mm']:g} mm is outside search.half_span_limits_mm")
    return out


def row(key: str, r: dict) -> dict:
    """coordinate_search row: only verified elastic / settled rigid results can be parents."""
    ok = r.get("status") in ("verified", "ok") and r.get("thrust_N") is not None and r.get("torque_Nm") is not None
    return {"id": key, "status": "ok" if ok else "failed", "simulation_mode": "isolated_single_wing_v1",
            "cycle_repeatable": ok, "single_wing_mean_thrust_N": r.get("thrust_N") if ok else None,
            "single_wing_peak_abs_roll_moment_Nm": r.get("torque_Nm") if ok else None}


def estimate_cases(spec: dict) -> tuple[int, int]:
    """(typical, most) solves: lineages usually stop well before their budget."""
    s = S.search_of(spec)
    n_search = len(spec["models"]) * len(spec["frequencies_hz"]) * len(spec["search"]["objectives"])
    lin = S.lineages_per_search(spec)
    extra = 1 if spec.get("structure") == "matched" else 0
    typical = n_search * (lin * (1 + min(TYPICAL_SOLVES_PER_LINEAGE, s["solves_per_lineage"])) + extra)
    return typical, S.case_count(spec)


def search(spec: dict, solve_many, log=print) -> dict:
    """Run every search. ``solve_many(cases) -> {key: result}`` solves (or loads) cases.

    Returns {"cases": [case...], "searches": [...]} with each case keyed by its cache key.
    """
    from .. import coordinate_search as cs
    s = S.search_of(spec)
    numerics = S.numerics_of(spec["numerics"][0])
    climb_structure = "chordwise" if spec.get("structure") == "matched" else spec.get("structure", "chordwise")
    starts = seeds(spec)
    cases: dict[str, dict] = {}            # key -> case (first use), in solve order
    results: dict[str, dict] = {}

    def case(model, freq, chords_mm, hs_mm, label, structure=climb_structure):
        return {"wing": label, "model": model, "structure": structure, "freq": float(freq),
                "chords_mm": [round(c, 6) for c in chords_mm], "half_span_mm": float(hs_mm), "numerics": dict(numerics)}

    def solve(batch):
        """batch: list of case dicts -> list of (key, result)."""
        got = solve_many(batch)
        out = []
        for c in batch:
            k = c["key"]
            cases.setdefault(k, c)
            results[k] = got[k]
            out.append((k, got[k]))
        return out

    plan = [(m, f, o) for m in spec["models"] for f in spec["frequencies_hz"] for o in spec["search"]["objectives"]]
    # 1. every seed of every (model, frequency), once: objectives share their seeds
    seed_cases = {(m, f, j): case(m, f, x["chords_mm"], x["half_span_mm"], x["label"])
                  for m in spec["models"] for f in spec["frequencies_hz"] for j, x in enumerate(starts)}
    seed_res = dict(zip(seed_cases, solve(list(seed_cases.values()))))
    log(f"seeds solved: {len(seed_cases)}")

    searches, lineages = [], []
    for m, f, o in plan:
        sid = f"{m}@{f:g}Hz/{objective_name(o)}"
        rows = {j: row(*seed_res[(m, f, j)]) for j in range(len(starts))}
        valid = [cs.loads(r) for r in rows.values() if cs.loads(r) is not None]
        rec = {"id": sid, "model": m, "freq": float(f), "objective": o, "objective_label": objective_label(o),
               "lineages": [], "winner": None, "winner_score": None, "status": "climbing"}
        searches.append(rec)
        if not valid:
            rec["status"] = "no valid seeds"
            continue
        scales = {"thrust_scale_N": max(max(abs(t) for t, _ in valid), 1e-9),
                  "torque_scale_Nm": max(max(q for _, q in valid), 1e-9)}
        rec.update(tref_N=scales["thrust_scale_N"], mref_Nm=scales["torque_scale_Nm"])
        score_fn = None
        if "torque_budget_Nm" in o:
            budget, tref, mref = o["torque_budget_Nm"], scales["thrust_scale_N"], scales["torque_scale_Nm"]

            def score_fn(r, budget=budget, tref=tref, mref=mref):
                v = cs.loads(r)
                if v is None:
                    return None
                t, q = v
                return t / tref if q <= budget else -10.0 - (q - budget) / mref
        for j, x in enumerate(starts):
            r = rules(s, o, x["chords_mm"][0])
            lin = {"search": rec, "id": f"L{j:02d}", "seed": x, "evals": 0, "accepted": [], "status": "running",
                   "score_fn": score_fn or (lambda rr, r=r, sc=scales: cs.score(rr, sc, r["tradeoff_lambda"])),
                   "half_span_mm": x["half_span_mm"], "model": m, "freq": f}
            if cs.loads(rows[j]) is None:
                lin["status"] = "invalid seed"
            else:
                lin["gen"] = cs.climb(r, x["half_span_mm"] / 1000, j + 1, x["family"],
                                      ([c / 1000 for c in x["chords_mm"]], rows[j]), scales, score_fn=score_fn)
                lin["pending"] = None
            lineages.append(lin)
            rec["lineages"].append(lin)

    def step(lin, sent):
        """Advance a lineage until it needs solves; returns the cases it needs (or [])."""
        try:
            msg = lin["gen"].send(sent) if sent is not None else next(lin["gen"])
            while True:
                if msg[0] == "accepted":
                    ev = msg[1]
                    lin["accepted"].append({"key": ev["case"]["id"], "score": lin["score_fn"](ev["case"]),
                                            "pass": ev.get("pass"), "node": ev.get("node"), "kind": ev.get("kind"),
                                            "half_span_mm": round(ev["span_m"] * 1000, 6)})
                    msg = next(lin["gen"])
                    continue
                pending = msg[1]
                if lin["evals"] + len(pending) > s["solves_per_lineage"]:
                    lin["status"] = "budget reached"
                    lin["gen"].close()
                    return []
                lin["evals"] += len(pending)
                return [case(lin["model"], lin["freq"], [c * 1000 for c in ch], round(meta["span_m"] * 1000, 6),
                             f"{lin['search']['id']} {lin['id']} ({lin['seed']['label']})") for ch, meta in pending]
        except StopIteration as stop:
            lin["status"] = (stop.value or {}).get("status", "complete")
            return []

    active = [l for l in lineages if "gen" in l]
    need = {id(l): step(l, None) for l in active}
    wave = 0
    while True:
        waiting = [l for l in active if need.get(id(l))]
        if not waiting:
            break
        wave += 1
        batch = [c for l in waiting for c in need[id(l)]]
        got = solve(batch)
        i = 0
        for l in waiting:
            k = len(need[id(l)])
            sent = [row(key, r) for key, r in got[i:i + k]]
            i += k
            need[id(l)] = step(l, sent)
        done = sum(1 for l in active if l["status"] != "running")
        log(f"wave {wave}: {len(batch)} solves, {done}/{len(active)} lineages finished")

    matched, owners = [], []
    for rec in searches:
        bests = [(l["accepted"][-1]["score"], l["accepted"][-1]["key"]) for l in rec["lineages"]
                 if l["accepted"] and l["accepted"][-1]["score"] is not None]
        if rec["status"] == "climbing":
            rec["status"] = "complete"
        if bests:
            sc, key = max(bests)
            rec["winner"], rec["winner_score"] = key, sc
            if spec.get("structure") == "matched":
                c = cases[key]
                matched.append(case(c["model"], c["freq"], c["chords_mm"], c["half_span_mm"],
                                    f"{rec['id']} winner, matched", structure="matched"))
                owners.append(rec)
    if matched:
        for (key, _), rec in zip(solve(matched), owners):
            rec["matched"] = key

    for rec in searches:
        rec["lineages"] = [{"id": l["id"], "seed": {k: v for k, v in l["seed"].items()}, "status": l["status"],
                            "solves": l["evals"], "accepted": l["accepted"],
                            "best": l["accepted"][-1]["key"] if l["accepted"] else None,
                            "best_score": l["accepted"][-1]["score"] if l["accepted"] else None}
                           for l in rec["lineages"]]
        for k in ("tref_N", "mref_Nm", "winner_score"):
            if isinstance(rec.get(k), float) and not math.isfinite(rec[k]):
                rec[k] = None
    return {"cases": list(cases.values()), "results": results, "searches": searches}
