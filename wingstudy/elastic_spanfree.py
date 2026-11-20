"""Span-free search: maximize thrust at exactly the 1 N·m torque budget, with a continuous half-span.

The rod and plate campaigns searched at five fixed nominal half-spans (150, 220, 280, 340, 400 mm), so
almost every design sits on one of those spans. Here span is not a search variable at all: every
candidate outline has its half-span rescaled (secant iterations on peak torque) until peak root
torque sits at the budget, clamped to 280-400 mm. A pattern search then moves the outboard station
chords (+/-20, then 10, then 5 mm), keeping the best move each round. Every candidate is therefore
compared at equal torque, and the span is whatever the torque budget allows.

Numerics, geometry rules, verification and storage are those of the campaigns (8 stations, 8 x 4
panels, 50 steps per cycle, 4 cycles, verified elastic solves), so results drop straight into the
atlas as another study. Starts per model: the best distinct campaign outlines at 1 Hz, the five seed
families and scrambled-Sobol outlines.

    python -m wingstudy.elastic_spanfree --workers 14            # full run (resumable: solves are cached)
    python -m wingstudy.elastic_spanfree --smoke --workers 14    # 2 starts per model, 2 rounds
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

from . import elastic_campaign as EC  # noqa: E402

OUT = ROOT / "outputs" / "elastic" / "campaigns" / "spanfree"
SOURCES = ["rod", "weekend", "sweep"]
LEVELS = ["rigid", "t0.50r", "t0.25r"]
FREQ = 1.0
SPAN_RANGE = (0.280, 0.400)          # effective half-span, m
TARGET, TOL = EC.TORQUE_TARGET - 0.004, 0.004   # aim just under the budget
STEPS = (0.020, 0.010, 0.005)
MIN_CHORD, ROOT_CHORD = 0.010, 0.200


def make_plan(smoke=False):
    plan = EC.default_plan(variant="sweep")
    plan["levels"] = [l for l in plan["levels"] if l["id"] in LEVELS]
    plan.update(name="Span-free search: thrust at the 1 N·m budget, continuous half-span 280-400 mm, 1 Hz",
                frequencies_hz=[FREQ], objectives={"focus": ["torque_1Nm"], "context": []},
                spanfree={"span_range_m": list(SPAN_RANGE), "steps_m": list(STEPS), "target_Nm": TARGET,
                          "starts": {"campaign_best": 2 if smoke else 12, "families": 0 if smoke else 5,
                                     "sobol": 0 if smoke else 12},
                          "max_rounds": 2 if smoke else 40})
    return plan


# ----------------------------------------------------------------------------------------
# Geometry: 8 stations, root fixed, non-increasing, >= 10 mm, optional zero tip suffix.
# A design is (active chords, effective span); stored as 8 chords + nominal half-span.
# ----------------------------------------------------------------------------------------
def to_stored(active, span):
    n = 8
    chords = [round(c, 4) for c in active] + [0.0] * (n - len(active))
    return chords, round(span * (n - 1) / (len(active) - 1), 5)


def active_of(chords, half_span):
    act = [c for c in chords if c > 0]
    return act, half_span * (len(act) - 1) / (len(chords) - 1)


def valid(active):
    if abs(active[0] - ROOT_CHORD) > 1e-9:
        return False
    return all(MIN_CHORD - 1e-9 <= c <= p + 1e-9 for p, c in zip(active, active[1:]))


# ----------------------------------------------------------------------------------------
# Worker: solve one outline at the span that uses the budget
# ----------------------------------------------------------------------------------------
def _project(job):
    """Secant on effective span until torque is within TOL under the budget. Returns every record."""
    plan, level, active, span0, db_path = job["plan"], job["level"], job["active"], job["span"], job["db"]
    lv = {l["id"]: l for l in plan["levels"]}[level]
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30)

    def solve(span):
        chords, hs = to_stored(active, span)
        key = EC.design_key(level, FREQ, chords, hs)
        row = db.execute("select status,thrust,torque from designs where key=?", (key,)).fetchone()
        if row:
            return {"key": key, "status": row[0], "thrust": row[1], "torque": row[2], "chords": chords,
                    "half_span": hs, "cached": True}
        task = {"key": key, "level": level, "freq": FREQ, "chords": chords, "half_span": hs,
                "thickness_mm": lv["thickness_mm"], "rod": lv.get("rod"), "material": plan["material"],
                "template": plan["template_case"], "steps_per_cycle": plan["steps_per_cycle"], "cycles": plan["cycles"],
                "span_panels": plan["span_panels"], "chord_panels": plan["chord_panels"],
                "dt_refinements": plan["dt_refinements"], "numerics": "base"}
        return EC._evaluate(task)

    ok = lambda r: r["status"] in ("verified", "ok") and r["thrust"] is not None and r["torque"] is not None
    recs, pts, best = [], [], None
    span = span0
    for _ in range(6):
        span = round(min(SPAN_RANGE[1], max(SPAN_RANGE[0], span)), 4)
        r = solve(span); r["eff_span"] = span; recs.append(r)
        if not ok(r):
            break
        if r["torque"] <= EC.TORQUE_TARGET and (best is None or r["thrust"] > best["thrust"]):
            best = r
        if abs(r["torque"] - TARGET) < TOL:
            break
        pts.append((span, r["torque"]))
        if len(pts) == 1:
            new = span * (TARGET / r["torque"]) ** (1 / 2.5)       # torque grows roughly as span^2.5
        else:
            (s0, q0), (s1, q1) = pts[-2], pts[-1]
            new = s1 + (TARGET - q1) * (s1 - s0) / (q1 - q0) if q1 != q0 else s1
        new = min(SPAN_RANGE[1], max(SPAN_RANGE[0], new))
        if abs(new - span) < 2e-4:
            break                                                  # pinned at a span limit
        span = new
    db.close()
    return {"job": job["id"], "records": recs, "best": best}


# ----------------------------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------------------------
class Start:
    def __init__(self, level, sid, family, active, span):
        self.level, self.id, self.family = level, sid, family
        self.active, self.span = list(active), span
        self.step_i, self.rounds, self.done, self.current, self.seq = 0, 0, False, None, 0
        self.note = ""

    @property
    def search_id(self):
        return f"{self.level}@1Hz/spanfree"

    def candidates(self):
        step = STEPS[self.step_i]
        out = []
        for i in range(1, len(self.active)):
            for sgn in (1, -1):
                a = list(self.active)
                a[i] = round(min(a[i - 1], max(MIN_CHORD, a[i] + sgn * step)), 4)
                if i + 1 < len(a):
                    a[i] = max(a[i], a[i + 1])
                if abs(a[i] - self.active[i]) > 1e-9 and valid(a):
                    out.append((f"c{i}{'+' if sgn > 0 else '-'}{step * 1000:g}mm", a))
        return out


def starts_for(plan, level):
    sf = plan["spanfree"]["starts"]
    starts, seen = [], set()

    def add(family, chords, hs):
        act, span = active_of(chords, hs)
        act = [ROOT_CHORD] + [round(max(MIN_CHORD, c), 4) for c in act[1:]]
        for k in range(1, len(act)):
            act[k] = min(act[k], act[k - 1])
        sig = tuple(round(c, 3) for c in act)
        if len(act) < 3 or sig in seen or not valid(act):
            return
        seen.add(sig)
        starts.append(Start(level, f"L{len(starts):02d}", family, act, min(SPAN_RANGE[1], max(SPAN_RANGE[0], span))))

    # 1. best distinct 1 Hz outlines (<= 1 N·m) from the campaigns, any model, best first
    rows = []
    for src in SOURCES:
        p = ROOT / "outputs" / "elastic" / "campaigns" / src / "campaign.sqlite"
        if p.exists():
            db = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
            rows += db.execute("select chords, half_span, thrust from designs where level=? and abs(freq-1)<1e-9 and "
                               "numerics='base' and status in ('verified','ok') and torque<=1.0 order by thrust desc limit 400",
                               (level,)).fetchall()
            db.close()
    n0 = len(starts)
    for ch, hs, _ in sorted(rows, key=lambda r: -r[2]):
        if len(starts) - n0 >= sf["campaign_best"]:
            break
        add("campaign best", json.loads(ch), hs)
    # 2. the five seed families
    for fam in EC.FAMILIES[:sf["families"]]:
        add(fam, EC.seed_chords(plan, fam), 0.34)
    # 3. scrambled-Sobol outlines
    if sf["sobol"]:
        sp = dict(plan, map=dict(plan["map"], seed=23))
        for s in EC.sobol_shapes(sp, 4 * sf["sobol"]):
            if sum(1 for x in starts if x.family == "sobol") >= sf["sobol"]:
                break
            add("sobol", s["chords"], s["half_span"])
    return starts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--smoke", action="store_true")
    a = ap.parse_args(argv)
    os.environ.update({k: "1" for k in ("NUMBA_NUM_THREADS", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")})
    a.out.mkdir(parents=True, exist_ok=True)
    store = EC.Store(a.out / "campaign.sqlite")
    plan = store.get_meta("plan")
    if plan is None:
        plan = make_plan(a.smoke)
        store.set_meta("plan", plan)
        (a.out / "plan.json").write_text(json.dumps(plan, indent=1))
    log = open(a.out / "spanfree.log", "a")

    def say(msg):
        line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
        print(line, flush=True); log.write(line + "\n"); log.flush()

    starts = [s for lv in LEVELS for s in starts_for(plan, lv)]
    for lv in LEVELS:
        sid = f"{lv}@1Hz/spanfree"
        n = sum(1 for s in starts if s.level == lv)
        store.execute("insert or ignore into searches(search_id,phase,level,freq,objective,status,lineages) values(?,?,?,?,?,?,?)",
                      (sid, "spanfree", lv, FREQ, "torque_1Nm", "climbing", n))
    for s in starts:
        store.execute("insert or replace into lineages values(?,?,?,?,?,?,?,?)",
                      (s.search_id, s.id, s.span, s.family, "running", 0, None, None))
    say(f"{len(starts)} starts ({', '.join(f'{lv}: {sum(1 for s in starts if s.level == lv)}' for lv in LEVELS)}); "
        f"workers {a.workers}")
    pool = ProcessPoolExecutor(a.workers)
    db_path = str(a.out / "campaign.sqlite")
    t0 = time.time()

    def run(batch):
        """batch: list of (start, tag, active, span). Returns list of best records (or None) in order."""
        jobs = [{"id": i, "plan": plan, "level": st.level, "active": act, "span": sp, "db": db_path}
                for i, (st, tag, act, sp) in enumerate(batch)]
        res = [None] * len(jobs)
        futs = [pool.submit(_project, j) for j in jobs]
        for fu in as_completed(futs):
            try:
                out = fu.result()
            except Exception as exc:  # noqa: BLE001
                say(f"  worker failed: {exc!r}"); continue
            st, tag = batch[out["job"]][0], batch[out["job"]][1]
            for r in out["records"]:
                if not r.get("cached"):
                    store.save(r)
                store.execute("insert or ignore into uses values(?,?,?,?,?,?)",
                              (r["key"], "search", st.search_id, st.id, "seed" if tag == "start" else "trial", "spanfree"))
            res[out["job"]] = out["best"]
        return res

    # starting points, each resized to the budget
    for st, rec in zip(starts, run([(s, "start", s.active, s.span) for s in starts])):
        if rec is None:
            st.done = True; st.note = "start did not solve at any span within the budget"
            continue
        st.current = rec; st.span = rec["eff_span"]
        accept(store, st, rec, "start")
    say("starts solved: " + "; ".join(f"{lv} best {max((s.current['thrust'] for s in starts if s.level == lv and s.current), default=0):.3f} N"
                                      for lv in LEVELS))
    max_rounds = plan["spanfree"]["max_rounds"]
    while any(not s.done for s in starts):
        active = [s for s in starts if not s.done]
        batch = [(s, tag, act, s.span) for s in active for tag, act in s.candidates()]
        say(f"round: {len(active)} active starts, {len(batch)} candidates, {(time.time() - t0) / 3600:.2f} h elapsed")
        res = run(batch)
        by = {}
        for (s, tag, act, _), rec in zip(batch, res):
            if rec is not None and rec["torque"] <= EC.TORQUE_TARGET:
                k = (s.level, s.id)
                if rec["thrust"] > s.current["thrust"] + 1e-6 and (k not in by or rec["thrust"] > by[k][2]["thrust"]):
                    by[k] = (tag, act, rec)
        for s in active:
            s.rounds += 1
            hit = by.get((s.level, s.id))
            if hit:
                tag, act, rec = hit
                s.active, s.current, s.span = act, rec, rec["eff_span"]
                accept(store, s, rec, tag)
            elif s.step_i + 1 < len(STEPS):
                s.step_i += 1
            else:
                s.done = True; s.note = f"no +/-{STEPS[-1] * 1000:g} mm move improves thrust at the budget"
            if s.rounds >= max_rounds and not s.done:
                s.done = True; s.note = f"round limit ({max_rounds})"
            if s.done:
                store.execute("update lineages set status=?, evals=? where search_id=? and lineage=?",
                              ("complete", s.rounds, s.search_id, s.id))
        for lv in LEVELS:
            b = max((s for s in starts if s.level == lv and s.current), key=lambda s: s.current["thrust"], default=None)
            if b:
                say(f"  {lv}: best {b.current['thrust']:.3f} N @ {b.current['torque']:.3f} N·m, half-span "
                    f"{b.span * 1000:.0f} mm ({b.id} {b.family}); {sum(1 for s in starts if s.level == lv and not s.done)} active")
    for lv in LEVELS:
        b = max((s for s in starts if s.level == lv and s.current), key=lambda s: s.current["thrust"], default=None)
        store.execute("update searches set status=?, best_key=?, best_score=? where search_id=?",
                      ("complete", b.current["key"] if b else None, b.current["thrust"] if b else None, f"{lv}@1Hz/spanfree"))
    summary = [{"level": s.level, "start": s.id, "family": s.family, "thrust": s.current and s.current["thrust"],
                "torque": s.current and s.current["torque"], "span_mm": round(s.span * 1000, 1),
                "chords_mm": [round(c * 1000, 1) for c in s.active], "key": s.current and s.current["key"],
                "rounds": s.rounds, "note": s.note} for s in starts]
    (a.out / "summary.json").write_text(json.dumps(summary, indent=1))
    pool.shutdown()
    say(f"span-free search complete in {(time.time() - t0) / 3600:.2f} h")


def accept(store, st, rec, tag):
    store.execute("insert or replace into accepted values(?,?,?,?,?,?,?,?)",
                  (st.search_id, st.id, st.seq, rec["key"], rec["thrust"], st.step_i, None, tag))
    store.execute("update lineages set best_key=?, best_score=? where search_id=? and lineage=?",
                  (rec["key"], rec["thrust"], st.search_id, st.id))
    st.seq += 1


if __name__ == "__main__":
    main()
