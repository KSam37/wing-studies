"""Polish studies: take the best shapes of finished searches and optimize them further.

``make_spec`` writes an evolutionary study whose lineages start from each source search's
top designs (the winner first) instead of family seeds, with a finer chord step and the
half-span free, under the source searches' own objectives. Each lineage's seed is the
"before" and its best accepted design the "after"; the atlas's Optimized shapes tab draws
the two over each other. Standard library only.
"""
from __future__ import annotations

from . import spec as S


def picks(sources: list[dict], top: int = 3, max_half_span_mm: float = 800.0) -> list[dict]:
    out, seen = [], set()
    for r in sources:
        by_key = {c["key"]: c for c in r["cases"]}
        for s in r.get("searches") or []:
            ranked = [s.get("winner")] + [l["best"] for l in sorted(
                (l for l in s.get("lineages") or [] if l.get("best") and l.get("best_score") is not None),
                key=lambda l: -l["best_score"])]
            n = 0
            for k in ranked:
                c = by_key.get(k)
                if not k or k in seen or not c or c.get("status") not in ("verified", "ok") or n >= top:
                    continue
                if c["half_span_mm"] > max_half_span_mm:
                    continue
                seen.add(k)
                n += 1
                out.append({"key": k, "case": c, "objective": s["objective"], "search": s["id"]})
    return out


def make_spec(study_id: str, sources: list[dict], top: int = 3, step_mm: float = 10.0, span_step_mm: float = 20.0,
              solves: int = 150, author: str = "", max_half_span_mm: float = 800.0) -> dict:
    chosen = picks(sources, top, max_half_span_mm)
    if not chosen:
        raise ValueError("nothing to polish: the sources have no verified search results within the span limit")
    objectives = []
    for p in chosen:
        if p["objective"] not in objectives:
            objectives.append(p["objective"])
    models = sorted({p["case"]["model"] for p in chosen})
    freqs = sorted({p["case"]["freq"] for p in chosen})
    numerics = [S.numerics_of(chosen[0]["case"]["numerics"])]
    lo = min(150.0, min(p["case"]["half_span_mm"] for p in chosen))
    ids = ", ".join(r["study"] for r in sources)
    spec = {"schema": S.SPEC_SCHEMA, "id": study_id,
            "title": f"Polish the top shapes of {ids}"[:120], "author": author or "sam",
            "question": (f"Starting from the {len(chosen)} best designs of {ids}, how much more thrust does a finer search "
                         f"({step_mm:g} mm chord step{', half-span free' if span_step_mm else ''}) find under the same "
                         "objectives, and how do the outlines change?")[:600],
            "kind": "evolutionary", "parent": sources[0]["study"], "structure": "chordwise", "models": models,
            "frequencies_hz": freqs, "numerics": numerics,
            "wings": {"designs": [{"name": f"seed {p['key']}", "chords_mm": [round(c, 6) for c in p["case"]["chords_mm"]],
                                   "half_span_mm": p["case"]["half_span_mm"]} for p in chosen]},
            "search": {"objectives": objectives[:S.OBJECTIVES_MAX], "solves_per_lineage": solves, "step_mm": step_mm,
                       "min_chord_mm": 10, "decreasing": True, "span_step_mm": span_step_mm,
                       "half_span_limits_mm": [lo, max_half_span_mm]},
            "notes": ("Before/after study: every lineage starts from a finished search's design (wing names carry its key) "
                      "and climbs again with finer steps. Every seed runs under every objective listed, so seeds found "
                      "under one torque budget are also tried under the others. Same model, motion and numerics as the "
                      "sources.")}
    if len(objectives) > S.OBJECTIVES_MAX:
        spec["notes"] += f" Only the first {S.OBJECTIVES_MAX} of {len(objectives)} objectives are kept."
    spec["budget"] = {"max_cases": S.case_count(spec)}
    return spec
