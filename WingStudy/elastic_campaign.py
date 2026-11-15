"""Weekend-scale elastic wing campaign: plan, coordinator, results store, replay.

Run through the dashboard (``Run Elastic Campaign.sh``) or directly:
  python WingStudy/elastic_campaign.py dashboard [--campaign DIR] [--workers N] [--smoke]
  python WingStudy/elastic_campaign.py replay DIR KEY      # Ptera animation of one stored design

Design of the study (all choices recorded in plan.json and shown before Start)
------------------------------------------------------------------------------
* Same geometry rules as the rigid coordinate studies, root chord fixed at 200 mm:
  8 chord stations equally spaced along the half-span, chords non-increasing toward the
  tip, positive chords >= 10 mm, zero chords only as a contiguous tip suffix (the tip
  may shorten the active span), 20 mm coordinate steps, one half-step retry, then retire.
  The search moves are coordinate_search.climb() itself, so the rule is identical.
* Objectives per (stiffness, frequency):
    torque_1Nm   maximize mean thrust subject to peak root torque <= 1.0 N m
                 (seeds above the limit first walk down in torque, then climb thrust)
    lambda_x     S = T/Tref - x * M/Mref, x in {0.75, 1.25, 1.75}; Tref, Mref fixed from
                 that (stiffness, frequency)'s own seeds, as in the rigid studies.
* Stiffness: plain-weave carbon (G = 4.5 GPa, E = 50 GPa), focus 0.5/0.4/0.3/0.25 mm
  (all four objectives, 25 lineages = 5 seed spans x 5 families), context rigid/1.0/0.2 mm
  (torque_1Nm and lambda_1.25, 15 lineages).
* Frequencies 0.75 / 1.0 / 1.25 Hz with the same 30 deg custom stroke at 0.5 m/s;
  dt = 1/(50 f) so every frequency has 50 steps per cycle.
* Shape map: the same scrambled-Sobol shapes (valid under the rules above) evaluated at
  every stiffness and frequency, so "same shape, different stiffness" is a fair comparison.
* Only `verified` elastic results (two stabilization settings agree within 3%) or settled
  rigid results may become search parents. `uncertain` results are kept, with ranges.
* Finalists (best design of every search) are re-run at 16 spanwise panels and dt/2.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from concurrent.futures.process import BrokenProcessPool
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
DEFAULT_DIR = ROOT / "outputs" / "elastic" / "campaigns" / "weekend"

PLAIN_WEAVE = {"name": "plain_weave_cf", "shear_modulus_pa": 4.5e9, "density_kg_m3": 1550.0, "youngs_modulus_pa": 50e9}
FAMILIES = ["triangle", "square", "concave", "convex", "narrow"]
TEMPLATE_CASE = 7657
TORQUE_TARGET = 1.0


# ======================================================================================
# Plan
# ======================================================================================
ROD_5x3 = {"diameter_m": 5e-3, "hollow_inner_diameter_m": 3e-3, "shear_modulus_pa": 4.5e9, "density_kg_m3": 1550.0}


def default_plan(smoke=False, variant="plate") -> dict:
    levels = [
        {"id": "rigid", "label": "Rigid", "thickness_mm": None, "tier": "context"},
        {"id": "t1.00", "label": "1.0 mm", "thickness_mm": 1.0, "tier": "context"},
        {"id": "t0.50", "label": "0.5 mm", "thickness_mm": 0.5, "tier": "focus"},
        {"id": "t0.25", "label": "0.25 mm", "thickness_mm": 0.25, "tier": "focus"},
        {"id": "t0.20", "label": "0.2 mm", "thickness_mm": 0.2, "tier": "context"},
    ]
    plan = {
        "name": "Elastic weekend campaign",
        "created": time.strftime("%Y-%m-%d %H:%M"),
        "template_case": TEMPLATE_CASE,
        "material": PLAIN_WEAVE,
        "levels": levels,
        "frequencies_hz": [0.75, 1.0, 1.25],
        "speed_mps": 0.5, "stroke": "custom 30 deg (-26..+34 deg), as rigid studies",
        "steps_per_cycle": 50, "cycles": 4, "span_panels": 8, "chord_panels": 4,
        "torque_target_nm": TORQUE_TARGET,
        "objectives": {"focus": ["torque_1Nm", "lambda_0.75", "lambda_1.25", "lambda_1.75"],
                       "context": ["torque_1Nm", "lambda_1.25"]},
        "seed_half_spans_m": {"focus": [0.15, 0.22, 0.28, 0.34, 0.40], "context": [0.15, 0.28, 0.40]},
        "families": FAMILIES,
        "geometry": {"nodes": 8, "root_chord_m": 0.2, "root_fixed": True, "max_chord_m": 0.2,
                     "min_positive_chord_m": 0.01, "tip_chord_seed_m": 0.01, "decreasing": True,
                     "zero_tip_suffix": True, "step_m": 0.02, "half_step_retry": True},
        "lineage_budget": 60,
        "map": {"focus_shapes": 2048, "context_shapes": 256, "half_spans_m": [0.15, 0.22, 0.28, 0.34, 0.40], "seed": 7},
        "finalists": {"span_panels": 16, "dt_divisor": 2},
        "dt_refinements": [1, 2, 4],
        "estimates_s_per_design": {"elastic": 2.0, "rigid": 0.6},
        "est_evals_per_lineage": 22,
    }
    if variant == "rod":
        # 5 mm OD / 3 mm ID carbon tube along the leading edge, bolted to the plate and held
        # against rotation at the root: its torsion adds to the plate's at every station.
        rod_levels = [levels[0],
                      {"id": "t0.50r", "label": "0.5 mm + rod", "thickness_mm": 0.5, "tier": "focus", "rod": ROD_5x3},
                      {"id": "t0.25r", "label": "0.25 mm + rod", "thickness_mm": 0.25, "tier": "focus", "rod": ROD_5x3}]
        plan.update(name="Elastic campaign: 5 mm rod leading edge", levels=rod_levels, rod=ROD_5x3,
                    objectives={"focus": ["torque_1Nm", "lambda_0.75", "lambda_1.25"], "context": ["torque_1Nm", "lambda_1.25"]})
        if smoke:
            levels = rod_levels
    if variant == "sweep":
        # Coarse geometric fill-in at the design frequency: new scrambled-Sobol outlines with
        # a continuous half-span (not the five seed spans), every model, no searches.
        sweep_levels = [dict(levels[0], tier="focus"),
                        {"id": "t0.50r", "label": "0.5 mm + rod", "thickness_mm": 0.5, "tier": "focus", "rod": ROD_5x3},
                        {"id": "t0.25r", "label": "0.25 mm + rod", "thickness_mm": 0.25, "tier": "focus", "rod": ROD_5x3},
                        {"id": "t0.50", "label": "0.5 mm (no rod)", "thickness_mm": 0.5, "tier": "focus"}]
        plan.update(name="Geometric sweep: continuous span 280-400 mm, 1 Hz", levels=sweep_levels, rod=ROD_5x3,
                    frequencies_hz=[1.0], objectives={"focus": [], "context": []},
                    map={"focus_shapes": 2048, "context_shapes": 2048, "half_span_range_m": [0.28, 0.40], "seed": 11})
        if smoke:
            plan["map"].update(focus_shapes=6, context_shapes=6)
            smoke = False
    if smoke:
        plan.update(name="Smoke test", frequencies_hz=[1.0, 0.75],
                    levels=[levels[0], levels[2]],
                    objectives={"focus": ["torque_1Nm", "lambda_1.25"], "context": ["torque_1Nm"]},
                    seed_half_spans_m={"focus": [0.22], "context": [0.22]},
                    families=["triangle", "convex"], lineage_budget=6,
                    map={"focus_shapes": 8, "context_shapes": 4, "half_spans_m": [0.22, 0.28], "seed": 7})
    plan["chunks"], plan["phases"] = build_phases(plan)
    return plan


def build_phases(plan):
    """One chunk per frequency (design frequency first); each chunk is self-contained:
    focus searches, context searches, shape map, then finalist re-checks for that frequency.
    Returns (chunks, phases) with phases tagged by chunk and ordered for execution."""
    lv = {l["id"]: l for l in plan["levels"]}
    focus = [l["id"] for l in plan["levels"] if l["tier"] == "focus"]
    context = [l["id"] for l in plan["levels"] if l["tier"] == "context"]
    fr = plan["frequencies_hz"]
    order = ([1.0] if 1.0 in fr else []) + [f for f in fr if f != 1.0]

    def searches(levels, f):
        return [{"level": l, "freq": f, "objective": obj,
                 "lineages": len(plan["seed_half_spans_m"][lv[l]["tier"]]) * len(plan["families"])}
                for l in levels for obj in plan["objectives"][lv[l]["tier"]]]

    def names(ids):
        return ", ".join(lv[i]["label"] for i in ids)

    chunks, phases = [], []
    for n, f in enumerate(order, 1):
        cid = str(n)
        ph = [
            {"id": f"{cid}A", "chunk": cid, "title": f"{f:g} Hz searches: {names(focus)} (the sheets you will cut)", "searches": searches(focus, f)},
            {"id": f"{cid}B", "chunk": cid, "title": f"{f:g} Hz context searches: {names(context)}", "searches": searches(context, f)},
            {"id": f"{cid}C", "chunk": cid, "title": f"{f:g} Hz shape map: same Sobol shapes at every stiffness",
             "map": [{"level": l["id"], "freq": f, "shapes": plan["map"]["focus_shapes" if l["tier"] == "focus" else "context_shapes"]}
                     for l in plan["levels"]]},
            {"id": f"{cid}D", "chunk": cid, "title": f"{f:g} Hz finalist re-check (16 spanwise panels, dt/2)", "finalists": True, "freq": f},
        ]
        ph = [p for p in ph if p.get("searches") or p.get("map") or p.get("finalists")]
        chunks.append({"id": cid, "freq": f, "title": f"Chunk {cid} \u00b7 {f:g} Hz" + (" (design frequency)" if f == 1.0 else ""),
                       "phases": [p["id"] for p in ph]})
        phases += ph
    return chunks, phases


def estimate(plan) -> dict:
    """Planned design counts and time per phase (time refined live from measured throughput)."""
    lv = {l["id"]: l for l in plan["levels"]}
    rate = plan["estimates_s_per_design"]
    rows, total_n, total_s = [], 0, 0.0
    for ph in plan["phases"]:
        n = s = 0.0
        for se in ph.get("searches", []):
            k = se["lineages"] * plan["est_evals_per_lineage"]
            n += k; s += k * rate["rigid" if lv[se["level"]]["thickness_mm"] is None else "elastic"]
        for m in ph.get("map", []):
            n += m["shapes"]; s += m["shapes"] * rate["rigid" if lv[m["level"]]["thickness_mm"] is None else "elastic"]
        if ph.get("finalists"):
            k = sum(len(p.get("searches", [])) for p in plan["phases"] if p.get("chunk") == ph.get("chunk")) * 2
            n += k; s += k * rate["elastic"] * 3
        rows.append({"id": ph["id"], "chunk": ph.get("chunk"), "title": ph["title"], "designs": int(n), "hours": s / 3600})
        total_n += n; total_s += s
    chunks = [{"id": c["id"], "title": c["title"], "freq": c["freq"],
               "designs": sum(r["designs"] for r in rows if r["chunk"] == c["id"]),
               "hours": sum(r["hours"] for r in rows if r["chunk"] == c["id"])} for c in plan.get("chunks", [])]
    return {"phases": rows, "chunks": chunks, "designs": int(total_n), "hours": total_s / 3600}


# ======================================================================================
# Geometry helpers (exactly the rigid-study rules via adaptive / coordinate_search)
# ======================================================================================
def rules(plan, objective="torque_1Nm") -> dict:
    g = plan["geometry"]
    n = g["nodes"]
    bounds = []
    for i in range(n):
        if i == 0:
            bounds.append({"min_m": g["root_chord_m"], "max_m": g["root_chord_m"], "step_m": g["step_m"]})
        else:
            bounds.append({"min_m": g["min_positive_chord_m"] if i < 2 else 0.0, "max_m": g["max_chord_m"], "step_m": g["step_m"]})
    lam = float(objective.split("_")[1]) if objective.startswith("lambda_") else 0.0
    return {"node_count": n, "bounds": bounds, "root_chord_m": g["root_chord_m"], "tip_chord_m": g["tip_chord_seed_m"],
            "minimum_chord_m": g["min_positive_chord_m"], "decreasing": g["decreasing"], "tradeoff_lambda": lam,
            "score_tolerance": 1e-6, "objective": objective}


def seed_chords(plan, family):
    import adaptive
    return adaptive.seed(rules(plan), family)


def sobol_shapes(plan, count):
    """Constraint-valid shapes: root 0.2 m, non-increasing, >= 10 mm or zero tip suffix."""
    import adaptive
    from scipy.stats import qmc
    g = plan["geometry"]; n = g["nodes"]; r = rules(plan)
    spans = plan["map"].get("half_spans_m")
    sob = qmc.Sobol(d=n, scramble=True, seed=plan["map"]["seed"])
    m = max(1, math.ceil(math.log2(max(count, 1))))
    u = sob.random_base2(m)[:count]
    out = []
    for i, row in enumerate(u):
        if plan["map"].get("half_span_range_m"):
            lo, hi = plan["map"]["half_span_range_m"]
            span = round(lo + row[0] * (hi - lo), 3)          # continuous, 1 mm resolution
        else:
            span = spans[min(int(row[0] * len(spans)), len(spans) - 1)]
        chords = [g["root_chord_m"]]
        for x in row[1:]:
            # Non-increasing: each station a fraction 0.3..1.0 of the previous one.
            c = chords[-1] * (0.3 + 0.7 * x)
            chords.append(c)
        fixed, zero = [], False
        for j, c in enumerate(chords):
            if zero or (j >= 2 and c < g["min_positive_chord_m"]):
                zero = True; fixed.append(0.0)
            else:
                fixed.append(round(max(c, g["min_positive_chord_m"]), 4))
        if adaptive.valid(fixed, r):
            out.append({"chords": fixed, "half_span": span, "shape_id": f"S{i:04d}"})
    return out


def design_key(level, freq, chords, half_span, numerics="base") -> str:
    blob = json.dumps([level, round(freq, 6), [round(c, 6) for c in chords], round(half_span, 6), numerics])
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


# ======================================================================================
# Worker (separate process)
# ======================================================================================
def _evaluate(task: dict) -> dict:
    """Solve one design. Runs in a worker process; returns a compact JSON-able record."""
    crash = os.environ.get("ELASTIC_TEST_CRASH_FILE")   # test hook: kill this worker once
    if crash and os.path.exists(crash):
        try:
            os.remove(crash)
            os._exit(1)
        except FileNotFoundError:
            pass
    import contextlib
    import io
    import warnings
    warnings.filterwarnings("ignore")
    import elastic
    import elastic_runner as R
    t0 = time.time()
    template, settings = R.load_catalog_case(task["template"])
    chords, hs = task["chords"], task["half_span"]
    active = [c for c in chords if c > 0]
    span = hs * (len(active) - 1) / (len(chords) - 1)
    case = R.sections_case(template, settings, active, span, task["key"])
    case["frequency_hz"] = task["freq"]
    ov = {"dt_s": 1.0 / (task["steps_per_cycle"] * task["freq"]), "cycles": task["cycles"],
          "span_panels": task["span_panels"], "chord_panels": task["chord_panels"]}
    if task.get("dt_divisor"):
        ov["dt_s"] /= task["dt_divisor"]
    cfg = None
    if task["thickness_mm"] is not None:
        cfg = elastic.ElasticConfig.from_dict({"stiffness_model": "plate", "thickness_m": task["thickness_mm"] * 1e-3,
                                               "material": task["material"], "rod": task.get("rod") or {}})
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        if cfg is None:
            r = R.run(case, settings, None, ov)
            status = "ok" if r["status"] == "ok" and r.get("settled") else ("unsettled" if r["status"] == "ok" else r["status"])
        else:
            r = R.run_verified(case, settings, cfg, ov, dt_refinements=tuple(task["dt_refinements"]))
            status = r["status"]
    rec = {"key": task["key"], "status": status, "level": task["level"], "freq": task["freq"], "chords": chords,
           "half_span": hs, "numerics": task.get("numerics", "base"),
           "thrust": r.get("mean_thrust_N"), "torque": r.get("peak_abs_root_torque_Nm"),
           "rms_lift": r.get("rms_lift_N"), "tip_twist": r.get("tip_twist_amplitude_deg"),
           "thrust_range": r.get("thrust_range_N"), "torque_range": r.get("torque_range_Nm"),
           "spread_pct": r.get("verification_spread_pct"), "dt": r.get("dt_s"), "cycles": r.get("cycles"),
           "factor": (r.get("elastic") or {}).get("added_mass_factor"),
           "cycle_error": max(r.get("force_cycle_error_pct") or 0, r.get("torque_cycle_error_pct") or 0) if r.get("force_cycle_error_pct") is not None else None,
           "final_cycle": r.get("final_cycle"), "error": r.get("error"),
           "elapsed": round(time.time() - t0, 2)}
    return rec


# ======================================================================================
# Store
# ======================================================================================
SCHEMA = """
create table if not exists meta(k text primary key, v text);
create table if not exists designs(key text primary key, status text, level text, freq real, chords text, half_span real,
  numerics text, thrust real, torque real, rms_lift real, tip_twist real, thrust_lo real, thrust_hi real, torque_lo real,
  torque_hi real, spread_pct real, dt real, cycles int, factor real, cycle_error real, error text, elapsed real, done_at real);
create table if not exists cycles(key text primary key, data text);
create table if not exists uses(key text, source text, search_id text, lineage text, role text, phase text,
  primary key(key, source, search_id, lineage, role));
create table if not exists searches(search_id text primary key, phase text, level text, freq real, objective text,
  status text, tref real, mref real, lineages int, best_key text, best_score real);
create table if not exists lineages(search_id text, lineage text, half_span real, family text, status text,
  evals int, best_key text, best_score real, primary key(search_id, lineage));
create table if not exists accepted(search_id text, lineage text, seq int, key text, score real, pass int, node int, kind text,
  primary key(search_id, lineage, seq));
create table if not exists rechecks(key text primary key, base_key text, search_id text);
create index if not exists designs_lf on designs(level, freq);
"""


class Store:
    def __init__(self, path: Path):
        self.path = path
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.db.execute("pragma journal_mode=wal")
        self.db.executescript(SCHEMA)
        self.lock = threading.Lock()

    def get_meta(self, k, default=None):
        row = self.db.execute("select v from meta where k=?", (k,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_meta(self, k, v):
        with self.lock:
            self.db.execute("insert or replace into meta values(?,?)", (k, json.dumps(v)))
            self.db.commit()

    def result(self, key):
        row = self.db.execute("select key,status,thrust,torque from designs where key=?", (key,)).fetchone()
        return None if row is None else {"key": row[0], "status": row[1], "thrust": row[2], "torque": row[3]}

    def save(self, rec):
        tr, mr = rec.get("thrust_range") or [None, None], rec.get("torque_range") or [None, None]
        with self.lock:
            self.db.execute("insert or replace into designs values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (
                rec["key"], rec["status"], rec["level"], rec["freq"], json.dumps(rec["chords"]), rec["half_span"],
                rec.get("numerics", "base"), rec.get("thrust"), rec.get("torque"), rec.get("rms_lift"), rec.get("tip_twist"),
                tr[0], tr[1], mr[0], mr[1], rec.get("spread_pct"), rec.get("dt"), rec.get("cycles"), rec.get("factor"),
                rec.get("cycle_error"), rec.get("error"), rec.get("elapsed"), time.time()))
            if rec.get("final_cycle"):
                self.db.execute("insert or replace into cycles values(?,?)", (rec["key"], json.dumps(rec["final_cycle"])))
            self.db.commit()

    def execute(self, sql, args=()):
        with self.lock:
            self.db.execute(sql, args)
            self.db.commit()


def parent_row(rec):
    """coordinate_search row: only verified elastic / settled rigid results can be parents."""
    ok = rec is not None and rec["status"] in ("verified", "ok") and rec["thrust"] is not None
    return {"id": rec["key"] if rec else None, "status": "ok" if ok else "failed",
            "simulation_mode": "isolated_single_wing_v1", "cycle_repeatable": ok,
            "single_wing_mean_thrust_N": rec["thrust"] if ok else None,
            "single_wing_peak_abs_roll_moment_Nm": rec["torque"] if ok else None}


# ======================================================================================
# Coordinator
# ======================================================================================
class Campaign:
    def __init__(self, directory: Path, workers: int, smoke=False, variant="plate"):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.store = Store(self.dir / "campaign.sqlite")
        plan = self.store.get_meta("plan")
        if plan is None:
            plan = default_plan(smoke, variant)
            self.store.set_meta("plan", plan)
            (self.dir / "plan.json").write_text(json.dumps(plan, indent=1))
        self.plan = plan
        self.levels = {l["id"]: l for l in plan["levels"]}
        self.workers = workers
        self.state = "ready"            # ready | running | paused | stopping | stopped | done
        self.control = threading.Event()
        self.started = None
        self.inflight = {}              # key -> future
        self.waiters = {}               # key -> list of callbacks
        self.log = []
        self.phase_index = 0
        self.completed_times = []       # (time, elapsed) of fresh solves, for throughput
        self.fresh = 0
        self.cached = 0
        self.lineage_evals_done = []
        self.current_units = []
        self.active_chunk = None
        self.next_chunk = None
        self.auto_continue = False
        self.chunk_started = None

    # ---------------- task plumbing ----------------
    def task(self, level, freq, chords, half_span, numerics="base", span_panels=None, dt_divisor=None):
        p = self.plan
        key = design_key(level, freq, chords, half_span, numerics)
        lv = self.levels[level]
        return {"key": key, "level": level, "freq": freq, "chords": chords, "half_span": half_span,
                "thickness_mm": lv["thickness_mm"], "rod": lv.get("rod"), "material": p["material"], "template": p["template_case"],
                "steps_per_cycle": p["steps_per_cycle"], "cycles": p["cycles"],
                "span_panels": span_panels or p["span_panels"], "chord_panels": p["chord_panels"],
                "dt_refinements": p["dt_refinements"], "numerics": numerics, "dt_divisor": dt_divisor}

    def request(self, task, callback):
        """callback(record) when available: from the store, an in-flight solve, or a new solve."""
        done = self.store.result(task["key"])
        if done is not None:
            self.cached += 1
            callback(done); return
        self.waiters.setdefault(task["key"], []).append(callback)
        if task["key"] not in self.inflight and task["key"] not in self.queue_keys:
            self.queue.append(task); self.queue_keys.add(task["key"])

    def note(self, msg):
        self.log.append({"t": time.time(), "msg": msg})
        self.log = self.log[-200:]

    # ---------------- searches ----------------
    def start_search(self, phase_id, spec):
        p = self.plan
        lv = self.levels[spec["level"]]
        tier = lv["tier"]
        sid = f"{spec['level']}@{spec['freq']:g}Hz/{spec['objective']}"
        unit = {"kind": "search", "id": sid, "phase": phase_id, "spec": spec, "seeds": {}, "lineages": [],
                "done": False, "state": "seeding"}
        self.store.execute("insert or ignore into searches(search_id,phase,level,freq,objective,status,lineages) values(?,?,?,?,?,?,?)",
                           (sid, phase_id, spec["level"], spec["freq"], spec["objective"], "seeding", spec["lineages"]))
        jobs = [(hs, fam) for hs in p["seed_half_spans_m"][tier] for fam in p["families"]]
        unit["jobs"] = jobs
        for j, (hs, fam) in enumerate(jobs):
            chords = seed_chords(p, fam)
            t = self.task(spec["level"], spec["freq"], chords, hs)
            self.store.execute("insert or ignore into uses values(?,?,?,?,?,?)", (t["key"], "search", sid, f"L{j:02d}", "seed", phase_id))

            def cb(rec, j=j, chords=chords, unit=unit):
                unit["seeds"][j] = (chords, rec)
                if len(unit["seeds"]) == len(unit["jobs"]):
                    self.begin_climb(unit)
            self.request(t, cb)
        return unit

    def begin_climb(self, unit):
        import coordinate_search as cs
        spec = unit["spec"]
        rows = {j: (chords, parent_row(rec)) for j, (chords, rec) in unit["seeds"].items()}
        valid = [cs.loads(r) for _, r in rows.values() if cs.loads(r) is not None]
        if not valid:
            unit["done"] = True; unit["state"] = "no valid seeds"
            self.store.execute("update searches set status=? where search_id=?", ("no valid seeds", unit["id"]))
            return
        scales = {"thrust_scale_N": max(max(abs(t) for t, m in valid), 1e-9), "torque_scale_Nm": max(max(m for t, m in valid), 1e-9)}
        unit["scales"] = scales
        self.store.execute("update searches set status=?, tref=?, mref=? where search_id=?",
                           ("climbing", scales["thrust_scale_N"], scales["torque_scale_Nm"], unit["id"]))
        r = rules(self.plan, spec["objective"])
        score_fn = None
        if spec["objective"] == "torque_1Nm":
            tref, mref = scales["thrust_scale_N"], scales["torque_scale_Nm"]

            def score_fn(row):
                v = cs.loads(row)
                if v is None:
                    return None
                t, m = v
                return t / tref if m <= TORQUE_TARGET else -10.0 - (m - TORQUE_TARGET) / mref
        unit["score_fn"] = score_fn or (lambda row, r=r, s=scales: cs.score(row, s, r["tradeoff_lambda"]))
        unit["state"] = "climbing"
        # Create every lineage before advancing any: with cached results a lineage can
        # replay to completion instantly, and the search must not be judged finished
        # (and its winner chosen) before all its lineages exist.
        for j, (hs, fam) in enumerate(unit["jobs"]):
            chords, row = rows[j]
            lid = f"L{j:02d}"
            lin = {"id": lid, "half_span": hs, "family": fam, "evals": 0, "seq": 0, "best": None, "status": "running"}
            self.store.execute("insert or replace into lineages values(?,?,?,?,?,?,?,?)", (unit["id"], lid, hs, fam, "running", 0, None, None))
            if cs.loads(row) is None:
                lin["status"] = "invalid seed"
                self.store.execute("update lineages set status=? where search_id=? and lineage=?", ("invalid seed", unit["id"], lid))
            else:
                lin["gen"] = cs.climb(r, hs, j + 1, fam, (chords, row), scales, score_fn=score_fn)
            unit["lineages"].append(lin)
        unit["ready"] = True
        for lin in list(unit["lineages"]):
            if "gen" in lin:
                self.advance(unit, lin, None)
        self.check_search_done(unit)

    def advance(self, unit, lin, results):
        """Drive one lineage generator until it needs solves (or ends)."""
        try:
            msg = lin["gen"].send(results) if results is not None else next(lin["gen"])
            while True:
                if msg[0] == "accepted":
                    ev = msg[1]
                    key = ev["case"]["id"]
                    sc = unit["score_fn"](ev["case"])
                    lin["best"] = (key, sc)
                    self.store.execute("insert or replace into accepted values(?,?,?,?,?,?,?,?)",
                                       (unit["id"], lin["id"], lin["seq"], key, sc, ev.get("pass"), ev.get("node"), ev.get("kind")))
                    self.store.execute("update lineages set best_key=?, best_score=? where search_id=? and lineage=?",
                                       (key, sc, unit["id"], lin["id"]))
                    lin["seq"] += 1
                    msg = next(lin["gen"])
                    continue
                pending = msg[1]
                if lin["evals"] + len(pending) > self.plan["lineage_budget"]:
                    lin["status"] = "budget reached"; break
                lin["evals"] += len(pending)
                lin["pending"] = pending
                lin["results"] = [None] * len(pending)
                lin["outstanding"] = len(pending)
                spec = unit["spec"]
                for i, (chords, meta) in enumerate(pending):
                    t = self.task(spec["level"], spec["freq"], chords, lin["half_span"])
                    self.store.execute("insert or ignore into uses values(?,?,?,?,?,?)",
                                       (t["key"], "search", unit["id"], lin["id"], meta.get("kind", "trial"), unit["phase"]))

                    def cb(rec, i=i, lin=lin, unit=unit):
                        lin["results"][i] = parent_row(rec)
                        lin["outstanding"] -= 1
                        if lin["outstanding"] == 0:
                            self.advance(unit, lin, lin["results"])
                    self.request(t, cb)
                return
        except StopIteration as stop:
            lin["status"] = (stop.value or {}).get("status", "complete")
        self.lineage_evals_done.append(lin["evals"])
        self.store.execute("update lineages set status=?, evals=? where search_id=? and lineage=?",
                           (lin["status"], lin["evals"], unit["id"], lin["id"]))
        self.check_search_done(unit)

    def check_search_done(self, unit):
        if unit["done"] or unit["state"] != "climbing" or not unit.get("ready"):
            return
        if all(l["status"] != "running" for l in unit["lineages"]):
            best = max((l["best"] for l in unit["lineages"] if l["best"] and l["best"][1] is not None),
                       key=lambda b: b[1], default=None)
            unit["done"] = True; unit["state"] = "complete"
            self.store.execute("update searches set status=?, best_key=?, best_score=? where search_id=?",
                               ("complete", best[0] if best else None, best[1] if best else None, unit["id"]))
            self.note(f"Search complete: {unit['id']}")

    # ---------------- map & finalists ----------------
    def start_map(self, phase_id, spec):
        shapes = sobol_shapes(self.plan, spec["shapes"])
        unit = {"kind": "map", "id": f"map {spec['level']}@{spec['freq']:g}Hz", "phase": phase_id, "remaining": len(shapes), "done": False}
        for s in shapes:
            t = self.task(spec["level"], spec["freq"], s["chords"], s["half_span"])
            self.store.execute("insert or ignore into uses values(?,?,?,?,?,?)", (t["key"], "map", unit["id"], s["shape_id"], "map", phase_id))

            def cb(rec, unit=unit):
                unit["remaining"] -= 1
                unit["done"] = unit["remaining"] <= 0
            self.request(t, cb)
        if not shapes:
            unit["done"] = True
        return unit

    def start_finalists(self, phase_id, freq=None):
        rows = self.store.db.execute("select search_id, level, freq, best_key from searches where best_key is not null").fetchall()
        if freq is not None:
            rows = [r for r in rows if abs(r[2] - freq) < 1e-9]
        unit = {"kind": "finalists", "id": "finalists", "phase": phase_id, "remaining": 0, "done": False}
        tasks = []
        for sid, level, freq, key in rows:
            d = self.store.db.execute("select chords, half_span, dt from designs where key=?", (key,)).fetchone()
            if not d:
                continue
            chords, hs = json.loads(d[0]), d[1]
            # Halve the step the base design actually verified at (soft plates often needed dt/2
            # already; dividing the nominal step would just repeat that solve).
            nominal = 1.0 / (self.plan["steps_per_cycle"] * freq)
            used = d[2] or nominal
            divisor = round(self.plan["finalists"]["dt_divisor"] * nominal / used, 6)
            for numerics, kw in (("span16", {"span_panels": self.plan["finalists"]["span_panels"]}),
                                 ("dt_half_used", {"dt_divisor": divisor})):
                t = self.task(level, freq, chords, hs, numerics, **kw)
                self.store.execute("insert or ignore into rechecks values(?,?,?)", (t["key"], key, sid))
                self.store.execute("insert or ignore into uses values(?,?,?,?,?,?)", (t["key"], "recheck", sid, numerics, numerics, phase_id))
                tasks.append(t)
        unit["remaining"] = len(tasks)          # count first: cached callbacks fire immediately

        def cb(rec, unit=unit):
            unit["remaining"] -= 1
            unit["done"] = unit["remaining"] <= 0
        for t in tasks:
            self.request(t, cb)
        if unit["remaining"] == 0:
            unit["done"] = True
        return unit

    def start_phase(self, ph):
        self.note(f"Phase {ph['id']} started: {ph['title']}")
        self.store.set_meta("phase", ph["id"])
        units = []
        for spec in ph.get("searches", []):
            units.append(self.start_search(ph["id"], spec))
        for spec in ph.get("map", []):
            units.append(self.start_map(ph["id"], spec))
        if ph.get("finalists"):
            units.append(self.start_finalists(ph["id"], ph.get("freq")))
        return units

    # ---------------- main loop ----------------
    def chunks_done(self):
        return self.store.get_meta("chunks_done", {})

    def run(self):
        """Run chunk by chunk. After each chunk the campaign waits for Start (unless
        auto-continue is on), so results can be checked between chunks."""
        os.environ.update({k: "1" for k in ("NUMBA_NUM_THREADS", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")})
        import multiprocessing as mp
        self.queue, self.queue_keys = [], set()
        self.tasks_by_key = {}

        def new_pool():
            return ProcessPoolExecutor(max_workers=self.workers, mp_context=mp.get_context("spawn"))
        pool, crashes = None, {}
        pending = [c for c in self.plan["chunks"] if c["id"] not in self.chunks_done()]
        if not pending:
            self.state = "done"; self.note("All chunks are complete"); return
        self.next_chunk = pending[0]["id"]
        self.state = "ready"
        try:
            for ch in pending:
                self.next_chunk = ch["id"]
                if not (self.auto_continue and self.active_chunk is not None):
                    self.state = "ready" if self.active_chunk is None else "waiting"
                    self.control.wait()      # set by Start (or --autostart before we got here)
                    self.control.clear()     # consume it, so the next chunk waits for a new Start
                if self.state == "stopping":
                    break
                if pool is None:
                    pool = new_pool()
                self.state = "running"
                self.chunk_started = time.time()
                self.active_chunk = ch["id"]
                self.started = self.started or time.time()
                t0, fresh0 = time.time(), self.fresh
                self.phase_index, self.current_units = 0, []
                self.note(f"{ch['title']} started with {self.workers} workers")
                phases = [p for p in self.plan["phases"] if p.get("chunk") == ch["id"]]
                finished, pool = self.run_phases(phases, pool, new_pool, crashes)
                if not finished:
                    break
                done = self.chunks_done()
                done[ch["id"]] = {"finished": time.time(), "hours": (time.time() - t0) / 3600,
                                  "fresh": self.fresh - fresh0, "report": None}
                try:
                    import elastic_figures
                    done[ch["id"]]["report"] = elastic_figures.chunk_report(self.store.path, self.plan, ch, self.dir / "reports")
                except Exception as exc:  # noqa: BLE001 - a plotting problem must not stop the campaign
                    self.note(f"Report for chunk {ch['id']} failed: {exc}")
                self.store.set_meta("chunks_done", done)
                self.note(f"{ch['title']} complete in {done[ch['id']]['hours']:.1f} h; report written")
            remaining = [c for c in self.plan["chunks"] if c["id"] not in self.chunks_done()]
            self.state = "done" if not remaining else "stopped"
        finally:
            if pool is not None:
                pool.shutdown(wait=False, cancel_futures=True)
            if self.state not in ("done",):
                self.state = "stopped"
            self.store.set_meta("state", self.state)
            self.note(f"Campaign {self.state}")

    def run_phases(self, phases, pool, new_pool, crashes):
        """Existing scheduler, limited to one chunk. Returns (finished, pool)."""
        while True:
            # Activate the next phase when the current one is drained or nearly so.
            if self.state == "running" and self.phase_index < len(phases):
                ph = phases[self.phase_index]
                all_done = all(u["done"] for u in self.current_units)
                idle_tail = not self.queue and len(self.inflight) < self.workers
                if ph.get("finalists") and not all_done and not self.queue and not self.inflight:
                    stuck = [u["id"] for u in self.current_units if not u["done"]]
                    self.note(f"{len(stuck)} unit(s) could not finish: {stuck[:5]}")
                    for u in self.current_units:
                        u["done"] = True
                    all_done = True
                # Finalists need every search finished; other phases may start early
                # to keep the workers busy while the previous phase's tail drains.
                if all_done or (idle_tail and not ph.get("finalists")):
                    self.current_units += self.start_phase(ph)
                    self.phase_index += 1
                    continue
            # Submit queued solves.
            while self.state == "running" and self.queue and len(self.inflight) < self.workers * 2:
                t = self.queue.pop(0); self.queue_keys.discard(t["key"])
                if self.store.result(t["key"]) is not None:
                    self.finish(self.store.result(t["key"]), fresh=False); continue
                self.tasks_by_key[t["key"]] = t
                try:
                    self.inflight[t["key"]] = pool.submit(_evaluate, t)
                except BrokenProcessPool:
                    self.queue.insert(0, t); self.queue_keys.add(t["key"])
                    pool = self.recover(pool, new_pool, crashes); break
            if not self.inflight:
                if self.state == "stopping":
                    return False, pool
                if self.state == "running" and self.phase_index >= len(phases) and not self.queue:
                    stuck = [u["id"] for u in self.current_units if not u["done"]]
                    if stuck:  # nothing left to solve, so these can never finish
                        self.note(f"Ended with {len(stuck)} unit(s) incomplete: {stuck[:5]}")
                        for u in self.current_units:
                            u["done"] = True
                    return True, pool
                if self.state == "paused":
                    time.sleep(0.5); continue
                if self.state == "running" and not self.queue:
                    time.sleep(0.2); continue
                continue
            done, _ = wait(list(self.inflight.values()), timeout=1.0, return_when=FIRST_COMPLETED)
            for fut in done:
                key = next(k for k, f in self.inflight.items() if f is fut)
                del self.inflight[key]
                try:
                    rec = fut.result()
                except BrokenProcessPool:
                    # A worker died (native crash or killed). Every in-flight future in
                    # this pool is lost: re-queue them on a fresh pool; a design that
                    # kills a worker twice is recorded as failed so the run moves on.
                    self.inflight[key] = fut
                    pool = self.recover(pool, new_pool, crashes)
                    break
                except Exception as exc:  # noqa: BLE001
                    t = self.tasks_by_key.get(key, {})
                    rec = {"key": key, "status": "failed", "level": t.get("level", "?"), "freq": t.get("freq", 0),
                           "chords": t.get("chords", []), "half_span": t.get("half_span", 0),
                           "numerics": t.get("numerics", "base"), "error": f"worker error: {exc}"}
                self.store.save(rec)
                self.completed_times.append((time.time(), rec.get("elapsed", 0)))
                self.completed_times = self.completed_times[-2000:]
                self.fresh += 1
                self.finish(self.store.result(key), fresh=True)

    def recover(self, pool, new_pool, crashes):
        lost = list(self.inflight)
        self.inflight.clear()
        pool.shutdown(wait=False, cancel_futures=True)
        for key in lost:
            t = self.tasks_by_key.get(key)
            if t is None:
                continue
            crashes[key] = crashes.get(key, 0) + 1
            if crashes[key] >= 2:
                rec = {"key": key, "status": "failed", "level": t["level"], "freq": t["freq"], "chords": t["chords"],
                       "half_span": t["half_span"], "numerics": t.get("numerics", "base"),
                       "error": "worker process died twice while solving this design"}
                self.store.save(rec)
                self.finish(self.store.result(key), fresh=True)
            else:
                self.queue.insert(0, t); self.queue_keys.add(key)
        self.note(f"A worker process died; restarted the pool and re-queued {len(lost)} design(s)")
        return new_pool()

    def finish(self, rec, fresh):
        for cb in self.waiters.pop(rec["key"], []):
            cb(rec)

    # ---------------- status for the dashboard ----------------
    def status(self) -> dict:
        db = sqlite3.connect(f"file:{self.store.path}?mode=ro", uri=True, timeout=30)
        now = time.time()
        recent = [t for t in self.completed_times if t[0] > now - 900]
        rate = len(recent) / max(now - recent[0][0], 1) if len(recent) >= 5 else None
        est = estimate(self.plan)
        done_by_phase = {r[0]: r[1] for r in db.execute(
            "select phase, count(distinct key) from uses where key in (select key from designs) group by phase")}
        evals = self.lineage_evals_done
        per_lin = (sum(evals) / len(evals)) if len(evals) >= 10 else self.plan["est_evals_per_lineage"]
        row = db.execute("select v from meta where k='chunks_done'").fetchone()
        chunks_done = json.loads(row[0]) if row else {}   # own connection: never touch the writer's
        phase_rows = {}
        for row, ph in zip(est["phases"], self.plan["phases"]):
            planned = row["designs"]
            if ph.get("searches"):
                planned = int(sum(x["lineages"] for x in ph["searches"]) * per_lin)
            done = done_by_phase.get(ph["id"], 0)
            units = [u for u in self.current_units if u["phase"] == ph["id"]]
            if (units and all(u["done"] for u in units)) or ph.get("chunk") in chunks_done:
                planned = done          # finished: report what actually ran
            phase_rows[ph["id"]] = {"id": ph["id"], "title": ph["title"], "planned": max(planned, done), "done": done,
                                    "chunk": ph.get("chunk")}
        focus_chunk = self.active_chunk if self.state in ("running", "paused", "stopping") else self.next_chunk
        chunks = []
        for c, ce in zip(self.plan["chunks"], est["chunks"]):
            rows = [phase_rows[i] for i in c["phases"]]
            planned, done = sum(r["planned"] for r in rows), sum(r["done"] for r in rows)
            if c["id"] in chunks_done:
                st = "done"
            elif c["id"] == self.active_chunk and self.state in ("running", "paused", "stopping"):
                st = self.state
            elif c["id"] == self.next_chunk and self.state in ("ready", "waiting"):
                st = "next"
            else:
                st = "pending"
            remaining = max(planned - done, 0)
            hours = (remaining / rate / 3600) if rate else ce["hours"] * remaining / max(ce["designs"], 1)
            info = chunks_done.get(c["id"], {})
            elapsed = ((now - self.chunk_started) / 3600 if st in ("running", "paused", "stopping") and self.chunk_started
                       else info_hours(chunks_done, c["id"]))
            chunks.append({"id": c["id"], "title": c["title"], "freq": c["freq"], "status": st, "planned": planned,
                           "done": done, "est_hours": ce["hours"], "elapsed_hours": elapsed,
                           "remaining_hours": 0 if st == "done" else hours,
                           "finished": info.get("finished"), "took_hours": info.get("hours"), "report": info.get("report")})
        cur = next((c for c in chunks if c["id"] == focus_chunk), None)
        counts = dict(db.execute("select status, count(*) from designs group by status").fetchall())
        lin = dict(db.execute("select status, count(*) from lineages group by status").fetchall())
        recent_rows = db.execute("select key, level, freq, status, thrust, torque, tip_twist, elapsed from designs "
                                 "order by done_at desc limit 12").fetchall()
        out_status = {"state": self.state, "workers": self.workers, "started": self.started, "now": now,
                      "fresh": self.fresh, "cached": self.cached, "inflight": len(self.inflight),
                      "queued": len(getattr(self, "queue", [])), "auto_continue": self.auto_continue,
                      "rate_per_min": rate * 60 if rate else None,
                      "chunk": cur, "chunks": chunks,
                      "eta_hours": cur["remaining_hours"] if cur else 0,
                      "remaining_designs": max(cur["planned"] - cur["done"], 0) if cur else 0,
                      "all_remaining_hours": sum(c["remaining_hours"] for c in chunks),
                      "all_est_hours": sum(c["est_hours"] for c in chunks),
                      "all_elapsed_hours": sum(c["elapsed_hours"] or 0 for c in chunks),
                      "all_planned": sum(c["planned"] for c in chunks), "all_done": sum(c["done"] for c in chunks),
                      "phases": [phase_rows[i] for i in (next(c["phases"] for c in self.plan["chunks"] if c["id"] == focus_chunk) if focus_chunk else [])],
                      "status_counts": counts, "lineage_counts": lin,
                      "recent": [dict(zip(("key", "level", "freq", "status", "thrust", "torque", "tip_twist", "elapsed"), r)) for r in recent_rows],
                      "log": self.log[-15:], "phase_index": self.phase_index}
        db.close()
        return out_status


def info_hours(chunks_done, cid):
    return (chunks_done.get(cid) or {}).get("hours")


def progress_line(st) -> str:
    """One-line terminal summary: bar, designs, elapsed, original estimate, remaining."""
    def h(x):
        if x is None:
            return "-"
        m = int(round(x * 60))
        return f"{m // 60}h{m % 60:02d}m"
    c = st.get("chunk")
    if not c:
        return f"[{st['state']}] all chunks done" if st["state"] == "done" else f"[{st['state']}]"
    frac = c["done"] / max(c["planned"], 1)
    bar = "#" * int(frac * 24) + "." * (24 - int(frac * 24))
    rate = f"{st['rate_per_min']:.0f}/min" if st.get("rate_per_min") else "rate pending"
    return (f"[{st['state']}] {c['title']}  [{bar}] {100 * frac:4.1f}%  {c['done']:,}/~{c['planned']:,} designs  "
            f"elapsed {h(c['elapsed_hours'])} | original est. {h(c['est_hours'])} | ~{h(c['remaining_hours'])} left ({rate})"
            f"  || all chunks: elapsed {h(st['all_elapsed_hours'])} of est. {h(st['all_est_hours'])}, ~{h(st['all_remaining_hours'])} left")


# ======================================================================================
# Replay (animation for a selected design)
# ======================================================================================
def replay(directory: Path, key: str, out: Path | None = None) -> Path:
    import elastic
    import elastic_runner as R
    store = Store(Path(directory) / "campaign.sqlite")
    plan = store.get_meta("plan")
    row = store.db.execute("select level,freq,chords,half_span,dt,cycles,factor,status from designs where key=?", (key,)).fetchone()
    if row is None:
        raise KeyError(f"No stored design {key}")
    level, freq, chords, hs, dt, cycles, factor, status = row
    chords = json.loads(chords)
    lv = {l["id"]: l for l in plan["levels"]}[level]
    template, settings = R.load_catalog_case(plan["template_case"])
    active = [c for c in chords if c > 0]
    case = R.sections_case(template, settings, active, hs * (len(active) - 1) / (len(chords) - 1), key)
    case["frequency_hz"] = freq
    cfg = None
    if lv["thickness_mm"] is not None:
        cfg = elastic.ElasticConfig.from_dict({"stiffness_model": "plate", "thickness_m": lv["thickness_mm"] * 1e-3,
                                               "material": plan["material"], "rod": lv.get("rod") or {},
                                               "added_mass_factor": factor or 0.5})
    out = Path(out or Path(directory) / "animations" / key)
    r = R.run(case, settings, cfg, {"dt_s": dt or 1 / (plan["steps_per_cycle"] * freq), "cycles": cycles or plan["cycles"],
                                     "span_panels": plan["span_panels"], "chord_panels": plan["chord_panels"]}, output_dir=out)
    r.pop("history", None)
    (out / "metrics.json").write_text(json.dumps({"key": key, "level": level, "freq": freq, "chords": chords,
                                                  "half_span": hs, "stored_status": status, **r}, indent=1, default=str))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("dashboard")
    d.add_argument("--campaign", type=Path, default=DEFAULT_DIR)
    d.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    d.add_argument("--port", type=int, default=8777)
    d.add_argument("--smoke", action="store_true", help="tiny plan for testing the pipeline")
    d.add_argument("--autostart", action="store_true")
    d.add_argument("--no-browser", action="store_true")
    d.add_argument("--variant", choices=["plate", "rod", "sweep"], default="plate",
                   help="plan for a NEW campaign folder: bare plate, or plate + 5 mm rod leading edge")
    rp = sub.add_parser("replay"); rp.add_argument("campaign", type=Path); rp.add_argument("key"); rp.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    if a.cmd == "replay":
        print(replay(a.campaign, a.key, a.out))
        return
    import elastic_dashboard
    camp = Campaign(a.campaign, a.workers, a.smoke, a.variant)
    elastic_dashboard.serve(camp, a.port, open_browser=not a.no_browser, autostart=a.autostart)


if __name__ == "__main__":
    main()
