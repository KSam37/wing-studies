"""Triple-resolution refinement of the FAAV top performers.

    python -m wingstudy.refine_top STUDY... [--workers N] [--factor 3] [--out DIR] [--dry]

Takes the FAAV standouts (0.5 mm sheet pivoting on a stiff leading edge: model t0.50,
chordwise, 1 Hz, verified) from finished study results: the highest-thrust wing at or below
each torque budget in LEVELS, and the best single-sheet (<= 400 mm) wing at each budget where
that differs. Each outline is redescribed with ``factor`` times as many chord segments (8
stations -> 22 by default, straight segments, so the starting shape is unchanged) and solved
on a mesh with one span panel per segment. A parallel pattern search then moves every
outboard chord (+/- 10 mm, then 5 mm; never increasing toward the tip, >= 10 mm) and the
half-span (+/- 20 mm, then 10 mm; single-sheet seeds stay <= 400 mm), accepting the best
improving move each round, under the budget the seed was picked for:

    score = T            if peak torque <= B
            -10 - (Q-B)  otherwise

Solves go through ``elastic_refine._solve`` (same template case, material and verification
ladder as the refinement tool). Every solve is cached in OUT/cache.jsonl, so a rerun resumes.
OUT/summary.json lists, per seed: the coarse study result (before), the same outline on the
fine description and mesh (start), and the refined result (after).

Second stage, from a finished summary (``--from``): each refined outline is re-solved on a mesh
with ``--chord-panels`` chordwise panels (``recheck``), then, with ``--curve N``, re-described as
a smooth monotone cubic (PCHIP) through the root chord and N control chords at equal fractions of
the half-span (the fit used by elastic_refine), and searched again on that mesh: +/- 10 mm then
5 mm on each control chord and +/- 20 mm then 10 mm on the half-span, same budget score.
``--baseline`` (with ``--from``): instead of searching, solve each seed's original study outline
(tripled stations, straight segments) on the ``--chord-panels`` mesh and write OUT/baseline.json,
so the study pick and the optimized wing can be compared on the same mesh.
``--gif DIR --summaries A B ...`` writes one evolution GIF per seed through every stage in order.

``--search-mesh`` (first stage): search on the 8 x 4 mesh every atlas wing is compared on, starting from the seed
exactly as solved (its own stations, straight segments), so the result can only match or beat it; with ``--curve N``
the outline is instead a PCHIP curve through N control chords sampled at 9 stations. The time step is halved up to
twice until verified. ``--pool-freqs F...`` picks seeds over all those frequencies together (each seed keeps its own):
the best wing under each budget at whichever frequency, as the Top tab shows it. ``--extra-cases FILE...`` adds
seed candidates from 8 x 4 results outside the studies: wingstudy.freq_explore results (both the as-found and the
budget-rescaled solves) and the 8 x 4 frequency sweep of the optimized wings, at ``--freq``.
"""
from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from . import elastic_refine as ER
from .studies import spec as S

LEVELS = (0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
FACTOR = 3
SHEET_M = 0.400
SPAN_LIMITS = (0.150, 0.800)
CHORD_STEPS = (0.010, 0.005)
SPAN_STEPS = (0.020, 0.010)
OUT = S.ROOT / "outputs" / "refine-top"


def faav_cases(results: list[dict], freq: float = 1.0) -> list[dict]:
    out, seen = [], set()
    for r in results:
        for c in r["cases"]:
            if (c.get("model") == "t0.50" and c.get("structure", "chordwise") == "chordwise" and abs(c["freq"] - freq) < 1e-9
                    and c.get("status") == "verified" and c.get("thrust_N") and c.get("torque_Nm") and c["key"] not in seen):
                seen.add(c["key"])
                out.append(c)
    return out


def atlas_cases(freq: float = 1.0) -> list[dict]:
    """FAAV cases from the whole atlas (atlas/data plus completed studies), in the study results' case format.

    The original campaigns (rod, plate) are only in atlas/data, so --atlas is how their standouts become seeds.
    """
    import sys
    sys.path.insert(0, str(S.ROOT / "tools"))
    import atlas_data
    from .studies import atlas as A
    D = atlas_data.assemble(S.ROOT / "atlas" / "data")
    atlas_data.drop_models(D)
    A.merge(D, A.completed(S.ROOT / "studies"))
    c, n = D["cols"], len(D["cols"]["s"])
    mi = next(i for i, m in enumerate(D["models"]) if m["id"] == "t0.50")
    end = (D.get("catalog") or {}).get("end", n)
    out, seen = [], set()
    for i in range(n):
        if D.get("catalog") and D["catalog"].get("first", n) <= i < end:
            continue
        if (c["m"][i] != mi or abs(D["freqs"][c["f"][i]] - freq) > 1e-9 or D["statuses"][c["S"][i]] != "verified"
                or not c["T"][i] or not c["Q"][i] or c["k"][i] in seen):
            continue
        seen.add(c["k"][i])
        out.append({"key": c["k"][i], "model": "t0.50", "structure": "chordwise", "freq": freq, "status": "verified",
                    "chords_mm": list(c["C"][8 * i:8 * i + 8]), "half_span_mm": c["H"][i],
                    "thrust_N": c["T"][i], "torque_Nm": c["Q"][i], "study": D["studies"][c["s"][i]]["id"]})
    return out


def effective_span_mm(c: dict) -> float:
    ch = c["chords_mm"]
    n = next((j for j, x in enumerate(ch) if x == 0), len(ch))
    return c["half_span_mm"] * (n - 1) / (len(ch) - 1)


def pick_seeds(cases: list[dict], levels=LEVELS, sheet_only: bool = False, freq: float = 1.0, free_span: bool = False) -> list[dict]:
    """Standouts per budget. With ``free_span``, a budget whose best wing already fits one sheet also gets an
    'any' seed from that wing, searched without the 400 mm cap, so every budget has a free-span search."""
    seeds = []
    for B in levels:
        ok = [c for c in cases if c["torque_Nm"] <= B]
        best = max(ok, key=lambda c: c["thrust_N"], default=None)
        sheet = max((c for c in ok if effective_span_mm(c) <= SHEET_M * 1000 + 0.5), key=lambda c: c["thrust_N"], default=None)
        pairs = ((sheet, True),) if sheet_only else ((best, best is not None and effective_span_mm(best) <= SHEET_M * 1000 + 0.5), (sheet, True))
        if free_span and not sheet_only and best is not None and pairs[0][1]:
            pairs = pairs + ((best, False),)
        for c, single in pairs:
            if c is None or any(s["case"]["key"] == c["key"] and s["budget"] == B and s["single_sheet"] == single for s in seeds):
                continue
            f = c.get("freq", freq)
            seeds.append({"id": f"{'' if abs(f - 1.0) < 1e-9 else f'F{f:g}-'}B{B:g}-{'sheet' if single else 'any'}-{c['key'][:8]}",
                          "budget": B, "single_sheet": single, "case": c, "freq": f})
    return seeds


def refine_outline(chords_mm, half_span_mm, factor=FACTOR):
    """Same outline on factor x as many segments: (outboard chords in m, active half-span in m)."""
    active = [c for c in chords_mm if c > 0]
    span = half_span_mm * (len(active) - 1) / (len(chords_mm) - 1)
    n = (len(active) - 1) * factor + 1
    pts = []
    for k in range(n):
        x = k / factor
        j = min(int(x), len(active) - 2)
        t = x - j
        pts.append(active[j] * (1 - t) + active[j + 1] * t)
    pts[0] = ER.ROOT_CHORD * 1000
    prev, ctrl = ER.ROOT_CHORD, []
    for c in pts[1:]:
        prev = min(prev, max(ER.MIN_CHORD, round(c / 1000, 5)))
        ctrl.append(prev)
    return ctrl, round(span / 1000, 5)


def numerics_for(n_segments: int, chord_panels: int = 4, param: str = "exact", freq: float = 1.0) -> dict:
    """Solve settings; "freq" is only added away from 1 Hz, so the 1 Hz cache keys stay as they were."""
    out = {"stations": n_segments + 1, "span_panels": n_segments, "chord_panels": chord_panels, "steps_per_cycle": 50,
           "cycles": 4, "dt_refinements": [1, 2], "param": param}
    if abs(freq - 1.0) > 1e-9:
        out["freq"] = freq
    return out


def outline_mm(ctrl, numerics) -> list[float]:
    """Chords (mm) at the mesh stations for a control vector, exact or PCHIP."""
    if numerics.get("param") == "exact":
        return [round(1000 * x, 2) for x in ER.chords_from_ctrl(ctrl, 0, "exact")]
    return [round(1000 * x, 2) for x in ER.chords_from_ctrl(ctrl, numerics["stations"], numerics.get("param"))]


def fit_curve(chords_mm, n_ctrl):
    """PCHIP control chords (m) through a station outline: its values at k/n of the half-span, kept monotone."""
    import numpy as np
    ys = np.linspace(0, 1, len(chords_mm))
    out, prev = [], ER.ROOT_CHORD
    for k in range(1, n_ctrl + 1):
        c = float(np.interp(k / n_ctrl, ys, chords_mm)) / 1000
        prev = min(prev, max(ER.MIN_CHORD, round(c, 5)))
        out.append(prev)
    return out


def search_mesh_numerics(freq: float, stations: int = 9, param: str = "pchip") -> dict:
    out = {"stations": stations, "span_panels": 8, "chord_panels": 4, "steps_per_cycle": 50, "cycles": 4, "dt_refinements": [1, 2, 4],
           "param": param}
    if abs(freq - 1.0) > 1e-9:
        out["freq"] = freq
    return out


def extra_cases(paths, freq: float) -> list[dict]:
    """8 x 4 results outside the studies as seed candidates (freq_explore results, 8 x 4 frequency sweep)."""
    out = {}
    def add(key, chords, r, study):
        if r and r.get("status") in ("ok", "verified") and r.get("thrust") is not None and key:
            out.setdefault(key, {"key": key, "model": "t0.50", "structure": "chordwise", "freq": freq, "status": "verified",
                                 "chords_mm": list(chords), "half_span_mm": r["half_span_mm"], "thrust_N": r["thrust"],
                                 "torque_Nm": r["torque"], "study": study})
    for p in paths:
        d = S.read_json(p)
        for x in d.get("results", []):                                    # freq_explore
            if abs(x["freq"] - freq) < 1e-9:
                for kind in ("fixed", "matched"):
                    add((x.get(kind) or {}).get("key"), x["chords_mm"], x.get(kind), "freq-explore")
        if str(d.get("mesh", "")).startswith("8 x 4"):                    # frequency_sweep --mesh 8 4
            for w in d.get("wings", []):
                for q in w["points"]:
                    if abs(q["freq"] - freq) < 1e-9:
                        for kind in ("fixed", "matched"):
                            add((q.get(kind) or {}).get("key"), w["chords_mm"], q.get(kind), "optimized-8x4")
    return list(out.values())


class Search:
    def __init__(self, seed: dict, factor: int, max_rounds: int, chord_panels: int = 4, curve: int = 0, search_mesh: bool = False):
        self.seed, self.budget = seed, seed["budget"]
        f = seed.get("freq", 1.0)
        c = seed["case"]
        self.recheck = None
        if seed.get("ctrl"):                                    # second stage: start from a refined outline
            n = len(seed["ctrl"])
            self.recheck_numerics = numerics_for(n, chord_panels, "exact", f)
            if curve:
                self.ctrl, self.span = fit_curve(outline_mm(seed["ctrl"], {"param": "exact"}), curve), seed["span"]
                self.numerics = numerics_for(n, chord_panels, "pchip", f)
            else:
                self.ctrl, self.span, self.numerics = list(seed["ctrl"]), seed["span"], self.recheck_numerics
        elif search_mesh:                                       # on the 8 x 4 search mesh
            active = [x for x in c["chords_mm"] if x > 0]
            self.span = round(effective_span_mm(c) / 1000, 5)
            if curve:                                           # smooth curve through `curve` control chords
                self.ctrl, self.numerics = fit_curve(active, curve), search_mesh_numerics(f)
            else:                                               # the seed's own stations: the start IS the seed
                self.ctrl = [round(x / 1000, 5) for x in active[1:]]
                self.numerics = search_mesh_numerics(f, len(active), "exact")
        else:
            self.ctrl, self.span = refine_outline(c["chords_mm"], c["half_span_mm"], factor)
            self.numerics = numerics_for(len(self.ctrl), chord_panels, freq=f)
        self.span_max = SHEET_M if seed["single_sheet"] else SPAN_LIMITS[1]
        self.step_i, self.rounds, self.max_rounds = 0, 0, max_rounds
        self.current, self.history, self.done, self.note = None, [], False, ""

    def score(self, rec):
        if rec is None or rec["status"] not in ("ok", "verified") or rec["thrust"] is None or rec["torque"] is None:
            return None
        return rec["thrust"] if rec["torque"] <= self.budget else -10.0 - (rec["torque"] - self.budget)

    def task(self, ctrl, span, tag, numerics=None):
        ctrl, span, num = [round(x, 5) for x in ctrl], round(span, 5), numerics or self.numerics
        return {"key": ER.key_of("t0.50", ctrl, span, num), "model": "t0.50", "ctrl": ctrl, "span": span,
                "numerics": num, "tag": tag}

    def candidates(self):
        cs, ss, out, n = CHORD_STEPS[self.step_i], SPAN_STEPS[self.step_i], [], len(self.ctrl)
        for i in range(n):
            for sgn in (1, -1):
                c = list(self.ctrl)
                hi = ER.ROOT_CHORD if i == 0 else c[i - 1]
                lo = ER.MIN_CHORD if i == n - 1 else max(ER.MIN_CHORD, c[i + 1])
                v = min(hi, max(lo, c[i] + sgn * cs))
                if abs(v - c[i]) > 1e-9:
                    c[i] = v
                    out.append(self.task(c, self.span, f"c{i + 1}{'+' if sgn > 0 else '-'}{cs * 1000:g}mm"))
        for sgn in (1, -1):
            s = min(self.span_max, max(SPAN_LIMITS[0], self.span + sgn * ss))
            if abs(s - self.span) > 1e-9:
                out.append(self.task(self.ctrl, s, f"span{'+' if sgn > 0 else '-'}{ss * 1000:g}mm"))
        return out

    def accept(self, recs):
        self.rounds += 1
        cur = self.score(self.current)
        best = max(((self.score(r), r) for r in recs if self.score(r) is not None and self.score(r) > cur + 1e-6),
                   key=lambda x: x[0], default=None)
        if best:
            self.current, self.ctrl, self.span = best[1], list(best[1]["ctrl"]), best[1]["span"]
            self.history.append({"round": self.rounds, **best[1], "score": best[0]})
        elif self.step_i + 1 < len(CHORD_STEPS):
            self.step_i += 1
        else:
            self.done, self.note = True, f"no +/- {CHORD_STEPS[-1] * 1000:g} mm chord or {SPAN_STEPS[-1] * 1000:g} mm span move improves"
        if self.rounds >= self.max_rounds and not self.done:
            self.done, self.note = True, f"round limit ({self.max_rounds})"

    def summary(self):
        c, f = self.seed["case"], self.current or {}
        start = self.history[0] if self.history else {}
        return {"id": self.seed["id"], "budget_Nm": self.budget, "single_sheet": self.seed["single_sheet"],
                "freq": self.seed.get("freq", 1.0),
                "source": {"key": c["key"], "chords_mm": c["chords_mm"], "half_span_mm": c["half_span_mm"],
                           "thrust_N": c["thrust_N"], "torque_Nm": c["torque_Nm"]},
                "numerics": self.numerics, "rounds": self.rounds, "note": self.note,
                "previous": self.seed.get("previous"),
                "recheck": {k: self.recheck.get(k) for k in ("status", "thrust", "torque", "tip_twist", "span")} if self.recheck else None,
                "start": {k: start.get(k) for k in ("status", "thrust", "torque", "tip_twist", "span", "ctrl")},
                "final": {k: f.get(k) for k in ("status", "thrust", "torque", "tip_twist", "span", "ctrl")},
                "final_chords_mm": outline_mm(f["ctrl"], self.numerics) if f.get("ctrl") else None,
                "history": [dict(h, chords_mm=outline_mm(h["ctrl"], self.numerics)) if h.get("ctrl") else h for h in self.history]}


def seeds_from_summary(path: Path) -> list[dict]:
    """Second-stage seeds: each refined final outline of a finished summary, same id and budget."""
    out = []
    for x in S.read_json(path)["seeds"]:
        f = x.get("final") or {}
        if f.get("ctrl") and f.get("status") in ("ok", "verified"):
            out.append({"id": x["id"], "budget": x["budget_Nm"], "single_sheet": x["single_sheet"], "case": x["source"],
                        "ctrl": f["ctrl"], "span": f["span"], "previous": {k: f.get(k) for k in ("thrust", "torque", "span")},
                        "freq": x.get("freq", (x.get("numerics") or {}).get("freq", 1.0))})
    return out


def _xy(ch, span_mm):
    n = len(ch)
    ys = [span_mm * i / (n - 1) for i in range(n)]
    return ys + ys[::-1] + [0.0], [0.0] * n + [-c for c in ch][::-1] + [0.0]


def write_gifs(summaries: list[Path], out: Path) -> list[Path]:
    """One GIF per seed id: the study outline (dashed) and every accepted step of every stage, to scale."""
    import io
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    stages = [S.read_json(p) for p in summaries]
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for first in stages[0]["seeds"]:
        sid, B, src = first["id"], first["budget_Nm"], first["source"]
        steps = []
        for st in stages:
            x = next((q for q in st["seeds"] if q["id"] == sid), None)
            if not x:
                continue
            num = x["numerics"]
            label = f"{num['span_panels']} × {num['chord_panels']}" + (", smooth curve" if num.get("param") == "pchip" else "")
            for h in x["history"]:
                if h.get("ctrl") and h.get("thrust") is not None:
                    steps.append((label, h["round"], h.get("chords_mm") or outline_mm(h["ctrl"], num), h["span"], h["thrust"], h["torque"]))
        if not steps:
            continue
        act = [c for c in src["chords_mm"] if c > 0]
        x0, y0 = _xy(act, src["half_span_mm"] * (len(act) - 1) / (len(src["chords_mm"]) - 1))
        frames = []
        for label, rnd, ch, span, T, Q in steps + [steps[-1]] * 6:
            fig, ax = plt.subplots(figsize=(7, 3.2))
            ax.plot(x0, y0, color="#b0afa9", lw=1, ls="--")
            xs, ys = _xy(ch, span * 1000)
            over = Q > B + 1e-9
            col = "#e08a00" if over else "#2a78d6"
            ax.fill(xs, ys, color=col, alpha=0.22, lw=0)
            ax.plot(xs, ys, color=col, lw=1.6)
            ax.set_aspect("equal"); ax.set_xlim(-5, 410); ax.set_ylim(-215, 8); ax.axis("off")
            ax.set_title(f"≤ {B:g} N·m · {label} mesh, round {rnd}: {T:.3f} N at {Q:.3f} N·m"
                         f"{' (over budget)' if over else ''}, {span * 1000:.0f} mm", fontsize=8.5, loc="left")
            ax.text(0, -213, "dashed: study result (8 stations, 8 × 4 mesh)", fontsize=7, color="#77766f")
            buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=80, facecolor="white"); plt.close(fig)
            buf.seek(0); frames.append(Image.open(buf).convert("P", palette=Image.ADAPTIVE))
        path = out / f"{sid}.gif"
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=300, loop=0)
        written.append(path)
    return written


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m wingstudy.refine_top", description=__doc__.split("\n\n")[0])
    ap.add_argument("studies", nargs="*", help="finished study ids to take the FAAV standouts from")
    ap.add_argument("--from", dest="from_summary", type=Path, help="second stage: start from this summary's refined outlines")
    ap.add_argument("--chord-panels", type=int, default=4, help="chordwise panels (default 4; 12 = three times finer)")
    ap.add_argument("--curve", type=int, default=0, help="with --from: search a PCHIP outline with this many control chords")
    ap.add_argument("--gif", type=Path, help="write evolution GIFs to this folder from --summaries, then stop")
    ap.add_argument("--summaries", type=Path, nargs="*", default=[], help="summaries in stage order, for --gif")
    ap.add_argument("--atlas", action="store_true", help="pick seeds from every FAAV wing in the atlas (campaigns included), not only the named studies")
    ap.add_argument("--freq", type=float, default=1.0, help="flapping frequency in Hz (default 1; seeds are picked at this frequency)")
    ap.add_argument("--baseline", action="store_true", help="with --from: solve the original study outlines on the --chord-panels mesh only")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--factor", type=int, default=FACTOR, help="chord segments per original segment (default 3)")
    ap.add_argument("--max-rounds", type=int, default=20)
    ap.add_argument("--levels", type=float, nargs="+", default=list(LEVELS), help="torque budgets to pick standouts at (N*m)")
    ap.add_argument("--sheet-only", action="store_true", help="only single-sheet (<= 400 mm) standouts, kept within one sheet")
    ap.add_argument("--free-span", action="store_true", help="also search each budget's best wing without the 400 mm cap when it fits one sheet")
    ap.add_argument("--search-mesh", action="store_true", help="first stage: search on the 8 x 4 mesh from the exact seed (or a --curve outline)")
    ap.add_argument("--pool-freqs", type=float, nargs="+", help="pick seeds over these frequencies together (with --atlas / --extra-cases)")
    ap.add_argument("--extra-cases", type=Path, nargs="*", default=[], help="8 x 4 result files to also pick seeds from (freq_explore, frequency_sweep --mesh 8 4)")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--dry", action="store_true", help="list the seeds and the first round's size, solve nothing")
    a = ap.parse_args(argv)
    if a.gif:
        for p in write_gifs(a.summaries, a.gif):
            print("wrote", p)
        return 0
    if a.from_summary:
        seeds = seeds_from_summary(a.from_summary)
    else:
        results = [S.read_json(S.study_dir(s) / "results.json") for s in a.studies if (S.study_dir(s) / "results.json").exists()]
        cases = []
        for fq in (a.pool_freqs or [a.freq]):
            cases += faav_cases(results, fq)
            if a.atlas:
                have = {c["key"] for c in cases}
                cases += [c for c in atlas_cases(fq) if c["key"] not in have]
            if a.extra_cases:
                have = {c["key"] for c in cases}
                cases += [c for c in extra_cases(a.extra_cases, fq) if c["key"] not in have]
        seeds = pick_seeds(cases, a.levels, a.sheet_only, a.freq, a.free_span)
    if not seeds:
        print("no verified FAAV wings to start from")
        return 1
    searches = [Search(s, a.factor, a.max_rounds, a.chord_panels, a.curve if (a.from_summary or a.search_mesh) else 0,
                       search_mesh=a.search_mesh and not a.from_summary) for s in seeds]
    for s in searches:
        c = s.seed["case"]
        kind = "curve control chords" if s.numerics.get("param") == "pchip" else "chords"
        print(f"{s.seed['id']}: {c['thrust_N']:.3f} N at {c['torque_Nm']:.3f} N·m -> {len(s.ctrl)} {kind}, "
              f"{s.numerics['span_panels']} × {s.numerics['chord_panels']} panels, {len(s.candidates())} moves per round")
    if a.dry:
        return 0
    a.out.mkdir(parents=True, exist_ok=True)
    cache_path = a.out / "cache.jsonl"
    cache = {}
    if cache_path.exists():
        for line in cache_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                cache[r["key"]] = r

    def solve_all(pool, tasks):
        todo = {t["key"]: t for t in tasks if t["key"] not in cache}
        if todo:
            with cache_path.open("a", encoding="utf-8") as fh:
                for r in pool.map(ER._solve, list(todo.values())):
                    cache[r["key"]] = r
                    fh.write(json.dumps(r) + "\n")
                    fh.flush()
        return [dict(cache[t["key"]], tag=t["tag"]) for t in tasks]

    def write():
        S.write_json(a.out / "summary.json", {"factor": a.factor, "levels": a.levels, "studies": a.studies,
                                              "from": str(a.from_summary) if a.from_summary else None,
                                              "chord_panels": a.chord_panels, "curve": a.curve,
                                              "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                              "seeds": [s.summary() for s in searches]})

    if a.baseline:
        if not a.from_summary:
            print("--baseline needs --from")
            return 1
        tasks = []
        for s in searches:
            ctrl, span = refine_outline(s.seed["case"]["chords_mm"], s.seed["case"]["half_span_mm"], a.factor)
            tasks.append(s.task(ctrl, span, "study outline on the finer mesh",
                                numerics_for(len(ctrl), a.chord_panels, freq=s.seed.get("freq", 1.0))))
        with ProcessPoolExecutor(max_workers=a.workers) as pool:
            recs = solve_all(pool, tasks)
        out = [{"id": s.seed["id"], "budget_Nm": s.budget, "key": r["key"], "numerics": t["numerics"],
                **{k: r.get(k) for k in ("status", "thrust", "torque", "tip_twist", "span")}} for s, t, r in zip(searches, tasks, recs)]
        S.write_json(a.out / "baseline.json", {"from": str(a.from_summary), "chord_panels": a.chord_panels, "factor": a.factor,
                                               "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "seeds": out})
        for x in out:
            print(f"{x['id']}: study outline on {x['numerics']['span_panels']} x {x['numerics']['chord_panels']}: "
                  f"{x['thrust']} N at {x['torque']} N·m ({x['status']})")
        return 0

    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        if a.from_summary:                                      # the refined outline itself on the new mesh
            checks = solve_all(pool, [s.task(s.seed["ctrl"], s.seed["span"], "recheck (refined outline, finer mesh)",
                                             s.recheck_numerics) for s in searches])
            for s, r in zip(searches, checks):
                s.recheck = r
        if a.from_summary:
            start_tag = "start (smooth-curve fit of the refined outline)" if a.curve else "start (refined outline)"
        else:
            start_tag = "start (same outline, tripled stations)"
        starts = solve_all(pool, [s.task(s.ctrl, s.span, start_tag) for s in searches])
        for s, r in zip(searches, starts):
            s.current = r
            s.history.append({"round": 0, **r, "score": s.score(r)})
            if s.score(r) is None:
                s.done, s.note = True, "start did not verify on the refined description"
        write()
        while any(not s.done for s in searches):
            live = [s for s in searches if not s.done]
            batches = [s.candidates() for s in live]
            got = solve_all(pool, [t for b in batches for t in b])
            k = 0
            for s, b in zip(live, batches):
                s.accept(got[k:k + len(b)])
                k += len(b)
            write()
            print(time.strftime("%H:%M:%S"), " · ".join(f"{s.seed['id']} r{s.rounds} {(s.current or {}).get('thrust') or 0:.3f} N"
                                                        for s in searches), flush=True)
    for s in searches:
        x = s.summary()
        print(f"{x['id']}: coarse {x['source']['thrust_N']:.3f} N -> start {x['start']['thrust']} -> final {x['final']['thrust']} "
              f"at {x['final']['torque']} N·m ({x['note']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
