"""Fold completed studies into the atlas data at site-build time (standard library only).

Each ``studies/<id>/results.json`` becomes one atlas study:

* design-set and geometry-sweep cases become map rows (``src`` bit 4, "a planned study"),
  with spanwise cases under ``span-flex:<model>`` like the matched reruns;
* matched-comparison cases join ``span_comparisons``, so they appear in the
  Spanwise elasticity tab and on the map exactly like the original matched reruns.

Rows are appended after the rigid catalog, so ``catalog.end`` marks where it stops.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from . import spec as S

SRC_STUDY = 4


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
                             "planned": True, "kind": spec["kind"]})
        for c in results["cases"]:
            fi = _index(D["freqs"], c["freq"])
            if spec["kind"] == "matched-comparison":
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
            vals = {"s": sid, "m": _model(D, c["model"], c["structure"]), "f": fi, "T": c["thrust_N"],
                    "Q": c["torque_Nm"], "H": c["half_span_mm"], "W": c.get("tip_twist_deg"),
                    "S": _index(D["statuses"], c["status"]), "src": SRC_STUDY, "k": c["key"], "obj": 0}
            for k in cols:
                if k == "C":
                    cols["C"].extend(list(c["chords_mm"]) + [0.0] * (S.NODES - len(c["chords_mm"])))
                else:
                    cols[k].append(vals.get(k))
            n = c["numerics"]
            notes[str(row)] = (f"{spec['id']} case {c['case_id']} ({c['wing']}): {n['span_panels']} × {n['chord_panels']} "
                               f"panels, {n['steps_per_cycle']} steps per cycle, {n['cycles']} cycles")
            added += 1
    return added
