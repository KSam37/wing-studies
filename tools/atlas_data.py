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
