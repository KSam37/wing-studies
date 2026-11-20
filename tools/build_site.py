"""Build the FAAV Wing Studies website into _site/ (what GitHub Pages serves).

    python tools/build_site.py            # -> _site/index.html, _site/atlas/index.html, media, files

The atlas page is a build artifact: its data comes from atlas/data/*.json, so nobody
edits (or merge-conflicts on) a 12 MB HTML file. The same output also works offline:
open _site/atlas/index.html directly, no server needed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import atlas_data  # noqa: E402

REPO_URL = "https://github.com/KSam37/wing-studies"
TEMPLATE = ROOT / "WingStudy" / "elastic_atlas.html"


def _js(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False).replace("</", "<\\/")


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return "local"


def build(out: Path) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    commit = _commit()
    D = atlas_data.assemble(ROOT / "atlas" / "data")
    D["built"] = now.strftime("%Y-%m-%d %H:%M UTC")
    D["build_id"] = f"{now:%Y%m%d%H%M%S}-{commit}"

    if out.exists():
        shutil.rmtree(out)
    (out / "atlas").mkdir(parents=True)

    page = TEMPLATE.read_text(encoding="utf-8").replace("/*__ATLAS_DATA__*/", _js(D))
    (out / "atlas" / "index.html").write_text(page, encoding="utf-8", newline="\n")
    for sub in ("media", "files"):
        src = ROOT / "atlas" / sub
        if src.exists():
            shutil.copytree(src, out / "atlas" / sub)

    # Landing page: headline numbers and a few real top-performing outlines for the background.
    winners = [w for w in D["winners"] if w.get("chords") and w.get("half_span")]
    rigid = {m["id"]: m["thickness"] is None for m in D["models"]}
    bg = []
    for w in sorted(winners, key=lambda w: -w["thrust"]):
        key = tuple(round(c) for c in w["chords"])
        if any(tuple(round(c) for c in b["chords"]) == key for b in bg):
            continue
        bg.append({"chords": w["chords"], "half_span": w["half_span"], "flex": not rigid.get(w["model"], False)})
    site = {"wings": len(D["cols"]["s"]) + sum(1 for p in D.get("span_comparisons", [])
                                               for k in ("baseline", "spanwise") if isinstance(p.get(k), dict)
                                               and p[k].get("mean_thrust_N") is not None),
            "studies": len(D["studies"]), "top": len(D["winners"]),
            "span_pairs": len(D.get("span_comparisons", [])), "wings_bg": bg[:12]}
    landing = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    landing = (landing.replace("/*__SITE_DATA__*/", _js(site)).replace("__REPO__", REPO_URL)
               .replace("__BUILT__", f"{D['built']} ({commit})"))
    (out / "index.html").write_text(landing, encoding="utf-8", newline="\n")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"built {out} ({size / 1e6:.1f} MB): {len(D['cols']['s']):,} atlas rows, build {D['build_id']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "_site")
    build(ap.parse_args(argv).out)


if __name__ == "__main__":
    main()
