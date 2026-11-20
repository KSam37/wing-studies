/* Study-spec validator for the browser: a line-by-line port of wingstudy/studies/spec.py.
   Its constants come from spec.limits() at site build time, and tests/builder.test.cjs checks
   that both give the same errors, in the same order, for a shared set of specs.
   One known difference: JSON cannot tell 8 from 8.0 in JavaScript, so "8.0" passes here where
   Python asks for a whole number. The builder never writes such values. */
(function (root) {
  "use strict";

  function pyRepr(x) {
    if (x === null || x === undefined) return "None";
    if (x === true) return "True";
    if (x === false) return "False";
    if (typeof x === "string") return x.includes("'") && !x.includes('"') ? `"${x}"` : `'${x.replace(/'/g, "\\'")}'`;
    if (Array.isArray(x)) return "[" + x.map(pyRepr).join(", ") + "]";
    if (typeof x === "object") return "{" + Object.keys(x).map(k => pyRepr(k) + ": " + pyRepr(x[k])).join(", ") + "}";
    return String(x);
  }
  const pyStr = x => typeof x === "string" ? x : pyRepr(x);
  const isNum = v => typeof v === "number" && Number.isFinite(v);
  const isInt = v => Number.isInteger(v);
  const isObj = v => v !== null && typeof v === "object" && !Array.isArray(v);
  const truthy = v => !(v === null || v === undefined || v === false || v === 0 || v === "" ||
                        (Array.isArray(v) && !v.length) || (isObj(v) && !Object.keys(v).length));
  const get = (o, k, d = null) => Object.prototype.hasOwnProperty.call(o, k) ? o[k] : d;
  const has = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
  const clen = s => [...s].length;                     // Python counts code points
  const g = n => String(n);                            // Python's :g for these round constants

  function make(L) {
    const ID_RE = new RegExp(L.id_re), KEY_RE = new RegExp(L.key_re);
    const MODELS = L.models, TOP = new Set(L.top_keys);
    const [FLO, FHI] = L.freq_range, [HLO, HHI] = L.half_span_range, [CLO, CHI] = L.chord_range, [SLO, SHI] = L.sweep_count;
    const DEF = L.numerics_default;
    const numericsOf = n => Object.fromEntries(Object.keys(DEF).map(k => [k, has(n, k) ? n[k] : DEF[k]]));
    const canon = o => JSON.stringify(Object.fromEntries(Object.keys(o).sort().map(k => [k, o[k]])));

    function validateChords(chords, where) {
      const e = [];
      if (!Array.isArray(chords) || chords.length !== L.nodes || !chords.every(isNum))
        return [`${where}: ${L.nodes} chord lengths in mm, root to tip`];
      if (chords.some(c => c < 0)) return [`${where}: chords cannot be negative`];
      let active = chords.findIndex(c => c === 0); if (active < 0) active = chords.length;
      if (chords.slice(active).some(c => c > 0)) e.push(`${where}: zero chords may only form a tip suffix`);
      if (active < 2) e.push(`${where}: at least the root and one more station must be positive`);
      for (const c of chords.slice(0, active))
        if (!(CLO <= c && c <= CHI)) { e.push(`${where}: positive chords must be ${g(CLO)}-${g(CHI)} mm`); break; }
      return e;
    }

    function caseCount(spec) {
      const nw = spec.kind === "geometry-sweep" ? spec.sweep.count
        : (spec.wings.designs || []).length + (spec.wings.from_atlas || []).length;
      return nw * spec.models.length * spec.frequencies_hz.length * get(spec, "numerics", [DEF]).length;
    }

    function validate(spec) {
      if (!isObj(spec)) return ["spec: must be a JSON object"];
      const e = L.required.filter(k => get(spec, k) === null).map(k => `${k}: required`);   // null counts as missing
      for (const k of Object.keys(spec)) if (!TOP.has(k)) e.push(`${k}: unknown field`);
      const schema = get(spec, "schema");
      if (schema !== null && schema !== L.spec_schema) e.push(`schema: must be ${pyRepr(L.spec_schema)}`);
      const sid = get(spec, "id");
      if (sid !== null && (typeof sid !== "string" || !ID_RE.test(sid) || clen(sid) > 80))
        e.push("id: YYYY-MM-DD-short-name, lower case letters, digits and hyphens, at most 80 characters");
      for (const [k, lo, hi] of [["title", 3, 120], ["author", 1, 60], ["question", 3, 600]]) {
        const v = get(spec, k);
        if (v !== null && (typeof v !== "string" || !(lo <= clen(v.trim()) && clen(v.trim()) <= hi))) e.push(`${k}: text, ${lo}-${hi} characters`);
      }
      const kind = get(spec, "kind");
      if (kind !== null && !L.kinds.includes(kind)) e.push(`kind: one of ${L.kinds.join(", ")}`);
      const structure = get(spec, "structure", "chordwise");
      if (!L.structures.includes(structure)) e.push(`structure: one of ${L.structures.join(", ")}`);
      const models = get(spec, "models");
      if (models !== null) {
        if (!Array.isArray(models) || !models.length || new Set(models.map(pyStr)).size !== models.length)
          e.push("models: a non-empty list without repeats");
        else {
          const bad = models.filter(m => typeof m !== "string" || !has(MODELS, m));
          if (bad.length) e.push(`models: unknown ${pyRepr(bad)}; choose from ${Object.keys(MODELS).join(", ")}`);
          if (models.includes("rigid") && (kind === "matched-comparison" || structure === "spanwise"))
            e.push("models: rigid wings have no structure to bend; remove 'rigid' for spanwise or matched studies");
        }
      }
      const freqs = get(spec, "frequencies_hz");
      if (freqs !== null) {
        if (!Array.isArray(freqs) || !freqs.length || !freqs.every(isNum) || new Set(freqs).size !== freqs.length)
          e.push("frequencies_hz: a non-empty list of distinct numbers");
        else if (!freqs.every(f => FLO <= f && f <= FHI)) e.push(`frequencies_hz: each ${g(FLO)}-${g(FHI)} Hz`);
      }
      const numerics = get(spec, "numerics", [DEF]);
      if (!Array.isArray(numerics) || !numerics.length) e.push("numerics: a non-empty list of numerical settings");
      else {
        numerics.forEach((n, j) => {
          if (!isObj(n)) { e.push(`numerics[${j}]: an object`); return; }
          for (const k of Object.keys(n)) if (!has(L.numerics_ranges, k)) e.push(`numerics[${j}].${k}: unknown setting`);
          for (const [k, [lo, hi]] of Object.entries(L.numerics_ranges)) {
            const v = has(n, k) ? n[k] : DEF[k];
            if (!isInt(v) || !(lo <= v && v <= hi)) e.push(`numerics[${j}].${k}: whole number ${lo}-${hi}`);
          }
        });
        if (new Set(numerics.filter(isObj).map(n => canon(numericsOf(n)))).size !== numerics.length) e.push("numerics: settings repeat");
      }
      const wings = get(spec, "wings"), sweep = get(spec, "sweep");
      if (kind === "design-set" || kind === "matched-comparison") {
        if (sweep !== null) e.push("sweep: only for geometry-sweep studies");
        if (!isObj(wings) || !(truthy(get(wings, "designs")) || truthy(get(wings, "from_atlas")))) e.push("wings: give designs and/or from_atlas");
        else {
          for (const k of Object.keys(wings)) if (k !== "designs" && k !== "from_atlas") e.push(`wings.${k}: unknown field`);
          const names = new Set();
          let designs = truthy(get(wings, "designs")) ? wings.designs : [];
          if (!Array.isArray(designs)) { e.push("wings.designs: a list of outlines"); designs = []; }
          designs.forEach((w, j) => {
            const where = `wings.designs[${j}]`;
            if (!isObj(w)) { e.push(`${where}: an object`); return; }
            for (const k of Object.keys(w)) if (!["name", "chords_mm", "half_span_mm"].includes(k)) e.push(`${where}.${k}: unknown field`);
            const name = get(w, "name", `wing ${j + 1}`);
            if (typeof name !== "string" || !(1 <= clen(name) && clen(name) <= 60) || names.has(name)) e.push(`${where}.name: unique text, 1-60 characters`);
            if (typeof name === "string") names.add(name);
            e.push(...validateChords(get(w, "chords_mm"), `${where}.chords_mm`));
            const hs = get(w, "half_span_mm");
            if (!isNum(hs) || !(HLO <= hs && hs <= HHI)) e.push(`${where}.half_span_mm: ${g(HLO)}-${g(HHI)} mm`);
          });
          const keys = truthy(get(wings, "from_atlas")) ? wings.from_atlas : [];
          if (!Array.isArray(keys) || !keys.every(k => typeof k === "string" && KEY_RE.test(k)))
            e.push("wings.from_atlas: a list of 24-character atlas design keys");
          else if (new Set(keys).size !== keys.length) e.push("wings.from_atlas: keys repeat");
        }
      } else if (kind === "geometry-sweep") {
        if (wings !== null) e.push("wings: not used by geometry-sweep studies (use sweep)");
        if (!isObj(sweep)) e.push("sweep: required for geometry-sweep studies");
        else {
          for (const k of Object.keys(sweep)) if (!["count", "half_span_mm", "seed"].includes(k)) e.push(`sweep.${k}: unknown field`);
          const c = get(sweep, "count");
          if (!isInt(c) || !(SLO <= c && c <= SHI)) e.push(`sweep.count: whole number ${SLO}-${SHI}`);
          const hs = get(sweep, "half_span_mm");
          if (!Array.isArray(hs) || hs.length !== 2 || !hs.every(isNum) || !(hs[0] < hs[1]) || hs[0] < HLO || hs[1] > HHI)
            e.push(`sweep.half_span_mm: [low, high] within ${g(HLO)}-${g(HHI)} mm`);
          if (has(sweep, "seed") && !(isInt(sweep.seed) && sweep.seed >= 0)) e.push("sweep.seed: whole number >= 0");
        }
      }
      const budget = get(spec, "budget");
      if (budget !== null && (!isObj(budget) || Object.keys(budget).some(k => k !== "max_cases") || !isInt(get(budget, "max_cases")) || budget.max_cases < 1))
        e.push('budget: {"max_cases": whole number >= 1}');
      if (has(spec, "parent") && (typeof spec.parent !== "string" || !ID_RE.test(spec.parent))) e.push("parent: the id of the study this one follows from");
      if (has(spec, "notes") && typeof spec.notes !== "string") e.push("notes: text");
      for (const k of ["title", "question"]) if (get(spec, k) === L.placeholders[k]) e.push(`${k}: replace the template text`);
      if (!e.length) {
        const n = caseCount(spec), cap = budget ? budget.max_cases : null;
        if (cap !== null && n > cap) e.push(`budget.max_cases: the spec expands to ${n} cases, more than ${cap}`);
      }
      return e;
    }
    return { validate, caseCount, validateChords, numericsOf };
  }

  const api = { make, pyRepr };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.WingSpec = api;
})(typeof window !== "undefined" ? window : globalThis);
