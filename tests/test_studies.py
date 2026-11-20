"""Planned studies: spec validation, expansion, schema agreement, run bookkeeping, atlas merge.

Standard library only (CI runs it without the solver); the solver itself is stubbed."""
import _paths  # noqa: F401  (repo root on sys.path)

import copy
import json
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from wingstudy.studies import atlas as A
from wingstudy.studies import run as R
from wingstudy.studies import spec as S

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "schema" / "study-spec.schema.json").read_text(encoding="utf-8"))
TAPER = [200, 150, 110, 80, 55, 35, 20, 10]


def filled(kind="design-set", sid="2026-11-20-test-study"):
    return dict(S.template(sid, kind, "tester"), title="A test study", question="Does the bookkeeping work?")


def design_spec(**kw):
    s = filled()
    s.update(kw)
    return s


class Validation(unittest.TestCase):
    def test_templates_need_a_title_and_question(self):
        for kind in S.KINDS:
            self.assertEqual(S.validate(filled(kind)), [], kind)
            errors = S.validate(S.template("2026-11-20-t", kind, "me"))
            self.assertEqual(errors, ["title: replace the template text", "question: replace the template text"])

    def test_problems_are_reported(self):
        cases = {
            "id": design_spec(id="Not An Id"),
            "unknown field": design_spec(colour="blue"),
            "rigid wings have no structure": design_spec(structure="spanwise", models=["rigid"]),
            "zero chords may only form a tip suffix": design_spec(wings={"designs": [
                {"name": "gap", "chords_mm": [200, 0, 50, 0, 0, 0, 0, 0], "half_span_mm": 300}]}),
            "half_span_mm": design_spec(wings={"designs": [{"name": "x", "chords_mm": TAPER, "half_span_mm": 50}]}),
            "frequencies_hz": design_spec(frequencies_hz=[1.0, 1.0]),
            "numerics[0].steps_per_cycle": design_spec(numerics=[{"steps_per_cycle": 5}]),
            "budget.max_cases": design_spec(models=["t0.50r", "t0.25r"], frequencies_hz=[0.75, 1.0], budget={"max_cases": 3}),
            "sweep: only for geometry-sweep": design_spec(sweep={"count": 4, "half_span_mm": [280, 400]}),
        }
        for needle, spec in cases.items():
            errors = S.validate(spec)
            self.assertTrue(any(needle in e for e in errors), (needle, errors))

    def test_tip_zeros_are_allowed(self):
        s = design_spec(wings={"designs": [{"name": "short", "chords_mm": [200, 120, 60, 20, 0, 0, 0, 0], "half_span_mm": 340}]})
        self.assertEqual(S.validate(s), [])


class Robustness(unittest.TestCase):
    def test_validate_never_raises(self):
        """The website and CI feed validate() arbitrary JSON; it must report, never crash."""
        import random
        rnd = random.Random(7)
        atoms = [None, True, 0, -1, 1.5, "", "x", "t0.50r", "2026-11-20-x", [], {}, [1], {"a": 1}, [[1]], "ab" * 12]
        def junk(depth=0):
            r = rnd.random()
            if depth > 2 or r < 0.5:
                return rnd.choice(atoms)
            if r < 0.75:
                return [junk(depth + 1) for _ in range(rnd.randint(0, 9))]
            return {rnd.choice(sorted(S.TOP_KEYS | {"designs", "from_atlas", "count", "name", "chords_mm"})): junk(depth + 1)
                    for _ in range(rnd.randint(0, 4))}
        for _ in range(3000):
            s = design_spec()
            s[rnd.choice(sorted(S.TOP_KEYS))] = junk()
            self.assertIsInstance(S.validate(s), list)
            self.assertIsInstance(S.validate(junk()), list)

    def test_limits_are_json(self):
        L = json.loads(json.dumps(S.limits()))
        self.assertEqual(L["models"], S.MODELS)
        self.assertEqual(L["id_re"], S.ID_RE.pattern)


class AtlasKeys(unittest.TestCase):
    def test_campaign_keys_resolve_and_catalog_keys_do_not(self):
        rows = ROOT / "atlas" / "data" / "rows"
        rod = json.loads((rows / "rod.json").read_text(encoding="utf-8"))["cols"]["k"][0]
        cat = json.loads((rows / "catalog.json").read_text(encoding="utf-8"))["cols"]["k"][0]
        w = S.atlas_wings([rod])[0]
        self.assertEqual((len(w["chords_mm"]), w["atlas_key"]), (S.NODES, rod))
        with self.assertRaises(KeyError):
            S.atlas_wings([cat])


class Import(unittest.TestCase):
    def test_import_places_a_downloaded_spec(self):
        from wingstudy.studies import cli
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(S, "STUDIES", Path(tmp) / "studies"):
            src = Path(tmp) / "spec.json"
            spec = design_spec()
            src.write_text(json.dumps(spec), encoding="utf-8")
            args = mock.Mock(file=str(src))
            with mock.patch("sys.stdout"):
                self.assertEqual(cli.cmd_import(args), 0)
                self.assertEqual(S.load(spec["id"]), spec)
                self.assertEqual(cli.cmd_import(args), 0)                     # same content again: fine
            src.write_text(json.dumps(dict(spec, title="Something else")), encoding="utf-8")
            with mock.patch("sys.stderr"):
                self.assertEqual(cli.cmd_import(args), 1)                     # never overwrites a different spec
                src.write_text(json.dumps(dict(spec, models=["rigid"], structure="spanwise")), encoding="utf-8")
                self.assertEqual(cli.cmd_import(args), 1)
                src.write_text(json.dumps(dict(spec, wings={"from_atlas": ["0" * 24]})), encoding="utf-8")
                self.assertEqual(cli.cmd_import(args), 1)                     # unknown atlas key


class Expansion(unittest.TestCase):
    def test_count_and_order(self):
        s = design_spec(models=["t0.50r", "t0.25r"], frequencies_hz=[0.75, 1.0],
                        numerics=[{}, {"steps_per_cycle": 100}], budget={"max_cases": 100},
                        wings={"designs": [{"name": "a", "chords_mm": TAPER, "half_span_mm": 340},
                                           {"name": "b", "chords_mm": TAPER, "half_span_mm": 300}]})
        cases = S.expand(s)
        self.assertEqual(len(cases), S.case_count(s))
        self.assertEqual(len(cases), 16)
        self.assertEqual([c["case_id"] for c in cases[:2]], ["c0001", "c0002"])
        self.assertEqual((cases[0]["wing"], cases[0]["model"], cases[0]["freq"]), ("a", "t0.50r", 0.75))
        self.assertEqual(cases[1]["numerics"]["steps_per_cycle"], 100)      # numerics vary fastest
        self.assertEqual(cases[0]["numerics"], S.NUMERICS_DEFAULT)

    def test_matched_structure(self):
        s = design_spec(structure="matched", models=["t0.50"])
        self.assertEqual(S.validate(s), [])
        self.assertTrue(all(c["structure"] == "matched" for c in S.expand(s)))
        self.assertTrue(any("rigid" in e for e in S.validate(design_spec(structure="matched", models=["rigid"]))))

    def test_spec_hash_ignores_key_order(self):
        s = design_spec()
        t = json.loads(json.dumps(s, sort_keys=True))
        self.assertEqual(S.spec_sha256(s), S.spec_sha256(dict(reversed(list(t.items())))))


class Evolutionary(unittest.TestCase):
    def test_upper_bound_and_matched_winners(self):
        s = filled("evolutionary")
        n = 2 * (2 * 2) * (1 + 30)               # 2 objectives x (2 spans x 2 families) x (seed + 30)
        self.assertEqual(S.case_count(s), n)
        s.update(structure="matched", models=["t0.50"], budget={"max_cases": 1000})
        self.assertEqual(S.case_count(s), n + 2)

    def test_search_rules(self):
        def errs(**search):
            s = filled("evolutionary")
            s["search"] = dict(s["search"], **search)
            return S.validate(s)
        self.assertTrue(any("repeats" in e for e in errs(objectives=[{"lambda": 1}, {"lambda": 1.0}])))
        self.assertTrue(any("go together" in e for e in errs(seed_families=[])))
        self.assertTrue(any("objectives[0]" in e for e in errs(objectives=[{"lambda": 1, "torque_budget_Nm": 1}])))
        self.assertTrue(any("seed_families" in e for e in errs(seed_families=["blob"])))
        self.assertTrue(any("step_mm" in e for e in errs(step_mm=0)))
        self.assertTrue(any("give seed" in e for e in errs(seed_half_spans_mm=[], seed_families=[])))
        s = filled("evolutionary")
        s["numerics"] = [{}, {"steps_per_cycle": 100}]
        self.assertTrue(any("exactly one" in e for e in S.validate(s)))
        s = filled("evolutionary")
        s["wings"] = {"designs": [{"name": "up", "chords_mm": [200, 210, 100, 50, 20, 8, 0, 0], "half_span_mm": 300}]}
        e = S.validate(s)
        self.assertTrue(any("must not increase" in x for x in e) and any("min_chord_mm" in x for x in e), e)
        self.assertTrue(any("only for evolutionary" in e for e in S.validate(design_spec(search={"objectives": [{"lambda": 1}]}))))



class SchemaAgreement(unittest.TestCase):
    """schema/study-spec.schema.json must describe the same rules as spec.py."""

    def test_fields_and_enums(self):
        P = SCHEMA["properties"]
        self.assertEqual(set(P), S.TOP_KEYS)
        self.assertEqual(set(SCHEMA["required"]), set(S.REQUIRED))
        self.assertEqual(P["schema"]["const"], S.SPEC_SCHEMA)
        self.assertEqual(tuple(P["kind"]["enum"]), S.KINDS)
        self.assertEqual(tuple(P["structure"]["enum"]), S.STRUCTURES)
        self.assertEqual(P["models"]["items"]["enum"], list(S.MODELS))
        self.assertEqual(re.compile(P["id"]["pattern"]).pattern, S.ID_RE.pattern)
        self.assertEqual(re.compile(P["wings"]["properties"]["from_atlas"]["items"]["pattern"]).pattern, S.KEY_RE.pattern)

    def test_ranges(self):
        P, defs = SCHEMA["properties"], SCHEMA["$defs"]
        f = P["frequencies_hz"]["items"]
        self.assertEqual((f["minimum"], f["maximum"]), S.FREQ_RANGE)
        for k, (lo, hi) in S.NUMERICS_RANGES.items():
            n = defs["numerics"]["properties"][k]
            self.assertEqual((n["minimum"], n["maximum"], n["default"]), (lo, hi, S.NUMERICS_DEFAULT[k]), k)
        d = defs["design"]["properties"]
        self.assertEqual((d["chords_mm"]["minItems"], d["chords_mm"]["maxItems"]), (S.NODES, S.NODES))
        self.assertEqual(d["chords_mm"]["items"]["maximum"], S.CHORD_RANGE[1])
        self.assertEqual((d["half_span_mm"]["minimum"], d["half_span_mm"]["maximum"]), S.HALF_SPAN_RANGE)
        c = P["sweep"]["properties"]["count"]
        self.assertEqual((c["minimum"], c["maximum"]), S.SWEEP_COUNT)


def fake_job(case, digest):
    key = f"{abs(hash((case['case_id'], case['model'], json.dumps(case['numerics'], sort_keys=True)))):024x}"[-24:]
    return {"engine": "design", "key": key, "input": {"level": case["model"], "key": key}}


def fake_solve(job):
    if job["input"]["level"] == "t0.25r":
        return {"status": "failed", "thrust_N": None, "torque_Nm": None, "error": "did not settle", "elapsed_s": 0.0}
    return {"status": "verified", "thrust_N": 2.0, "torque_Nm": 0.9, "tip_twist_deg": 12.0, "elapsed_s": 0.0}


def evo_job(case, digest):
    blob = json.dumps([case["model"], case["structure"], case["freq"], case["chords_mm"], case["half_span_mm"]])
    import hashlib
    key = hashlib.sha256(blob.encode()).hexdigest()[:24]
    return {"engine": "matched" if case["structure"] == "matched" else "design", "key": key,
            "input": {"chords": case["chords_mm"], "half_span": case["half_span_mm"], "structure": case["structure"]}}


def evo_solve(job):
    """Thrust grows with area; torque with area x span. Lambda searches have an interior optimum."""
    if job["engine"] == "matched":
        return {"status": "complete", "baseline": {"status": "verified", "mean_thrust_N": 2.0, "peak_abs_root_torque_Nm": 0.9},
                "spanwise": {"status": "verified", "mean_thrust_N": 1.9, "peak_abs_root_torque_Nm": 0.8}, "elapsed_s": 0.0}
    c, hs = job["input"]["chords"], job["input"]["half_span"]
    area = sum(c) * hs / 8 / 1e4
    return {"status": "verified", "thrust_N": 0.2 * area, "torque_Nm": 0.0004 * area * hs, "elapsed_s": 0.0}


class RunAndMerge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        t = Path(self.tmp.name)
        self.patches = [mock.patch.object(S, "STUDIES", t / "studies"), mock.patch.object(R, "CACHE", t / "cache"),
                        mock.patch.object(R, "job_for", fake_job), mock.patch.object(R, "solve", fake_solve),
                        mock.patch("wingstudy.identity.code_identity",
                                   return_value={"digest": "0123456789abcdef", "structural": "c130", "ptera": None})]
        for p in self.patches:
            p.start()
        self.spec = design_spec(models=["t0.50r", "t0.25r"], numerics=[{}, {"steps_per_cycle": 100}])
        S.write_json(S.study_dir(self.spec["id"]) / "spec.json", self.spec)

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_run_writes_results_status_and_cache(self):
        out = R.run(self.spec["id"], log=lambda *a: None)
        folder = S.study_dir(self.spec["id"])
        self.assertEqual(out["counts"], {"verified": 2, "failed": 2})
        self.assertEqual(S.read_json(folder / "status.json")["state"], "complete")
        self.assertEqual(R.results_errors(S.read_json(folder / "results.json"), self.spec), [])
        self.assertEqual(len(list(R.CACHE.glob("*.json"))), 4)
        with mock.patch.object(R, "solve", side_effect=AssertionError("should be cached")):
            R.run(self.spec["id"], log=lambda *a: None)            # second run: all from cache

    def test_results_are_immutable(self):
        R.run(self.spec["id"], log=lambda *a: None)
        changed = copy.deepcopy(self.spec)
        changed["frequencies_hz"] = [1.25]
        S.write_json(S.study_dir(self.spec["id"]) / "spec.json", changed)
        with self.assertRaises(RuntimeError):
            R.run(self.spec["id"], log=lambda *a: None)
        errs = R.results_errors(S.read_json(S.study_dir(self.spec["id"]) / "results.json"), changed)
        self.assertTrue(any("spec_sha256" in e for e in errs))

    def test_merge_into_atlas(self):
        R.run(self.spec["id"], log=lambda *a: None)
        studies = A.completed(S.STUDIES)
        self.assertEqual(len(studies), 1)
        D = {"studies": [{"id": "rod"}], "models": [{"id": "t0.50r"}], "freqs": [1.0], "statuses": ["verified"],
             "catalog": {"first": 1}, "cols": {k: [0] for k in ("s", "m", "f", "T", "Q", "H", "W", "S", "src", "k", "obj")}}
        D["cols"]["C"] = [0.0] * 8
        added = A.merge(D, studies)
        self.assertEqual(added, 2)                                  # failed cases stay off the map
        self.assertEqual(D["catalog"]["end"], 1)
        self.assertEqual(D["studies"][1]["id"], self.spec["id"])
        self.assertEqual(D["cols"]["src"][1:], [A.SRC_STUDY] * 2)
        self.assertEqual(len(D["cols"]["C"]), 8 * 3)
        self.assertIn("100 steps per cycle", D["row_notes"]["2"])

    def test_evolutionary_run(self):
        try:
            import numpy  # noqa: F401  (family seeds use adaptive.seed, which imports numpy)
        except ImportError:
            self.skipTest("numpy not installed")
        spec = filled("evolutionary", "2026-11-20-evo")
        spec.update(structure="matched", models=["t0.50"], budget={"max_cases": 1000})
        spec["search"].update(solves_per_lineage=12)
        S.write_json(S.study_dir(spec["id"]) / "spec.json", spec)
        with mock.patch.object(R, "job_for", evo_job), mock.patch.object(R, "solve", evo_solve):
            out = R.run(spec["id"], log=lambda *a: None)
        self.assertEqual(R.results_errors(out, spec), [])
        self.assertEqual(len(out["searches"]), 2)
        keys = {c["key"]: c for c in out["cases"]}
        for x in out["searches"]:
            self.assertIn(x["winner"], keys)
            self.assertEqual(keys[x["matched"]]["structure"], "matched")
            self.assertEqual(len(x["lineages"]), 4)
            for lin in x["lineages"]:
                self.assertLessEqual(lin["solves"], 12)
                scores = [a["score"] for a in lin["accepted"]]
                self.assertEqual(scores, sorted(scores))              # a climb only accepts improvements
        budget = next(x for x in out["searches"] if "torque_budget_Nm" in x["objective"])
        self.assertLessEqual(keys[budget["winner"]]["torque_Nm"], 1.0)
        self.assertLessEqual(len(out["cases"]), S.case_count(spec))
        D = {"studies": [], "models": [], "freqs": [], "statuses": [], "cols": {k: [] for k in ("s", "m", "f", "T", "Q", "H", "W", "S", "src", "k", "obj", "C")}}
        added = A.merge(D, [(spec, out)])
        self.assertEqual(added, sum(1 for c in out["cases"] if c["structure"] != "matched"))
        self.assertEqual(len(D["span_comparisons"]), 2)
        win = D["row_search"]
        self.assertTrue(any(v.get("winner") for v in win.values()))
        self.assertTrue(all(src & A.SRC_STUDY and src & 1 for src in D["cols"]["src"]))

    def test_matched_merge(self):
        spec = design_spec(id="2026-11-20-matched", structure="matched", models=["t0.50"])
        cases = [dict(c, key="ab" * 12, status="complete", replay={"engine": "matched", "input": {"numerics": {}}},
                      baseline={"status": "verified", "mean_thrust_N": 3.0}, spanwise={"status": "verified", "mean_thrust_N": 2.5})
                 for c in S.expand(spec)]
        results = {"schema": S.RESULTS_SCHEMA, "study": spec["id"], "spec_sha256": S.spec_sha256(spec),
                   "code": {"digest": "x"}, "cases": cases}
        D = {"studies": [], "models": [], "freqs": [], "statuses": [], "cols": {"s": [], "C": []}}
        self.assertEqual(A.merge(D, [(spec, results)]), 0)
        self.assertEqual(D["span_comparisons"][0]["source"]["study"], spec["id"])


if __name__ == "__main__":
    unittest.main()
