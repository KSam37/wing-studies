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

    const searchOf = spec => Object.assign({}, L.search_default, spec.search);
    function lineagesPerSearch(spec) {
      const sr = searchOf(spec), w = truthy(get(spec, "wings")) ? spec.wings : {};
      return sr.seed_half_spans_mm.length * sr.seed_families.length
        + (truthy(get(w, "designs")) ? w.designs : []).length + (truthy(get(w, "from_atlas")) ? w.from_atlas : []).length;
    }

    function searchErrors(search) {
      if (!isObj(search)) return ["search: required for evolutionary studies"];
      const e = Object.keys(search).filter(k => !L.search_keys.includes(k)).map(k => `search.${k}: unknown field`);
      const objs = get(search, "objectives");
      if (!Array.isArray(objs) || !(1 <= objs.length && objs.length <= L.objectives_max))
        e.push(`search.objectives: a list of 1-${L.objectives_max} objectives`);
      else {
        const seen = new Set();
        objs.forEach((o, j) => {
          const where = `search.objectives[${j}]`;
          if (!isObj(o) || Object.keys(o).length !== 1 || !["lambda", "torque_budget_Nm"].includes(Object.keys(o)[0])) {
            e.push(`${where}: one of lambda or torque_budget_Nm`); return;
          }
          const k = Object.keys(o)[0], v = o[k];
          const [lo, hi] = k === "lambda" ? L.lambda_range : L.torque_budget_range;
          if (!isNum(v) || !(lo <= v && v <= hi)) e.push(`${where}.${k}: ${g(lo)}-${g(hi)}`);
          else if (seen.has(k + "|" + v)) e.push(`${where}: repeats an earlier objective`);
          else seen.add(k + "|" + v);
        });
      }
      const spans = get(search, "seed_half_spans_mm", []);
      const spansOk = Array.isArray(spans) && spans.length <= L.seed_spans_max && spans.every(isNum)
        && new Set(spans).size === spans.length && spans.every(x => HLO <= x && x <= HHI);
      if (!spansOk) e.push(`search.seed_half_spans_mm: up to ${L.seed_spans_max} distinct half-spans, ${g(HLO)}-${g(HHI)} mm`);
      const fams = get(search, "seed_families", []);
      if (!Array.isArray(fams) || !fams.every(f => typeof f === "string" && L.families.includes(f)) || new Set(fams).size !== fams.length)
        e.push(`search.seed_families: distinct names from ${L.families.join(", ")}`);
      else if (spansOk && (spans.length > 0) !== (fams.length > 0))
        e.push("search: seed half-spans and seed families go together (give both or neither)");
      for (const [k, [lo, hi], whole] of [["solves_per_lineage", L.solves_per_lineage, true], ["step_mm", L.step_range, false],
                                          ["min_chord_mm", L.min_chord_range, false]]) {
        const v = get(search, k, L.search_default[k]);
        if (!(whole ? isInt(v) : isNum(v)) || !(lo <= v && v <= hi)) e.push(`search.${k}: ${whole ? "whole number " : ""}${g(lo)}-${g(hi)}`);
      }
      if (typeof get(search, "decreasing", true) !== "boolean") e.push("search.decreasing: true or false");
      const ss = get(search, "span_step_mm", L.search_default.span_step_mm), [SLO, SHI] = L.span_step_range;
      if (!isNum(ss) || !(SLO <= ss && ss <= SHI)) e.push(`search.span_step_mm: ${g(SLO)}-${g(SHI)} (0 keeps the span fixed)`);
      const lim = get(search, "half_span_limits_mm", L.search_default.half_span_limits_mm);
      if (!Array.isArray(lim) || lim.length !== 2 || !lim.every(isNum) || !(lim[0] < lim[1]) || lim[0] < HLO || lim[1] > HHI)
        e.push(`search.half_span_limits_mm: [low, high] within ${g(HLO)}-${g(HHI)} mm`);
      else if (spansOk && spans.some(x => !(lim[0] <= x && x <= lim[1])))
        e.push("search.seed_half_spans_mm: every seed half-span must lie within search.half_span_limits_mm");
      return e;
    }

    function seedRuleErrors(chords, search, where) {
      const e = [], mn = get(search, "min_chord_mm", L.search_default.min_chord_mm);
      if (isNum(mn) && chords.some(c => 0 < c && c < mn))
        e.push(`${where}: to seed a search, positive chords must be at least search.min_chord_mm`);
      if (get(search, "decreasing", true) !== false && chords.slice(1).some((b, j) => b > chords[j]))
        e.push(`${where}: to seed a search with decreasing chords, chords must not increase toward the tip`);
      return e;
    }

    function caseCount(spec) {
      if (spec.kind === "evolutionary") {
        const searches = spec.models.length * spec.frequencies_hz.length * spec.search.objectives.length;
        const per = lineagesPerSearch(spec) * (1 + searchOf(spec).solves_per_lineage);
        return searches * (per + (get(spec, "structure") === "matched" ? 1 : 0));
      }
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
          if (models.includes("rigid") && (structure === "spanwise" || structure === "matched"))
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
        else if (kind === "evolutionary" && numerics.length !== 1) e.push("numerics: evolutionary searches use exactly one numerical setting");
      }
      const wings = get(spec, "wings"), sweep = get(spec, "sweep"), search = get(spec, "search");
      if (kind !== "evolutionary" && search !== null) e.push("search: only for evolutionary studies");
      if (kind === "evolutionary") {
        if (sweep !== null) e.push("sweep: only for geometry-sweep studies");
        e.push(...searchErrors(search));
        if (wings !== null && !isObj(wings)) e.push("wings: seed outlines as designs and/or from_atlas");
      }
      if (kind === "design-set" || (kind === "evolutionary" && isObj(wings))) {
        if (sweep !== null && kind === "design-set") e.push("sweep: only for geometry-sweep studies");
        if (kind === "design-set" && (!isObj(wings) || !(truthy(get(wings, "designs")) || truthy(get(wings, "from_atlas"))))) e.push("wings: give designs and/or from_atlas");
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
            const ce = validateChords(get(w, "chords_mm"), `${where}.chords_mm`);
            e.push(...ce);
            if (!ce.length && kind === "evolutionary" && isObj(search)) e.push(...seedRuleErrors(w.chords_mm, search, `${where}.chords_mm`));
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
      if (kind === "evolutionary" && !searchErrors(search).length && !e.length && !lineagesPerSearch(spec))
        e.push("search: give seed half-spans and families, or seed wings");
      const budget = get(spec, "budget");
      if (budget !== null && (!isObj(budget) || Object.keys(budget).some(k => k !== "max_cases") || !isInt(get(budget, "max_cases")) || budget.max_cases < 1))
        e.push('budget: {"max_cases": whole number >= 1}');
      if (has(spec, "parent") && (typeof spec.parent !== "string" || !ID_RE.test(spec.parent))) e.push("parent: the id of the study this one follows from");
      if (has(spec, "notes") && typeof spec.notes !== "string") e.push("notes: text");
      for (const k of ["title", "question"]) if (get(spec, k) === L.placeholders[k]) e.push(`${k}: replace the template text`);
      if (!e.length) {
        const n = caseCount(spec), cap = budget ? budget.max_cases : null;
        if (cap !== null && n > cap) e.push(`budget.max_cases: the spec expands to ${kind === "evolutionary" ? "up to " : ""}${n} cases, more than ${cap}`);
      }
      return e;
    }
    return { validate, caseCount, validateChords, numericsOf, lineagesPerSearch, searchOf };
  }

  const api = { make, pyRepr };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.WingSpec = api;
})(typeof window !== "undefined" ? window : globalThis);
