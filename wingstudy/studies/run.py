"""Plan and run a study: expand its spec into cases and solve them with the existing engines.

Study kinds map onto the engines the campaigns already use, unchanged:

    design-set, geometry-sweep  ->  elastic_campaign._evaluate   (one design, verification ladder)
    matched-comparison          ->  span_atlas.evaluate          (chordwise vs spanwise pair)

Every solved case is cached under outputs/study-cache/<key>.json. The key covers the
wing, model, motion template, numerics and the code identity, so reruns and later
studies reuse identical solves and anything that changes the physics or code re-solves.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys
import time
from pathlib import Path

from . import spec as S

CACHE = S.ROOT / "outputs" / "study-cache"
TEMPLATE_CASE = 7657                       # motion and fluid template: 0.5 m/s, 30 deg stroke, water
DT_REFINEMENTS = [1, 2, 4]
SPANWISE_OPTIONS = {"spanwise_bending": True, "large_deflection": True, "max_bend_deg": 75.0,
                    "max_tip_deflection_fraction": 0.95}
# Rough wall-clock seconds per case at 8x4 panels, 50 steps/cycle, 4 cycles, one case per worker,
# including the verification ladder (dt, dt/2, dt/4). Calibrated on the first planned study:
# t0.50r at 8x4/50 took 35 s, 16x4/100 took 81 s with four workers busy; spanwise t0.50r at 8x4/50
# took 31-34 s with two workers. Matched solves both models (two ladders).
SECONDS = {"rigid": 5.0, "chordwise": 35.0, "spanwise": 40.0, "matched": 80.0}
BIG_KEYS = ("history", "span_history", "strips", "elastic")


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ----------------------------------------------------------------------------- jobs
def job_for(case: dict, code_digest: str) -> dict:
    """The exact solver input for one case (also its replay manifest) and its cache key."""
    from ..elastic_campaign import PLAIN_WEAVE, ROD_5x3, design_key
    model = S.MODELS[case["model"]]
    n = case["numerics"]
    rod = ROD_5x3 if model["rod"] else None
    if case["structure"] == "matched":
        w = {"chords": list(case["chords_mm"]), "half_span": case["half_span_mm"], "freq": case["freq"],
             "template_case": TEMPLATE_CASE, "thickness_mm": model["thickness_mm"], "rod": rod or {},
             "material": PLAIN_WEAVE,
             "numerics": {"dt_s": 1.0 / (n["steps_per_cycle"] * case["freq"]), "cycles": n["cycles"],
                          "span_panels": n["span_panels"], "chord_panels": n["chord_panels"]}}
        key = design_key(case["model"], case["freq"], [c / 1000 for c in case["chords_mm"]], case["half_span_mm"] / 1000,
                         "study-matched", context={"w": w, "code": code_digest})
        return {"engine": "matched", "key": key, "input": dict(w, key=key)}
    task = {"level": case["model"], "freq": case["freq"],
            "chords": [round(c / 1000, 6) for c in case["chords_mm"]], "half_span": round(case["half_span_mm"] / 1000, 6),
            "elastic_options": dict(SPANWISE_OPTIONS) if case["structure"] == "spanwise" else {},
            "thickness_mm": model["thickness_mm"], "rod": rod, "material": PLAIN_WEAVE, "template": TEMPLATE_CASE,
            "steps_per_cycle": n["steps_per_cycle"], "cycles": n["cycles"], "span_panels": n["span_panels"],
            "chord_panels": n["chord_panels"], "dt_refinements": DT_REFINEMENTS, "numerics": "study", "dt_divisor": None}
    key = design_key(task["level"], task["freq"], task["chords"], task["half_span"], "study",
                     context={"structure": case["structure"], "task": task, "code": code_digest})
    return {"engine": "design", "key": key, "input": dict(task, key=key)}


def solve(job: dict) -> dict:
    """Run one job in a worker process. Returns a compact, JSON-able result."""
    import warnings
    warnings.filterwarnings("ignore")
    t0 = time.time()
    if job["engine"] == "design":
        from ..elastic_campaign import _evaluate
        r = _evaluate(job["input"])
        out = {"status": r["status"], "thrust_N": r.get("thrust"), "torque_Nm": r.get("torque"),
               "tip_twist_deg": r.get("tip_twist"), "rms_lift_N": r.get("rms_lift"),
               "verification_spread_pct": r.get("spread_pct"), "cycle_error_pct": r.get("cycle_error"),
               "dt_s": r.get("dt"), "cycles": r.get("cycles"), "added_mass_factor": r.get("factor"),
               "error": r.get("error")}
    else:
        import contextlib
        import io
        from .. import span_atlas
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            try:
                r = span_atlas.evaluate(job["input"])
            except Exception as exc:          # a failure is recorded, never a zero
                r = {"baseline": {"status": "failed", "error": str(exc)}, "spanwise": {"status": "failed", "error": str(exc)}}
        out = {k: {x: v for x, v in r[k].items() if x not in BIG_KEYS} for k in ("baseline", "spanwise")}
        out["status"] = "complete" if all(out[k].get("status") in ("verified", "ok") for k in ("baseline", "spanwise")) else (
            "failed" if all(out[k].get("status") == "failed" for k in ("baseline", "spanwise")) else "partial")
    out["elapsed_s"] = round(time.time() - t0, 2)
    return _clean(out)


def _clean(x):
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_clean(v) for v in x]
    return x


# ----------------------------------------------------------------------------- plan
def estimate_seconds(case: dict) -> float:
    n = case["numerics"]
    kind = "rigid" if case["model"] == "rigid" else case["structure"]
    scale = (n["steps_per_cycle"] / 50) ** 0.6 * (n["span_panels"] * n["chord_panels"] / 32) ** 0.6 * (n["cycles"] / 4)
    return SECONDS[kind] * scale


def prepare(study_id: str):
    spec = S.load(study_id)
    errors = S.validate(spec)
    if errors:
        raise ValueError("invalid spec:\n  " + "\n  ".join(errors))
    if spec["id"] != study_id and Path(study_id).name != spec["id"]:
        raise ValueError(f"spec id {spec['id']!r} does not match its folder {study_id!r}")
    from ..identity import code_identity
    code = code_identity()
    cases = S.expand(spec)
    jobs = [job_for(c, code["digest"]) for c in cases]
    return spec, code, cases, jobs


def plan(study_id: str, workers: int = 1) -> dict:
    spec, code, cases, jobs = prepare(study_id)
    cached = sum((CACHE / f"{j['key']}.json").exists() for j in jobs)
    secs = sum(estimate_seconds(c) for c, j in zip(cases, jobs) if not (CACHE / f"{j['key']}.json").exists())
    return {"study": spec["id"], "kind": spec["kind"], "cases": len(cases), "cached": cached,
            "to_solve": len(cases) - cached, "estimated_minutes": round(secs / 60 / max(workers, 1), 1),
            "workers": workers, "code": code["digest"]}


# ----------------------------------------------------------------------------- run
def run(study_id: str, workers: int = 1, force: bool = False, log=print) -> dict:
    spec, code, cases, jobs = prepare(study_id)
    folder = S.study_dir(spec["id"])
    sha = S.spec_sha256(spec)
    results_path = folder / "results.json"
    if results_path.exists() and not force:
        old = S.read_json(results_path)
        if old.get("spec_sha256") != sha:
            raise RuntimeError("This study already has results for a different spec. Results are immutable: "
                               "create a new study (with \"parent\") instead of editing this one.")
    CACHE.mkdir(parents=True, exist_ok=True)
    status = {"state": "running", "total": len(cases), "done": 0, "failed": 0, "started": now(), "finished": None}
    S.write_json(folder / "status.json", status)
    results = {}
    todo = []
    for c, j in zip(cases, jobs):
        p = CACHE / f"{j['key']}.json"
        if p.exists():
            results[c["case_id"]] = S.read_json(p)["result"]
        else:
            todo.append((c, j))
    log(f"{spec['id']}: {len(cases)} cases, {len(cases) - len(todo)} cached, {len(todo)} to solve with {workers} worker(s)")

    def finish(c, j, r):
        S.write_json(CACHE / f"{j['key']}.json", {"key": j["key"], "job": j, "result": r, "code": code, "solved": now()})
        results[c["case_id"]] = r
        status["done"] = len(results)
        status["failed"] = sum(1 for x in results.values() if x["status"] == "failed")
        S.write_json(folder / "status.json", status)
        log(f"[{len(results)}/{len(cases)}] {c['case_id']} {c['model']} {c['freq']:g} Hz: {summary(r)}")

    try:
        if workers <= 1 or len(todo) <= 1:
            for c, j in todo:
                finish(c, j, solve(j))
        else:
            import multiprocessing as mp
            from concurrent.futures import ProcessPoolExecutor, as_completed
            with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as pool:
                futures = {pool.submit(solve, j): (c, j) for c, j in todo}
                for f in as_completed(futures):
                    c, j = futures[f]
                    try:
                        r = f.result()
                    except Exception as exc:
                        r = {"status": "failed", "error": f"worker crashed: {exc}"}
                    finish(c, j, r)
    except BaseException:
        status.update(state="failed" if status["done"] < len(cases) else "running", finished=now())
        S.write_json(folder / "status.json", status)
        raise
    out = {"schema": S.RESULTS_SCHEMA, "study": spec["id"], "kind": spec["kind"], "spec_sha256": sha,
           "code": code, "completed": now(),
           "counts": _counts(results.values()),
           "cases": [dict(c, key=j["key"], replay={"engine": j["engine"], "input": j["input"]}, **results[c["case_id"]])
                     for c, j in zip(cases, jobs)]}
    S.write_json(results_path, out)
    status.update(state="complete", finished=now())
    S.write_json(folder / "status.json", status)
    log(f"{spec['id']}: complete. {out['counts']}")
    return out


def _counts(rs) -> dict:
    out = {}
    for r in rs:
        out[r["status"]] = out.get(r["status"], 0) + 1
    return out


def summary(r: dict) -> str:
    if "baseline" in r:
        def one(x):
            return (f"{x.get('status')} {x['mean_thrust_N']:.2f} N/{x['peak_abs_root_torque_Nm']:.2f} N·m"
                    if x.get("mean_thrust_N") is not None else str(x.get("status")))
        return f"chordwise {one(r['baseline'])} | spanwise {one(r['spanwise'])} ({r['elapsed_s']} s)"
    if r.get("thrust_N") is None:
        return f"{r['status']} ({r.get('error') or 'no metrics'})"
    return f"{r['status']} {r['thrust_N']:.3f} N at {r['torque_Nm']:.3f} N·m ({r['elapsed_s']} s)"


# ----------------------------------------------------------------------------- results checks
def results_errors(results: dict, spec: dict) -> list[str]:
    """Structural checks CI runs on a committed results.json (no solver needed)."""
    e = []
    if results.get("schema") != S.RESULTS_SCHEMA:
        e.append(f"results.schema: must be {S.RESULTS_SCHEMA!r}")
    if results.get("study") != spec.get("id"):
        e.append("results.study: does not match spec id")
    if results.get("spec_sha256") != S.spec_sha256(spec):
        e.append("results.spec_sha256: spec.json changed after the run (results are immutable; make a new study)")
    cases = results.get("cases")
    if not isinstance(cases, list) or len(cases) != S.case_count(spec):
        e.append(f"results.cases: expected {S.case_count(spec)} cases")
        return e
    for c in cases:
        if not isinstance(c, dict) or not {"case_id", "key", "status", "model", "freq", "chords_mm", "half_span_mm"} <= set(c):
            e.append(f"results.cases: {c.get('case_id') if isinstance(c, dict) else c!r} is missing fields")
            continue
        if spec["kind"] != "matched-comparison":
            for k in ("thrust_N", "torque_Nm"):
                v = c.get(k)
                if v is not None and not (isinstance(v, (int, float)) and math.isfinite(v)):
                    e.append(f"results.cases[{c['case_id']}].{k}: a finite number or null")
            if c["status"] in ("verified", "ok") and (c.get("thrust_N") is None or c.get("torque_Nm") is None):
                e.append(f"results.cases[{c['case_id']}]: {c['status']} without thrust and torque")
    return e
