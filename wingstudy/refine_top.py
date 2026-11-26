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


def effective_span_mm(c: dict) -> float:
    ch = c["chords_mm"]
    n = next((j for j, x in enumerate(ch) if x == 0), len(ch))
    return c["half_span_mm"] * (n - 1) / (len(ch) - 1)


def pick_seeds(cases: list[dict], levels=LEVELS, sheet_only: bool = False) -> list[dict]:
    seeds = []
    for B in levels:
        ok = [c for c in cases if c["torque_Nm"] <= B]
        best = max(ok, key=lambda c: c["thrust_N"], default=None)
        sheet = max((c for c in ok if effective_span_mm(c) <= SHEET_M * 1000 + 0.5), key=lambda c: c["thrust_N"], default=None)
        pairs = ((sheet, True),) if sheet_only else ((best, best is not None and effective_span_mm(best) <= SHEET_M * 1000 + 0.5), (sheet, True))
        for c, single in pairs:
            if c is None or any(s["case"]["key"] == c["key"] and s["budget"] == B for s in seeds):
                continue
            seeds.append({"id": f"B{B:g}-{'sheet' if single else 'any'}-{c['key'][:8]}", "budget": B,
                          "single_sheet": single, "case": c})
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


def numerics_for(n_segments: int) -> dict:
    return {"stations": n_segments + 1, "span_panels": n_segments, "chord_panels": 4, "steps_per_cycle": 50,
            "cycles": 4, "dt_refinements": [1, 2], "param": "exact"}


class Search:
    def __init__(self, seed: dict, factor: int, max_rounds: int):
        self.seed, self.budget = seed, seed["budget"]
        c = seed["case"]
        self.ctrl, self.span = refine_outline(c["chords_mm"], c["half_span_mm"], factor)
        self.span_max = SHEET_M if seed["single_sheet"] else SPAN_LIMITS[1]
        self.numerics = numerics_for(len(self.ctrl))
        self.step_i, self.rounds, self.max_rounds = 0, 0, max_rounds
        self.current, self.history, self.done, self.note = None, [], False, ""

    def score(self, rec):
        if rec is None or rec["status"] not in ("ok", "verified") or rec["thrust"] is None or rec["torque"] is None:
            return None
        return rec["thrust"] if rec["torque"] <= self.budget else -10.0 - (rec["torque"] - self.budget)

    def task(self, ctrl, span, tag):
        ctrl, span = [round(x, 5) for x in ctrl], round(span, 5)
        return {"key": ER.key_of("t0.50", ctrl, span, self.numerics), "model": "t0.50", "ctrl": ctrl, "span": span,
                "numerics": self.numerics, "tag": tag}

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
                "source": {"key": c["key"], "chords_mm": c["chords_mm"], "half_span_mm": c["half_span_mm"],
                           "thrust_N": c["thrust_N"], "torque_Nm": c["torque_Nm"]},
                "numerics": self.numerics, "rounds": self.rounds, "note": self.note,
                "start": {k: start.get(k) for k in ("status", "thrust", "torque", "tip_twist", "span", "ctrl")},
                "final": {k: f.get(k) for k in ("status", "thrust", "torque", "tip_twist", "span", "ctrl")},
                "final_chords_mm": [round(1000 * x, 2) for x in ER.chords_from_ctrl(f["ctrl"], 0, "exact")] if f.get("ctrl") else None,
                "history": self.history}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m wingstudy.refine_top", description=__doc__.split("\n\n")[0])
    ap.add_argument("studies", nargs="+", help="finished study ids to take the FAAV standouts from")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--factor", type=int, default=FACTOR, help="chord segments per original segment (default 3)")
    ap.add_argument("--max-rounds", type=int, default=20)
    ap.add_argument("--levels", type=float, nargs="+", default=list(LEVELS), help="torque budgets to pick standouts at (N*m)")
    ap.add_argument("--sheet-only", action="store_true", help="only single-sheet (<= 400 mm) standouts, kept within one sheet")
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--dry", action="store_true", help="list the seeds and the first round's size, solve nothing")
    a = ap.parse_args(argv)
    results = [S.read_json(S.study_dir(s) / "results.json") for s in a.studies if (S.study_dir(s) / "results.json").exists()]
    seeds = pick_seeds(faav_cases(results), a.levels, a.sheet_only)
    if not seeds:
        print("no verified FAAV wings in those studies")
        return 1
    searches = [Search(s, a.factor, a.max_rounds) for s in seeds]
    for s in searches:
        c = s.seed["case"]
        print(f"{s.seed['id']}: {c['thrust_N']:.3f} N at {c['torque_Nm']:.3f} N·m, {effective_span_mm(c):.0f} mm -> "
              f"{len(s.ctrl)} chords, {s.numerics['span_panels']} span panels, {len(s.candidates())} moves per round")
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
                                              "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                                              "seeds": [s.summary() for s in searches]})

    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        starts = solve_all(pool, [s.task(s.ctrl, s.span, "start (same outline, tripled stations)") for s in searches])
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
