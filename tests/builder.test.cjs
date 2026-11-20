// The study builder's validator (site/new/spec.js) must give exactly the errors that
// wingstudy/studies/spec.py gives, for valid specs and for every kind of mistake.
//   node tests/builder.test.cjs            (uses `python` on PATH; set PYTHON to override)
"use strict";
const { execFileSync } = require("child_process");
const path = require("path");
const assert = require("assert");

const ROOT = path.resolve(__dirname, "..");
const PY = process.env.PYTHON || "python";
const py = (code, input = "") => execFileSync(PY, ["-c", code], { cwd: ROOT, input, encoding: "utf8", maxBuffer: 64 << 20 });

const TAPER = [200, 150, 110, 80, 55, 35, 20, 10];
const base = {
  schema: "wingstudy/study-spec@1", id: "2026-11-20-parity", title: "Parity check", author: "ci",
  question: "Do both validators agree?", kind: "design-set", structure: "chordwise", models: ["t0.50r"],
  frequencies_hz: [1.0], numerics: [{ span_panels: 8, chord_panels: 4, steps_per_cycle: 50, cycles: 4 }],
  wings: { designs: [{ name: "taper", chords_mm: TAPER, half_span_mm: 340 }] }, budget: { max_cases: 20 },
};
const w = (...designs) => ({ designs });
const d = (o = {}) => Object.assign({ name: "x", chords_mm: TAPER, half_span_mm: 300 }, o);
const m = o => Object.assign(JSON.parse(JSON.stringify(base)), o);
const drop = (...ks) => { const s = m({}); ks.forEach(k => delete s[k]); return s; };
const sweep = { kind: "geometry-sweep", wings: undefined, sweep: { count: 16, half_span_mm: [280, 400], seed: 1 } };
const matched = { structure: "matched", models: ["t0.50"] };
const SEARCH = { objectives: [{ torque_budget_Nm: 1.0 }, { lambda: 1.25 }], seed_half_spans_mm: [220, 340], seed_families: ["triangle", "convex"],
  solves_per_lineage: 30, step_mm: 20, min_chord_mm: 10, decreasing: true };
const evo = (o = {}) => ({ kind: "evolutionary", wings: undefined, search: Object.assign({}, SEARCH, o), budget: { max_cases: 1000 } });
const clean = o => JSON.parse(JSON.stringify(o));      // drop undefined keys

const FIX = [
  base, [], "spec", null, {}, drop("schema", "title"), m({ models: null, kind: null, title: null, frequencies_hz: null }), m({ colour: "blue", extra: 1 }), m({ schema: "v2" }), m({ schema: ["x"] }),
  m({ id: "Bad Id" }), m({ id: "2026-11-20-x\n" }), m({ id: "2026-11-20-" + "a".repeat(80) }), m({ id: 7 }),
  m({ title: "  a " }), m({ title: "x".repeat(121) }), m({ author: "" }), m({ question: 5 }),
  m({ title: "Describe the study in a short title" }), m({ question: "What should this study answer?" }),
  m({ kind: "search" }), m({ kind: ["design-set"] }), m({ structure: "both" }), m({ structure: null }), m({ structure: {} }),
  m({ models: [] }), m({ models: "t0.50" }), m({ models: ["t0.50", "t0.50"] }), m({ models: ["x", 3, [1], null, true] }),
  m({ models: ["rigid"], structure: "spanwise" }), m({ models: ["t0.50", "1"] }), m({ models: ["t0.50", 1] }),
  m({ frequencies_hz: [] }), m({ frequencies_hz: [1, 1] }), m({ frequencies_hz: [0.1, 1] }), m({ frequencies_hz: ["1"] }),
  m({ frequencies_hz: [true] }), m({ frequencies_hz: [[1]] }), m({ frequencies_hz: [0.25, 3] }),
  m({ numerics: [] }), m({ numerics: "x" }), m({ numerics: null }), m({ numerics: [{}] }), m({ numerics: [{}, {}] }),
  m({ numerics: [{}, { span_panels: 8 }] }), m({ numerics: [{ span_panels: 1, foo: 2 }] }), m({ numerics: [3, {}] }),
  m({ numerics: [{ steps_per_cycle: 500, cycles: 1.5 }] }), m({ numerics: [{ chord_panels: true }] }), m({ numerics: [{ span_panels: [1] }] }),
  m({ wings: null }), m({ wings: {} }), m({ wings: { designs: [] } }), m({ wings: { designs: "abc" } }), m({ wings: { designs: [1, "a"] } }),
  m({ wings: { designs: [d()], x: 1 } }), m({ wings: w(d({ colour: 1 })) }), m({ wings: w(d({ name: undefined })) }),
  m({ wings: w(d({ name: "" })) }), m({ wings: w(d({ name: [1] })) }), m({ wings: w(d({ name: "a" }), d({ name: "a" })) }),
  m({ wings: w(d({ name: "é".repeat(60) })) }), m({ wings: w(d({ name: "é".repeat(61) })) }),
  m({ wings: w(d({ chords_mm: [200, 100] })) }), m({ wings: w(d({ chords_mm: TAPER.map(String) })) }),
  m({ wings: w(d({ chords_mm: [200, -1, 0, 0, 0, 0, 0, 0] })) }), m({ wings: w(d({ chords_mm: [200, 0, 50, 0, 0, 0, 0, 0] })) }),
  m({ wings: w(d({ chords_mm: [200, 0, 0, 0, 0, 0, 0, 0] })) }), m({ wings: w(d({ chords_mm: [0, 0, 0, 0, 0, 0, 0, 0] })) }),
  m({ wings: w(d({ chords_mm: [500, 100, 0, 0, 0, 0, 0, 0] })) }), m({ wings: w(d({ chords_mm: [200, 4, 0, 0, 0, 0, 0, 0] })) }),
  m({ wings: w(d({ chords_mm: [200, 120, 60, 20, 0, 0, 0, 0] })) }), m({ wings: w(d({ half_span_mm: 50 })) }),
  m({ wings: w(d({ half_span_mm: "300" })) }), m({ wings: w(d({ half_span_mm: undefined })) }),
  m({ wings: { from_atlas: ["41b86f0c5546d36090730546"] } }), m({ wings: { from_atlas: ["41B86F0C5546D36090730546"] } }),
  m({ wings: { from_atlas: ["41b86f0c5546d36090730546", "41b86f0c5546d36090730546"] } }), m({ wings: { from_atlas: "41b86f0c5546d36090730546" } }),
  m({ wings: { from_atlas: [5] } }), m({ wings: { designs: [d()], from_atlas: ["41b86f0c5546d36090730546"] } }),
  m({ sweep: { count: 3 } }),
  m(sweep), m(Object.assign({}, sweep, { wings: base.wings })), m(Object.assign({}, sweep, { sweep: null })),
  m(Object.assign({}, sweep, { sweep: { count: 0, half_span_mm: [400, 280], seed: -1, x: 1 } })),
  m(Object.assign({}, sweep, { sweep: { count: true, half_span_mm: [280, "a"] } })),
  m(Object.assign({}, sweep, { sweep: { count: 5000, half_span_mm: [50, 900] } })),
  m(Object.assign({}, sweep, { sweep: { count: 64, half_span_mm: [280, 400] } })),
  m(matched), m(Object.assign({}, matched, { models: ["rigid", "t0.50"] })), m(Object.assign({}, matched, { sweep: { count: 2 } })),
  m(evo()), m(Object.assign(evo(), { structure: "matched", models: ["t0.50"] })), m(Object.assign(evo(), { structure: "matched" })),
  m(Object.assign(evo(), { budget: { max_cases: 10 } })), m(Object.assign(evo(), { search: null })), m(Object.assign(evo(), { search: [] })),
  m(evo({ objectives: [] })), m(evo({ objectives: "lambda" })), m(evo({ objectives: [{ lambda: 1 }, { lambda: 1.0 }] })),
  m(evo({ objectives: [{ lambda: 11 }, { torque_budget_Nm: 0 }, { lambda: true }, { lambda: "1" }] })),
  m(evo({ objectives: [{ lambda: 1, torque_budget_Nm: 1 }, {}, 3, { budget: 1 }] })), m(evo({ objectives: Array(7).fill(0).map((_, i) => ({ lambda: i })) })),
  m(evo({ seed_half_spans_mm: [] })), m(evo({ seed_families: [] })), m(evo({ seed_half_spans_mm: [], seed_families: [] })),
  m(evo({ seed_half_spans_mm: [300, 300] })), m(evo({ seed_half_spans_mm: [50] })), m(evo({ seed_half_spans_mm: "300" })),
  m(evo({ seed_half_spans_mm: Array(11).fill(0).map((_, i) => 200 + i) })), m(evo({ seed_families: ["blob"] })),
  m(evo({ seed_families: ["triangle", "triangle"] })), m(evo({ seed_families: [1] })), m(evo({ seed_families: "square" })),
  m(evo({ solves_per_lineage: 0 })), m(evo({ solves_per_lineage: 501 })), m(evo({ solves_per_lineage: 2.5 })), m(evo({ solves_per_lineage: null })),
  m(evo({ step_mm: 0 })), m(evo({ step_mm: "20" })), m(evo({ min_chord_mm: 4 })), m(evo({ min_chord_mm: 100.5 })), m(evo({ decreasing: "yes" })),
  m(evo({ decreasing: false })), m(evo({ extra: 1 })), m(Object.assign(evo(), { numerics: [{}, { steps_per_cycle: 100 }] })),
  m(Object.assign(evo(), { sweep: { count: 3 } })), m(Object.assign(evo(), { wings: "x" })), m(Object.assign(evo(), { wings: {} })),
  m(Object.assign(evo({ seed_half_spans_mm: [], seed_families: [] }), { wings: w(d()) })),
  m(Object.assign(evo(), { wings: w(d({ chords_mm: [200, 210, 100, 50, 20, 8, 0, 0] })) })),
  m(Object.assign(evo({ decreasing: false, min_chord_mm: "x" }), { wings: w(d({ chords_mm: [200, 210, 100, 50, 20, 8, 0, 0] })) })),
  m(Object.assign(evo({ seed_half_spans_mm: [], seed_families: [] }), { wings: { from_atlas: ["41b86f0c5546d36090730546"] } })),
  m({ search: { objectives: [{ lambda: 1 }] } }), m(Object.assign({}, sweep, { search: SEARCH })),
  m({ budget: null }), m({ budget: {} }), m({ budget: { max_cases: 0 } }), m({ budget: { max_cases: 5, x: 1 } }), m({ budget: [] }),
  m({ models: ["t0.50r", "t0.25r"], frequencies_hz: [0.75, 1, 1.25], budget: { max_cases: 5 } }),
  m({ parent: "nope" }), m({ parent: "2026-11-19-numerics-hardware-winner" }), m({ notes: 3 }), m({ notes: "fine" }),
].map(x => (x && typeof x === "object" ? clean(x) : x));

// plus seeded random mutations: any field replaced by junk, nested a few levels deep
let seed = 12345;
const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
const pick = a => a[Math.floor(rnd() * a.length)];
const ATOMS = [null, true, false, 0, -1, 1.5, 1, 8, 50, "", "x", "t0.50r", "rigid", "2026-11-20-x", [], {}, [1], [200, 0], TAPER, "ab".repeat(12),
  "matched", "triangle", [300], { lambda: 1 }, { torque_budget_Nm: 1 }];
const KEYS = Object.keys(base).concat(["sweep", "search", "parent", "notes", "designs", "from_atlas", "count", "half_span_mm", "chords_mm", "name", "seed", "span_panels",
  "objectives", "lambda", "torque_budget_Nm", "seed_half_spans_mm", "seed_families", "solves_per_lineage", "step_mm", "min_chord_mm", "decreasing"]);
const junk = (dep = 0) => { const r = rnd(); if (dep > 2 || r < 0.5) return pick(ATOMS);
  if (r < 0.75) return Array.from({ length: Math.floor(rnd() * 9) }, () => junk(dep + 1));
  const o = {}; for (let i = Math.floor(rnd() * 4); i > 0; i--) o[pick(KEYS)] = junk(dep + 1); return o; };
for (let i = 0; i < 400; i++) { const s = m({}); s[pick(KEYS.slice(0, 13))] = junk(); if (rnd() < 0.3) s.kind = pick(["geometry-sweep", "evolutionary"]); if (rnd() < 0.2) s.structure = "matched"; FIX.push(s); }
for (let i = 0; i < 300; i++) {                     // evolutionary specs with junk inside the search block
  const s = clean(m(evo())); if (rnd() < 0.5) s.search[pick(Object.keys(SEARCH).concat(["x"]))] = junk(); else s[pick(KEYS.slice(0, 14))] = junk();
  if (rnd() < 0.3) s.wings = rnd() < 0.5 ? w(d({ chords_mm: pick([TAPER, [200, 210, 100, 50, 20, 8, 0, 0], [200, 9, 0, 0, 0, 0, 0, 0]]) })) : junk();
  FIX.push(s);
}

const L = JSON.parse(py("import json; from wingstudy.studies import spec; print(json.dumps(spec.limits()))"));
const want = JSON.parse(py("import json,sys; from wingstudy.studies import spec; print(json.dumps([spec.validate(s) for s in json.loads(sys.stdin.buffer.read())]))", JSON.stringify(FIX)));
const V = require(path.join(ROOT, "site", "new", "spec.js")).make(L);

let bad = 0, nValid = 0;
FIX.forEach((s, i) => {
  const got = V.validate(s);
  if (!want[i].length) nValid++;
  try { assert.deepStrictEqual(got, want[i]); }
  catch (_) { bad++; console.log(`MISMATCH #${i}: ${JSON.stringify(s).slice(0, process.env.FULL ? 5000 : 160)}\n  python: ${JSON.stringify(want[i])}\n  js:     ${JSON.stringify(got)}`); }
});
// case counts agree for every valid spec
const counts = JSON.parse(py("import json,sys; from wingstudy.studies import spec; print(json.dumps([spec.case_count(s) if isinstance(s, dict) and not spec.validate(s) else None for s in json.loads(sys.stdin.buffer.read())]))", JSON.stringify(FIX)));
FIX.forEach((s, i) => { if (counts[i] !== null && V.caseCount(s) !== counts[i]) { bad++; console.log(`COUNT MISMATCH #${i}: ${counts[i]} vs ${V.caseCount(s)}`); } });
if (bad) { console.log(`FAIL ${bad} of ${FIX.length} specs disagree`); process.exit(1); }
console.log(`PASS builder validator matches Python on ${FIX.length} specs (${nValid} valid, ${FIX.length - nValid} with errors)`);
