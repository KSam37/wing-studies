"""Permanent wing shape numbers (W00001, W00002, ...) for every outline in the atlas.

A point on the map is one simulation. Its wing shape is the outline alone: chords from root to tip and the
half-span, whatever the construction, structural model, frequency or mesh. Every simulation is named by its
shape number followed by those parameters.

An outline is identified by sampling it at 25 equal fractions of its effective half-span (straight lines between
stations, root to the last non-zero chord) and rounding chords and half-span to 1 mm, so the same outline on 8 or
on 22 stations is one shape. Rigid-catalog wings, drawn as polygons, are identified by their polygon.

Numbers are kept in atlas/shape-ids.json, an append-only registry the site build updates: a shape never changes
number, and new outlines get the next numbers in atlas row order. Standard library only.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

SAMPLES = 25


def outline_key(chords_mm, half_span_mm) -> str | None:
    ch = list(chords_mm)
    n = len(ch)
    pts = [(half_span_mm * j / (n - 1), c) for j, c in enumerate(ch) if c and c > 0]
    if len(pts) < 2:
        return None
    L = pts[-1][0]
    out, j = [round(L)], 0
    for k in range(SAMPLES):
        x = L * k / (SAMPLES - 1)
        while j < len(pts) - 2 and pts[j + 1][0] < x:
            j += 1
        (x0, c0), (x1, c1) = pts[j], pts[j + 1]
        t = min(1.0, max(0.0, (x - x0) / (x1 - x0))) if x1 > x0 else 0.0
        out.append(round(c0 + (c1 - c0) * t))
    return hashlib.sha1(",".join(map(str, out)).encode()).hexdigest()[:12]


def poly_key(poly) -> str:
    flat = [v for p in poly for v in (p if isinstance(p, (list, tuple)) else [p])]
    return "c" + hashlib.sha1(json.dumps([round(v) for v in flat]).encode()).hexdigest()[:11]


def assign(D: dict, registry: Path) -> int:
    """Add ``cols["g"]`` (shape number per row) and ``shape`` to every span-comparison source; returns new shapes."""
    reg = json.loads(registry.read_text(encoding="utf-8")) if registry.exists() else {"next": 1, "ids": {}}
    ids, nxt = reg["ids"], reg["next"]
    cols, n = D["cols"], len(D["cols"]["s"])
    cat = D.get("catalog") or {}
    c0, c1 = cat.get("first", n), cat.get("end", n)
    outlines = D.get("row_outline") or {}

    def number(key):
        nonlocal nxt
        if key is None:
            return None
        if key not in ids:
            ids[key] = nxt
            nxt += 1
        return ids[key]

    g = []
    for i in range(n):
        if c0 <= i < c1:
            g.append(number(poly_key(cat["poly"][i - c0])))
        else:
            ch = outlines.get(str(i)) or cols["C"][8 * i:8 * i + 8]
            g.append(number(outline_key(ch, cols["H"][i])))
    cols["g"] = g
    for p in D.get("span_comparisons") or []:
        s = p["source"]
        s["shape"] = number(outline_key(s["chords"], s["half_span"]))
    added = nxt - reg["next"]
    if added:
        registry.write_text(json.dumps({"about": "Permanent wing shape numbers (wingstudy/shapes.py); append-only, "
                                                 "written by tools/build_site.py.", "next": nxt, "ids": ids},
                                       separators=(",", ":")), encoding="utf-8")
    return added
