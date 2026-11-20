"""Study specs: the contract shared by the CLI, the website builder and AI agents.

A study lives in ``studies/<id>/``:

    spec.json      what was asked (immutable once run)
    status.json    proposed | running | complete | failed, with counts and dates
    results.json   compact per-case results plus a replay manifest for every case

``schema/study-spec.schema.json`` describes the same rules for other tools; this module
is the authoritative validator (standard library only, so CI can run it without the
solver). ``tests/test_studies.py`` checks that the two agree.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUDIES = ROOT / "studies"
SPEC_SCHEMA = "wingstudy/study-spec@1"
RESULTS_SCHEMA = "wingstudy/study-results@1"

KINDS = ("design-set", "geometry-sweep", "matched-comparison")
STRUCTURES = ("chordwise", "spanwise")
STATES = ("proposed", "running", "complete", "failed")

# Material models, as in the atlas. Sheets are plain-weave carbon fibre; the rod is the
# 5/3 mm carbon tube bolted along the leading edge.
MODELS = {
    "rigid": {"label": "Rigid", "thickness_mm": None, "rod": False},
    "t1.00": {"label": "1.0 mm", "thickness_mm": 1.0, "rod": False},
    "t0.50": {"label": "0.5 mm (no rod)", "thickness_mm": 0.5, "rod": False},
    "t0.25": {"label": "0.25 mm (no rod)", "thickness_mm": 0.25, "rod": False},
    "t0.20": {"label": "0.2 mm (no rod)", "thickness_mm": 0.2, "rod": False},
    "t0.50r": {"label": "0.5 mm + rod", "thickness_mm": 0.5, "rod": True},
    "t0.25r": {"label": "0.25 mm + rod", "thickness_mm": 0.25, "rod": True},
}
NODES = 8                       # chord stations per wing, root to tip (as in every atlas study)
NUMERICS_DEFAULT = {"span_panels": 8, "chord_panels": 4, "steps_per_cycle": 50, "cycles": 4}
NUMERICS_RANGES = {"span_panels": (2, 32), "chord_panels": (2, 16), "steps_per_cycle": (20, 400), "cycles": (2, 10)}
FREQ_RANGE = (0.25, 3.0)
HALF_SPAN_RANGE = (100.0, 800.0)
CHORD_RANGE = (5.0, 400.0)
SWEEP_COUNT = (1, 4096)
ID_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9]+(?:-[a-z0-9]+)*$")
KEY_RE = re.compile(r"^[0-9a-f]{24}$")
TOP_KEYS = {"schema", "id", "title", "author", "question", "kind", "structure", "models", "frequencies_hz",
            "numerics", "wings", "sweep", "budget", "parent", "notes"}
REQUIRED = ("schema", "id", "title", "author", "question", "kind", "models", "frequencies_hz")


# ----------------------------------------------------------------------------- io
def study_dir(study_id: str) -> Path:
    return STUDIES / study_id


def read_json(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=1, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(path)


def load(study_id_or_path) -> dict:
    p = Path(study_id_or_path)
    if p.suffix != ".json":
        p = (p if p.is_dir() else study_dir(str(study_id_or_path))) / "spec.json"
    return read_json(p)


def spec_sha256(spec: dict) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# ----------------------------------------------------------------------------- validation
def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and v == v and abs(v) != float("inf")


def _int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def validate_chords(chords, where: str) -> list[str]:
    e = []
    if not isinstance(chords, list) or len(chords) != NODES or not all(_num(c) for c in chords):
        return [f"{where}: {NODES} chord lengths in mm, root to tip"]
    if any(c < 0 for c in chords):
        return [f"{where}: chords cannot be negative"]
    active = next((j for j, c in enumerate(chords) if c == 0), len(chords))   # leading positive stations
    if any(c > 0 for c in chords[active:]):
        e.append(f"{where}: zero chords may only form a tip suffix")
    if active < 2:
        e.append(f"{where}: at least the root and one more station must be positive")
    for c in chords[:active]:
        if not CHORD_RANGE[0] <= c <= CHORD_RANGE[1]:
            e.append(f"{where}: positive chords must be {CHORD_RANGE[0]:g}-{CHORD_RANGE[1]:g} mm")
            break
    return e


def validate(spec: dict) -> list[str]:
    """Every problem with a spec, as readable 'field: message' strings (empty = valid)."""
    if not isinstance(spec, dict):
        return ["spec: must be a JSON object"]
    e = [f"{k}: required" for k in REQUIRED if k not in spec]
    e += [f"{k}: unknown field" for k in spec if k not in TOP_KEYS]
    if spec.get("schema") not in (None, SPEC_SCHEMA):
        e.append(f"schema: must be {SPEC_SCHEMA!r}")
    sid = spec.get("id")
    if sid is not None and (not isinstance(sid, str) or not ID_RE.match(sid) or len(sid) > 80):
        e.append("id: YYYY-MM-DD-short-name, lower case letters, digits and hyphens, at most 80 characters")
    for k, lo, hi in (("title", 3, 120), ("author", 1, 60), ("question", 3, 600)):
        v = spec.get(k)
        if v is not None and (not isinstance(v, str) or not lo <= len(v.strip()) <= hi):
            e.append(f"{k}: text, {lo}-{hi} characters")
    kind = spec.get("kind")
    if kind is not None and kind not in KINDS:
        e.append(f"kind: one of {', '.join(KINDS)}")
    structure = spec.get("structure", "chordwise")
    if structure not in STRUCTURES:
        e.append(f"structure: one of {', '.join(STRUCTURES)}")
    models = spec.get("models")
    if models is not None:
        if not isinstance(models, list) or not models or len(set(map(str, models))) != len(models):
            e.append("models: a non-empty list without repeats")
        else:
            bad = [m for m in models if m not in MODELS]
            if bad:
                e.append(f"models: unknown {bad}; choose from {', '.join(MODELS)}")
            if "rigid" in models and (kind == "matched-comparison" or structure == "spanwise"):
                e.append("models: rigid wings have no structure to bend; remove 'rigid' for spanwise or matched studies")
    freqs = spec.get("frequencies_hz")
    if freqs is not None:
        if (not isinstance(freqs, list) or not freqs or not all(_num(f) for f in freqs)
                or len(set(freqs)) != len(freqs)):
            e.append("frequencies_hz: a non-empty list of distinct numbers")
        elif not all(FREQ_RANGE[0] <= f <= FREQ_RANGE[1] for f in freqs):
            e.append(f"frequencies_hz: each {FREQ_RANGE[0]:g}-{FREQ_RANGE[1]:g} Hz")
    numerics = spec.get("numerics", [NUMERICS_DEFAULT])
    if not isinstance(numerics, list) or not numerics:
        e.append("numerics: a non-empty list of numerical settings")
    else:
        for j, n in enumerate(numerics):
            if not isinstance(n, dict):
                e.append(f"numerics[{j}]: an object"); continue
            for k in n:
                if k not in NUMERICS_RANGES:
                    e.append(f"numerics[{j}].{k}: unknown setting")
            for k, (lo, hi) in NUMERICS_RANGES.items():
                v = n.get(k, NUMERICS_DEFAULT[k])
                if not _int(v) or not lo <= v <= hi:
                    e.append(f"numerics[{j}].{k}: whole number {lo}-{hi}")
        if len({json.dumps(numerics_of(n), sort_keys=True) for n in numerics if isinstance(n, dict)}) != len(numerics):
            e.append("numerics: settings repeat")
    wings, sweep = spec.get("wings"), spec.get("sweep")
    if kind in ("design-set", "matched-comparison"):
        if sweep is not None:
            e.append("sweep: only for geometry-sweep studies")
        if not isinstance(wings, dict) or not (wings.get("designs") or wings.get("from_atlas")):
            e.append("wings: give designs and/or from_atlas")
        else:
            for k in wings:
                if k not in ("designs", "from_atlas"):
                    e.append(f"wings.{k}: unknown field")
            names = set()
            for j, w in enumerate(wings.get("designs") or []):
                where = f"wings.designs[{j}]"
                if not isinstance(w, dict):
                    e.append(f"{where}: an object"); continue
                for k in w:
                    if k not in ("name", "chords_mm", "half_span_mm"):
                        e.append(f"{where}.{k}: unknown field")
                name = w.get("name", f"wing {j + 1}")
                if not isinstance(name, str) or not 1 <= len(name) <= 60 or name in names:
                    e.append(f"{where}.name: unique text, 1-60 characters")
                names.add(name)
                e += validate_chords(w.get("chords_mm"), f"{where}.chords_mm")
                hs = w.get("half_span_mm")
                if not _num(hs) or not HALF_SPAN_RANGE[0] <= hs <= HALF_SPAN_RANGE[1]:
                    e.append(f"{where}.half_span_mm: {HALF_SPAN_RANGE[0]:g}-{HALF_SPAN_RANGE[1]:g} mm")
            keys = wings.get("from_atlas") or []
            if not isinstance(keys, list) or not all(isinstance(k, str) and KEY_RE.match(k) for k in keys):
                e.append("wings.from_atlas: a list of 24-character atlas design keys")
            elif len(set(keys)) != len(keys):
                e.append("wings.from_atlas: keys repeat")
    elif kind == "geometry-sweep":
        if wings is not None:
            e.append("wings: not used by geometry-sweep studies (use sweep)")
        if not isinstance(sweep, dict):
            e.append("sweep: required for geometry-sweep studies")
        else:
            for k in sweep:
                if k not in ("count", "half_span_mm", "seed"):
                    e.append(f"sweep.{k}: unknown field")
            if not _int(sweep.get("count")) or not SWEEP_COUNT[0] <= sweep["count"] <= SWEEP_COUNT[1]:
                e.append(f"sweep.count: whole number {SWEEP_COUNT[0]}-{SWEEP_COUNT[1]}")
            hs = sweep.get("half_span_mm")
            if (not isinstance(hs, list) or len(hs) != 2 or not all(_num(x) for x in hs) or not hs[0] < hs[1]
                    or hs[0] < HALF_SPAN_RANGE[0] or hs[1] > HALF_SPAN_RANGE[1]):
                e.append(f"sweep.half_span_mm: [low, high] within {HALF_SPAN_RANGE[0]:g}-{HALF_SPAN_RANGE[1]:g} mm")
            if "seed" in sweep and not (_int(sweep["seed"]) and sweep["seed"] >= 0):
                e.append("sweep.seed: whole number >= 0")
    budget = spec.get("budget")
    if budget is not None:
        if not isinstance(budget, dict) or set(budget) - {"max_cases"} or not _int(budget.get("max_cases")) or budget["max_cases"] < 1:
            e.append("budget: {\"max_cases\": whole number >= 1}")
    if "parent" in spec and (not isinstance(spec["parent"], str) or not ID_RE.match(spec["parent"])):
        e.append("parent: the id of the study this one follows from")
    if "notes" in spec and not isinstance(spec["notes"], str):
        e.append("notes: text")
    for k in ("title", "question"):
        if spec.get(k) == PLACEHOLDERS[k]:
            e.append(f"{k}: replace the template text")
    if not e:
        n = case_count(spec)
        cap = (budget or {}).get("max_cases")
        if cap is not None and n > cap:
            e.append(f"budget.max_cases: the spec expands to {n} cases, more than {cap}")
    return e


# ----------------------------------------------------------------------------- expansion
def numerics_of(n: dict) -> dict:
    return {k: n.get(k, v) for k, v in NUMERICS_DEFAULT.items()}


def atlas_wings(keys: list[str], data_dir: Path | None = None) -> list[dict]:
    """Outlines of atlas designs by key (from atlas/data/rows/*.json)."""
    data_dir = Path(data_dir or ROOT / "atlas" / "data")
    want, found = set(keys), {}
    for p in sorted((data_dir / "rows").glob("*.json")):
        cols = read_json(p)["cols"]
        for r, k in enumerate(cols["k"]):
            if k in want and k not in found:
                found[k] = {"name": f"atlas {k[:8]}", "chords_mm": cols["C"][8 * r:8 * r + 8],
                            "half_span_mm": cols["H"][r], "atlas_key": k}
    missing = [k for k in keys if k not in found]
    if missing:
        raise KeyError(f"atlas keys not found: {', '.join(missing)}")
    return [found[k] for k in keys]


def wings_of(spec: dict) -> list[dict]:
    if spec["kind"] == "geometry-sweep":
        return sweep_wings(spec["sweep"])
    out = [{"name": w.get("name", f"wing {j + 1}"), "chords_mm": list(w["chords_mm"]), "half_span_mm": w["half_span_mm"]}
           for j, w in enumerate(spec["wings"].get("designs") or [])]
    if spec["wings"].get("from_atlas"):
        out += atlas_wings(spec["wings"]["from_atlas"])
    return out


def sweep_wings(sweep: dict) -> list[dict]:
    """Scrambled-Sobol outlines with the campaigns' rules: 200 mm root, each station 0.3-1.0
    of the previous one, chords under 10 mm become a zero tip suffix; continuous half-span.
    Same generator as the geometric sweep campaign (elastic_campaign.sobol_shapes)."""
    from scipy.stats import qmc          # solver environment only
    lo, hi = sweep["half_span_mm"]
    sob = qmc.Sobol(d=NODES, scramble=True, seed=sweep.get("seed", 0))
    m = max(1, (max(sweep["count"], 1) - 1).bit_length())
    out = []
    for i, row in enumerate(sob.random_base2(m)[:sweep["count"]]):
        span = round(lo + row[0] * (hi - lo), 0)
        chords = [200.0]
        for x in row[1:]:
            chords.append(chords[-1] * (0.3 + 0.7 * x))
        fixed, zero = [], False
        for j, c in enumerate(chords):
            if zero or (j >= 2 and c < 10.0):
                zero = True
                fixed.append(0.0)
            else:
                fixed.append(round(max(c, 10.0), 1))
        out.append({"name": f"S{i:04d}", "chords_mm": fixed, "half_span_mm": span})
    return out


def case_count(spec: dict) -> int:
    n_w = (spec["sweep"]["count"] if spec["kind"] == "geometry-sweep"
           else len(spec["wings"].get("designs") or []) + len(spec["wings"].get("from_atlas") or []))
    return n_w * len(spec["models"]) * len(spec["frequencies_hz"]) * len(spec.get("numerics", [NUMERICS_DEFAULT]))


def expand(spec: dict, wings: list[dict] | None = None) -> list[dict]:
    """Every case of the study, in a stable order: wing, model, frequency, numerics."""
    wings = wings_of(spec) if wings is None else wings
    structure = "matched" if spec["kind"] == "matched-comparison" else spec.get("structure", "chordwise")
    cases = []
    for w in wings:
        for m in spec["models"]:
            for f in spec["frequencies_hz"]:
                for n in spec.get("numerics", [NUMERICS_DEFAULT]):
                    cases.append({"case_id": f"c{len(cases) + 1:04d}", "wing": w["name"], "model": m,
                                  "structure": structure, "freq": float(f), "chords_mm": list(w["chords_mm"]),
                                  "half_span_mm": float(w["half_span_mm"]), "numerics": numerics_of(n),
                                  **({"atlas_key": w["atlas_key"]} if w.get("atlas_key") else {})})
    return cases


# ----------------------------------------------------------------------------- templates
PLACEHOLDERS = {"title": "Describe the study in a short title", "question": "What should this study answer?"}


def template(study_id: str, kind: str = "design-set", author: str = "") -> dict:
    """A starting spec. Its title and question are placeholders that validate() rejects until replaced."""
    base = {"schema": SPEC_SCHEMA, "id": study_id, "title": PLACEHOLDERS["title"],
            "author": author or "your-name", "question": PLACEHOLDERS["question"], "kind": kind}
    if kind == "design-set":
        return {**base, "structure": "chordwise", "models": ["t0.50r"], "frequencies_hz": [1.0],
                "numerics": [dict(NUMERICS_DEFAULT)],
                "wings": {"designs": [{"name": "taper", "chords_mm": [200, 150, 110, 80, 55, 35, 20, 10], "half_span_mm": 340}]},
                "budget": {"max_cases": 20}}
    if kind == "geometry-sweep":
        return {**base, "structure": "chordwise", "models": ["t0.50r"], "frequencies_hz": [1.0],
                "numerics": [dict(NUMERICS_DEFAULT)], "sweep": {"count": 16, "half_span_mm": [280, 400], "seed": 1},
                "budget": {"max_cases": 64}}
    if kind == "matched-comparison":
        return {**base, "models": ["t0.50"], "frequencies_hz": [1.0], "numerics": [dict(NUMERICS_DEFAULT)],
                "wings": {"designs": [{"name": "taper", "chords_mm": [200, 150, 110, 80, 55, 35, 20, 10], "half_span_mm": 340}]},
                "budget": {"max_cases": 10}}
    raise ValueError(f"kind: one of {', '.join(KINDS)}")
