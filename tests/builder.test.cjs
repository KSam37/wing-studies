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
const matched = { kind: "matched-comparison", structure: undefined, models: ["t0.50"] };
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
  m({ budget: null }), m({ budget: {} }), m({ budget: { max_cases: 0 } }), m({ budget: { max_cases: 5, x: 1 } }), m({ budget: [] }),
  m({ models: ["t0.50r", "t0.25r"], frequencies_hz: [0.75, 1, 1.25], budget: { max_cases: 5 } }),
  m({ parent: "nope" }), m({ parent: "2026-11-19-numerics-hardware-winner" }), m({ notes: 3 }), m({ notes: "fine" }),
].map(x => (x && typeof x === "object" ? clean(x) : x));

// plus seeded random mutations: any field replaced by junk, nested a few levels deep
let seed = 12345;
const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648);
const pick = a => a[Math.floor(rnd() * a.length)];
const ATOMS = [null, true, false, 0, -1, 1.5, 1, 8, 50, "", "x", "t0.50r", "rigid", "2026-11-20-x", [], {}, [1], [200, 0], TAPER, "ab".repeat(12)];
const KEYS = Object.keys(base).concat(["sweep", "parent", "notes", "designs", "from_atlas", "count", "half_span_mm", "chords_mm", "name", "seed", "span_panels"]);
const junk = (dep = 0) => { const r = rnd(); if (dep > 2 || r < 0.5) return pick(ATOMS);
  if (r < 0.75) return Array.from({ length: Math.floor(rnd() * 9) }, () => junk(dep + 1));
  const o = {}; for (let i = Math.floor(rnd() * 4); i > 0; i--) o[pick(KEYS)] = junk(dep + 1); return o; };
for (let i = 0; i < 400; i++) { const s = m({}); s[pick(KEYS.slice(0, 13))] = junk(); if (rnd() < 0.3) s.kind = pick(["geometry-sweep", "matched-comparison"]); FIX.push(s); }

const L = JSON.parse(py("import json; from wingstudy.studies import spec; print(json.dumps(spec.limits()))"));
const want = JSON.parse(py("import json,sys; from wingstudy.studies import spec; print(json.dumps([spec.validate(s) for s in json.load(sys.stdin)]))", JSON.stringify(FIX)));
const V = require(path.join(ROOT, "site", "new", "spec.js")).make(L);

let bad = 0, nValid = 0;
FIX.forEach((s, i) => {
  const got = V.validate(s);
  if (!want[i].length) nValid++;
  try { assert.deepStrictEqual(got, want[i]); }
  catch (_) { bad++; console.log(`MISMATCH #${i}: ${JSON.stringify(s).slice(0, 160)}\n  python: ${JSON.stringify(want[i])}\n  js:     ${JSON.stringify(got)}`); }
});
// case counts agree for every valid spec
const counts = JSON.parse(py("import json,sys; from wingstudy.studies import spec; print(json.dumps([spec.case_count(s) if isinstance(s, dict) and not spec.validate(s) else None for s in json.load(sys.stdin)]))", JSON.stringify(FIX)));
FIX.forEach((s, i) => { if (counts[i] !== null && V.caseCount(s) !== counts[i]) { bad++; console.log(`COUNT MISMATCH #${i}: ${counts[i]} vs ${V.caseCount(s)}`); } });
if (bad) { console.log(`FAIL ${bad} of ${FIX.length} specs disagree`); process.exit(1); }
console.log(`PASS builder validator matches Python on ${FIX.length} specs (${nValid} valid, ${FIX.length - nValid} with errors)`);
