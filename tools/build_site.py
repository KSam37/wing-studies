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
sys.path.insert(0, str(ROOT))
import atlas_data  # noqa: E402
from wingstudy.studies import atlas as study_atlas  # noqa: E402

REPO_URL = "https://github.com/KSam37/wing-studies"
TEMPLATE = ROOT / "wingstudy" / "elastic_atlas.html"


def _js(obj) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False, allow_nan=False).replace("</", "<\\/")


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:
        return "local"


def landing_figure(D: dict, max_points: int = 9000) -> dict:
    """Data for the landing page's background figure: a sample of the atlas's thrust-torque
    points (verified / settled only) and the observed frontier."""
    C = D["cols"]
    good = {i for i, s in enumerate(D["statuses"]) if s in ("verified", "ok")}
    # The elastic campaigns share one root chord, stroke and speed; the older rigid catalog
    # spans much larger wings and would squash the figure, so it is left out of this plate.
    campaign = {i for i, st in enumerate(D["studies"]) if st["id"] != "catalog"}
    pts = [(q, t) for q, t, s, st in zip(C["Q"], C["T"], C["S"], C["s"])
           if s in good and st in campaign and q is not None and t is not None and q > 0 and t > 0]
    qs, ts = sorted(p[0] for p in pts), sorted(p[1] for p in pts)
    qmax, tmax = qs[int(.99 * (len(qs) - 1))], ts[int(.99 * (len(ts) - 1))]
    inside = [p for p in pts if p[0] <= qmax and p[1] <= tmax]
    step = max(1, len(inside) // max_points)
    sample = [[round(q, 4), round(t, 4)] for q, t in inside[::step]]
    frontier, best = [], -1.0
    for q, t in sorted(inside):
        if t > best:
            best = t
            frontier.append([round(q, 4), round(t, 4)])
    return {"scatter": sample, "frontier": frontier, "axes": [round(qmax, 3), round(tmax, 3)]}


def study_queue() -> list[dict]:
    """One row per study folder for the builder's queue view (valid specs only)."""
    from wingstudy.studies import spec as S
    rows = []
    for folder in sorted((ROOT / "studies").glob("*/")):
        try:
            spec = S.read_json(folder / "spec.json")
        except (OSError, ValueError):
            continue
        if S.validate(spec):
            continue
        status = S.read_json(folder / "status.json") if (folder / "status.json").exists() else {}
        counts = None
        if (folder / "results.json").exists():
            counts = S.read_json(folder / "results.json").get("counts")
        rows.append({"id": spec["id"], "title": spec["title"], "author": spec["author"], "kind": spec["kind"],
                     "parent": spec.get("parent"), "cases": S.case_count(spec), "state": status.get("state", "proposed"),
                     "done": status.get("done"), "counts": counts})
    rows.sort(key=lambda r: r["id"], reverse=True)
    return rows


def build(out: Path) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    commit = _commit()
    D = atlas_data.assemble(ROOT / "atlas" / "data")
    dropped = atlas_data.drop_models(D)
    if dropped:
        print(f"left out {dropped} rows of {', '.join(atlas_data.DROPPED_MODELS)} (not a standard sheet)")
    atlas_data.attach_evolution(D, ROOT / "atlas" / "media")
    atlas_data.attach_run_dates(D)
    planned = study_atlas.completed(ROOT / "studies")
    if planned:
        print(f"planned studies: {len(planned)} ({study_atlas.merge(D, planned)} map rows)")
    fav = ROOT / "atlas" / "favorites.json"
    D["favorites"] = json.loads(fav.read_text(encoding="utf-8")).get("favorites", []) if fav.exists() else []
    # wingstudy.refine_top runs, one folder each under atlas/refine-top/: stage1.json (tripled chord stations,
    # 21 x 4), stage2.json (21 x 12 and smooth curve), baseline.json (the starting wings on 21 x 12)
    runs = sorted(d for d in (ROOT / "atlas" / "refine-top").glob("*") if d.is_dir())
    for key, name in (("refine_top", "stage1"), ("refine_curve", "stage2"), ("refine_baseline", "baseline")):
        parts = [json.loads((d / f"{name}.json").read_text(encoding="utf-8")) for d in runs if (d / f"{name}.json").exists()]
        if parts:
            D[key] = {**parts[0], "runs": [d.name for d in runs], "seeds": [s for x in parts for s in x["seeds"]]}
    n = study_atlas.merge_refinement(D, [D.get("refine_top"), D.get("refine_curve")])
    if n:
        print(f"optimized shapes: {n} map rows")
    ml = ROOT / "atlas" / "mesh-ladder.json"        # wingstudy.mesh_ladder output: the recommended wings on finer meshes
    if ml.exists():
        D["mesh_ladder"] = json.loads(ml.read_text(encoding="utf-8"))
    gifs = ROOT / "atlas" / "media" / "refine-top"   # wingstudy.refine_top --gif output
    D["refine_gifs"] = sorted(g.stem for g in gifs.glob("*.gif")) if gifs.exists() else []
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

    site = {"wings": len(D["cols"]["s"]) + sum(1 for p in D.get("span_comparisons", [])
                                               for k in ("baseline", "spanwise") if isinstance(p.get(k), dict)
                                               and p[k].get("mean_thrust_N") is not None),
            "studies": len(D["studies"]), "top": len(D["winners"]),
            "span_pairs": len(D.get("span_comparisons", [])), **landing_figure(D)}
    landing = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    landing = (landing.replace("/*__SITE_DATA__*/", _js(site)).replace("__REPO__", REPO_URL)
               .replace("__BUILT__", f"{D['built']} ({commit})"))
    (out / "index.html").write_text(landing, encoding="utf-8", newline="\n")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    # study builder and queue (site/new): validator constants come from spec.py, never a second copy
    from wingstudy.studies import run as study_run, spec as study_spec
    builder = {"limits": study_spec.limits(), "seconds": study_run.SECONDS, "repo": REPO_URL,
               "studies": study_queue(), "built": D["built"]}
    (out / "new").mkdir()
    page = (ROOT / "site" / "new" / "index.html").read_text(encoding="utf-8").replace("/*__BUILDER_DATA__*/", _js(builder))
    (out / "new" / "index.html").write_text(page, encoding="utf-8", newline="\n")
    shutil.copy2(ROOT / "site" / "new" / "spec.js", out / "new" / "spec.js")

    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"built {out} ({size / 1e6:.1f} MB): {len(D['cols']['s']):,} atlas rows, build {D['build_id']}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path, default=ROOT / "_site")
    build(ap.parse_args(argv).out)


if __name__ == "__main__":
    main()
