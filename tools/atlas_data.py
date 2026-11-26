"""Atlas data in the repository: split from a built atlas, and reassembled for the site.

The atlas page used to carry all of its data inside one 12 MB index.html, so every
publish rewrote one file and collaborators always conflicted. The data now lives as
small JSON files under atlas/data/:

    meta.json                study list, models, frequencies, winners, refined shapes, ...
    rows/<study-id>.json     column-packed map rows for one study (row order preserved)
    catalog.json             rigid-catalog outlines and cohorts
    span_comparisons.json    matched chordwise / spanwise reruns

    python tools/atlas_data.py split PATH/TO/index.html atlas/data   # one-time import
    python tools/atlas_data.py check PATH/TO/index.html atlas/data   # reassembled == original?

`assemble()` rebuilds exactly the object the atlas page expects.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROW_FILE_KEYS = ("s", "m", "f", "T", "Q", "H", "W", "S", "C", "src", "k", "obj")
CHORDS_PER_ROW = 8
VOLATILE = ("built", "build_id")  # set by each site build


# When the imported studies were run, for the atlas timeline. The campaign databases are not in
# the repository, so their dates come from what is recorded elsewhere: the atlas that first held
# them was built 2026-11-15 (a Sunday, the end of the weekend campaign) and the last rigid study
# before them is dated 2026-11-09. Correct these if a better record turns up. Rigid-catalog rows
# carry their own study timestamps (catalog.json); planned studies use results.json "completed".
RUN_DATES = {
    "rod": ("2026-11-15T12:00:00", "on or before 15 Nov 2026; exact date not recorded"),
    "weekend": ("2026-11-15T12:00:00", "weekend of 14-15 Nov 2026; exact date not recorded"),
    "sweep": ("2026-11-15T12:00:00", "on or before 15 Nov 2026; exact date not recorded"),
    "spanfree": ("2026-11-15T12:00:00", "on or before 15 Nov 2026; exact date not recorded"),
}
SPAN_COMPARISON_DATE = ("2026-11-18T12:00:00", "matched spanwise reruns, 17-18 Nov 2026")


def attach_run_dates(D: dict) -> None:
    """Give each imported study a run_date (ISO, local time) for the atlas timeline."""
    for st in D["studies"]:
        if st["id"] in RUN_DATES and "run_date" not in st:
            st["run_date"], st["run_date_note"] = RUN_DATES[st["id"]]
    D["span_comparison_date"] = list(SPAN_COMPARISON_DATE)


def read_embedded(html_path: Path) -> dict:
    text = html_path.read_text(encoding="utf-8")
    m = re.search(r'<script[^>]*id="atlas-data"[^>]*>(.*?)</script>', text, re.S)
    if not m:
        raise SystemExit(f"no embedded atlas data in {html_path}")
    return json.loads(m.group(1))


def _dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False) + "\n",
                    encoding="utf-8", newline="\n")


def split(D: dict, out: Path) -> None:
    cols = D["cols"]
    n = len(cols["s"])
    # Rows are contiguous per study; keep the order so row indices (winners, refined, catalog.first) stay valid.
    runs = []
    for i, s in enumerate(cols["s"]):
        if not runs or runs[-1][0] != s:
            runs.append([s, i])
    if len({r[0] for r in runs}) != len(runs):
        raise SystemExit("study rows are not contiguous; refusing to split")
    order = []
    for k, (s, start) in enumerate(runs):
        end = runs[k + 1][1] if k + 1 < len(runs) else n
        sid = D["studies"][s]["id"]
        chunk = {key: cols[key][start:end] for key in ROW_FILE_KEYS if key != "C"}
        chunk["C"] = cols["C"][start * CHORDS_PER_ROW:end * CHORDS_PER_ROW]
        _dump(out / "rows" / f"{sid}.json", {"study": sid, "start": start, "count": end - start, "cols": chunk})
        order.append(sid)
    meta = {k: v for k, v in D.items() if k not in ("cols", "catalog", "span_comparisons")}
    meta["row_files"] = order
    meta["col_keys"] = list(cols.keys())
    _dump(out / "meta.json", meta)
    _dump(out / "catalog.json", D["catalog"])
    _dump(out / "span_comparisons.json", D.get("span_comparisons", []))


def assemble(data: Path) -> dict:
    meta = json.loads((data / "meta.json").read_text(encoding="utf-8"))
    order, keys = meta.pop("row_files"), meta.pop("col_keys")
    cols = {k: [] for k in keys}
    for sid in order:
        chunk = json.loads((data / "rows" / f"{sid}.json").read_text(encoding="utf-8"))
        if chunk["start"] != len(cols["s"]):
            raise SystemExit(f"rows/{sid}.json starts at {chunk['start']}, expected {len(cols['s'])}")
        for k in keys:
            cols[k].extend(chunk["cols"][k])
    D = dict(meta)
    D["cols"] = cols
    D["catalog"] = json.loads((data / "catalog.json").read_text(encoding="utf-8"))
    D["span_comparisons"] = json.loads((data / "span_comparisons.json").read_text(encoding="utf-8"))
    # restore the original key order so the embedded JSON reads the same as before
    first = ["built", "build_id", "torque_limit", "studies", "catalog", "models", "freqs", "statuses", "unique", "cols"]
    return {**{k: D[k] for k in first if k in D}, **{k: v for k, v in D.items() if k not in first}}


# Materials left out of the published atlas. 0.2 mm is not a standard sheet size; its rows stay
# in atlas/data (generated, never hand-edited) and are dropped when the site is built.
DROPPED_MODELS = ("t0.20",)


def drop_models(D: dict, ids=DROPPED_MODELS) -> int:
    """Remove every row, winner and matched comparison of the given base materials, in place,
    renumbering the rows and models the rest of the atlas refers to. Run straight after
    assemble (before attach_evolution and the planned-study merge). Returns rows removed."""
    drop_m = {i for i, m in enumerate(D["models"]) if m["id"].split(":")[-1] in ids}
    if not drop_m:
        return 0
    cols = D["cols"]
    n = len(cols["s"])
    keep = [cols["m"][i] not in drop_m for i in range(n)]
    new_row, j = [None] * n, 0
    for i in range(n):
        if keep[i]:
            new_row[i] = j
            j += 1
    new_model, k = {}, 0
    for i in range(len(D["models"])):
        if i not in drop_m:
            new_model[i] = k
            k += 1
    for c, v in cols.items():
        if c == "C":
            cols[c] = [x for i in range(n) if keep[i] for x in v[8 * i:8 * i + 8]]
        elif c == "m":
            cols[c] = [new_model[x] for i, x in enumerate(v) if keep[i]]
        else:
            cols[c] = [x for i, x in enumerate(v) if keep[i]]
    D["models"] = [m for i, m in enumerate(D["models"]) if i not in drop_m]

    def remap(r):
        return None if r is None or not 0 <= r < n else new_row[r]
    cat = D.get("catalog") or {}
    for key in ("first", "end"):
        if key in cat:
            cat[key] = sum(keep[:cat[key]])
    for name in ("ranges", "row_notes", "row_search"):
        if isinstance(D.get(name), dict):
            D[name] = {str(remap(int(r))): v for r, v in D[name].items() if remap(int(r)) is not None}
    D["winners"] = [w for w in D.get("winners", []) if w.get("model") not in ids]
    for w in D["winners"]:
        if w.get("row") is not None:
            w["row"] = remap(w["row"])
    D["refined"] = [x for x in D.get("refined", []) if x.get("model") not in ids]
    D["span_comparisons"] = [p for p in D.get("span_comparisons", []) if (p["source"].get("source_model") or p["source"].get("model")) not in ids]
    for p in D["span_comparisons"]:
        if p["source"].get("row") is not None:
            p["source"]["row"] = remap(p["source"]["row"])
    if "unique" in D:
        D["unique"] = len(set(cols["k"]))
    return n - j


def attach_evolution(D: dict, media: Path) -> int:
    """Attach each search-found winner's evolution animation (media/evolution/<study>/index.json,
    written by `python -m wingstudy.elastic_evolution CAMPAIGN --atlas-winners STUDY`)."""
    n = 0
    for index_path in sorted((media / "evolution").glob("*/index.json")):
        study, index = index_path.parent.name, json.loads(index_path.read_text(encoding="utf-8"))
        for w in D.get("winners", []):
            e = index.get((w.get("key") or "")[:16])
            if w.get("study") == study and e and (media / e["gif"]).exists():
                w["evolution"] = e
                w["media"] = {**(w.get("media") or {}), "evolution": e["gif"]}
                n += 1
    return n


def check(original: dict, rebuilt: dict) -> list[str]:
    a = {k: v for k, v in original.items() if k not in VOLATILE}
    b = {k: v for k, v in rebuilt.items() if k not in VOLATILE}
    problems = []
    for k in sorted(set(a) | set(b)):
        if a.get(k) != b.get(k):
            problems.append(k)
    return problems


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["split", "check"])
    ap.add_argument("html", type=Path)
    ap.add_argument("data", type=Path)
    a = ap.parse_args(argv)
    D = read_embedded(a.html)
    if a.command == "split":
        split(D, a.data)
    bad = check(D, assemble(a.data))
    if bad:
        print("MISMATCH in:", ", ".join(bad))
        return 1
    print(f"OK: reassembled data equals the original ({len(D['cols']['s']):,} rows, "
          f"{len(D.get('span_comparisons', []))} span comparisons)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
