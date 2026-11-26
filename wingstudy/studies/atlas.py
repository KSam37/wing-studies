"""Fold completed studies into the atlas data at site-build time (standard library only).

Each ``studies/<id>/results.json`` becomes one atlas study:

* chordwise and spanwise cases become map rows (``src`` bit 4, "a planned study"),
  with spanwise cases under ``span-flex:<model>`` like the matched reruns;
* matched cases join ``span_comparisons``, so they appear in the Elasticity effects
  tab and on the map exactly like the original matched reruns;
* evolutionary cases are also search rows (``src`` bit 1). ``row_search[row]`` names
  the objective(s) that reached each one and marks search winners, and each winner
  carries its lineage's accepted outlines (``evolution``) for the atlas to animate.
  ``lineage_pairs`` records every lineage's seed and best rows (before and after);
* convergence studies (design sets with several numerics settings) do not become map
  rows: their per-design refinement metrics go to ``convergence`` (studies/convergence.py).

Rows are appended after the rigid catalog, so ``catalog.end`` marks where it stops.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from . import convergence as CV
from . import spec as S

SRC_STUDY = 4
SRC_SEARCH = 1
# atlas objective bits for the campaigns' own objectives (other values are spelled out)
OBJ_BITS = {("torque_budget_Nm", 1.0): 1, ("lambda", 0.75): 2, ("lambda", 1.25): 4, ("lambda", 1.75): 8}


def _search_roles(results: dict) -> dict:
    """key -> {"objectives": [...], "winner_of": [...], "seed": bool, "evolution": {...}}"""
    roles = {}
    for x in results.get("searches") or []:
        (k, v), = x["objective"].items()
        label = x.get("objective_label") or f"{k} {v}"
        for lin in x.get("lineages") or []:
            for n, a in enumerate(lin.get("accepted") or []):
                e = roles.setdefault(a["key"], {"objectives": [], "bits": 0, "winner_of": [], "seed": False})
                if label not in e["objectives"]:
                    e["objectives"].append(label)
                e["bits"] |= OBJ_BITS.get((k, float(v)), 0)
                e.setdefault("lambda", set())
                if k == "lambda":
                    e["lambda"].add(float(v))
                else:
                    e.setdefault("budget", set()).add(float(v))
                e["seed"] |= n == 0
            best = lin.get("best")
            if best and best == x.get("winner"):
                e = roles[best]
                e["winner_of"].append(x["id"])
                seed = lin.get("seed") or {}
                e["evolution"] = {"search": x["id"], "objective": label,
                                  "lambda": float(v) if k == "lambda" else None,
                                  "torque_budget_Nm": float(v) if k != "lambda" else None,
                                  "family": seed.get("family"), "seed_label": seed.get("label"),
                                  "seed_half_span_mm": seed.get("half_span_mm"),
                                  "steps": [a["key"] for a in lin["accepted"]]}
    return roles


def _finite(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def completed(root: Path = S.STUDIES) -> list[tuple[dict, dict]]:
    """(spec, results) for every study whose results match its spec."""
    from .run import results_errors          # no solver import: results_errors is pure
    out = []
    for folder in sorted(Path(root).glob("*/")):
        sp, rp = folder / "spec.json", folder / "results.json"
        if not (sp.exists() and rp.exists()):
            continue
        spec, results = S.read_json(sp), S.read_json(rp)
        if S.validate(spec) or results_errors(results, spec):
            continue                          # CI reports these; the site skips them
        out.append((spec, results))
    return out


def _index(lst: list, value) -> int:
    if value not in lst:
        lst.append(value)
    return lst.index(value)


def _model(D: dict, model: str, structure: str) -> int:
    m = S.MODELS[model]
    mid = f"span-flex:{model}" if structure == "spanwise" else model
    for i, x in enumerate(D["models"]):
        if x["id"] == mid:
            return i
    D["models"].append({"id": mid, "label": m["label"] + (" · span + chord" if structure == "spanwise" else ""),
                        "thickness": m["thickness_mm"], "rod": m["rod"]})
    return len(D["models"]) - 1


def merge(D: dict, studies: list[tuple[dict, dict]]) -> int:
    """Append the studies to the assembled atlas object D in place; returns rows added."""
    if not studies:
        return 0
    cols = D["cols"]
    if D.get("catalog") and "end" not in D["catalog"]:
        D["catalog"]["end"] = len(cols["s"])
    notes = D.setdefault("row_notes", {})
    added = 0
    for spec, results in studies:
        sid = len(D["studies"])
        D["studies"].append({"id": spec["id"], "label": spec["title"], "short": spec["title"][:28],
                             "about": f"{spec['question']} Planned study by {spec['author']}; "
                                      f"{len(results['cases'])} cases, code {results['code']['digest']}.",
                             "planned": True, "kind": spec["kind"],
                             **({"run_date": results["completed"]} if results.get("completed") else {}),
                             **({"convergence": True} if CV.is_convergence(spec) else {})})
        if CV.is_convergence(spec):
            m = CV.metrics(spec, results)
            m["title"], m["question"], m["completed"] = spec["title"], spec["question"], results.get("completed")
            D.setdefault("convergence", []).append(m)
            continue
        roles = _search_roles(results) if spec["kind"] == "evolutionary" else {}
        rows_of = {}
        for c in results["cases"]:
            fi = _index(D["freqs"], c["freq"])
            if c.get("structure") == "matched":
                if not all(isinstance(c.get(k), dict) for k in ("baseline", "spanwise")):
                    continue
                m = S.MODELS[c["model"]]
                D.setdefault("span_comparisons", []).append({
                    "source": {"study": spec["id"], "key": c["key"], "freq": c["freq"], "chords": c["chords_mm"],
                               "half_span": c["half_span_mm"], "source_model": c["model"], "material_label": m["label"],
                               "thickness_mm": m["thickness_mm"], "has_rod": m["rod"],
                               "numerics": c["replay"]["input"].get("numerics"),
                               "comparison_note": f"{spec['title']} ({spec['id']}, case {c['case_id']})"},
                    "baseline": c["baseline"], "spanwise": c["spanwise"]})
                continue
            if not (_finite(c.get("thrust_N")) and _finite(c.get("torque_Nm"))):
                continue                      # failed cases stay in results.json, not on the map
            row = len(cols["s"])
            role = roles.get(c["key"])
            vals = {"s": sid, "m": _model(D, c["model"], c["structure"]), "f": fi, "T": c["thrust_N"],
                    "Q": c["torque_Nm"], "H": c["half_span_mm"], "W": c.get("tip_twist_deg"),
                    "S": _index(D["statuses"], c["status"]),
                    "src": SRC_STUDY | (SRC_SEARCH if spec["kind"] == "evolutionary" else 0), "k": c["key"],
                    "obj": (role["bits"] | (16 if role["seed"] and not role["winner_of"] else 0)) if role else 0}
            rows_of[c["key"]] = row
            if spec["kind"] == "evolutionary":
                D.setdefault("row_search", {})[str(row)] = (
                    {"objectives": role["objectives"], "lambda": sorted(role["lambda"]),
                     "torque_budget_Nm": sorted(role.get("budget", ())), "winner": bool(role["winner_of"]),
                     "winner_of": role["winner_of"], **({"evolution": role["evolution"]} if role.get("evolution") else {})}
                    if role else {"objectives": [], "lambda": [], "torque_budget_Nm": [], "winner": False, "trial": True})
            for k in cols:
                if k == "C":
                    cols["C"].extend(list(c["chords_mm"]) + [0.0] * (S.NODES - len(c["chords_mm"])))
                else:
                    cols[k].append(vals.get(k))
            n = c["numerics"]
            notes[str(row)] = (f"{spec['id']} case {c['case_id']} ({c['wing']}): {n['span_panels']} × {n['chord_panels']} "
                               f"panels, {n['steps_per_cycle']} steps per cycle, {n['cycles']} cycles")
            added += 1
        for x in results.get("searches") or [] if spec["kind"] == "evolutionary" else []:
            (k, v), = x["objective"].items()
            for lin in x.get("lineages") or []:
                acc = lin.get("accepted") or []
                if not acc or rows_of.get(acc[0]["key"]) is None or rows_of.get(acc[-1]["key"]) is None:
                    continue
                seed = lin.get("seed") or {}
                D.setdefault("lineage_pairs", []).append({
                    "study": spec["id"], "search": x["id"], "objective": x.get("objective_label") or f"{k} {v}",
                    "torque_budget_Nm": float(v) if k == "torque_budget_Nm" else None,
                    "lambda": float(v) if k == "lambda" else None, "lineage": lin["id"],
                    "family": seed.get("family"), "seed_label": seed.get("label"),
                    "before": rows_of[acc[0]["key"]], "after": rows_of[acc[-1]["key"]],
                    "accepted": len(acc) - 1, "solves": lin.get("solves"), "status": lin.get("status"),
                    "winner": acc[-1]["key"] == x.get("winner")})
        for v in (D.get("row_search") or {}).values():          # evolution steps as atlas rows
            ev = v.get("evolution")
            if ev and ev.get("steps") and isinstance(ev["steps"][0], str):
                ev["steps"] = [rows_of.get(k) for k in ev["steps"]]
    return added
