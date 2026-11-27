"""Ptera animations for every Top-tab performer (FAAV wing, every frequency, one-sheet and free-span).

    python -m wingstudy.top_media [SUMMARY...] [--freqs 0.75 1 1.25] [--workers 2] [--dry]

Two kinds of wing:
  study picks  the best verified FAAV wing at or below each torque budget in refine_top.LEVELS, and the best
               within one 400 mm sheet (refine_top.pick_seeds on the whole atlas), as solved by the studies:
               8 straight-segment chords, 8 x 4 panels, 50 steps per cycle, 4 cycles.
  optimized    every final of the given second-stage refine_top summaries (default atlas/refine-top/*/stage2.json):
               PCHIP outline, 21 x 12 panels.
The campaign databases are not needed: each case is rebuilt from its outline and numerics, solved with the
verification ladder to recover the time step and added-mass factor, checked against the stored thrust, then
run once more with Ptera's animation output. Media go to atlas/media/top/<key[:16]>/ (main, front, top, poster
.webp) and are listed in atlas/top-media.json, which tools/build_site.py merges into the atlas. Existing renders
are skipped, so a rerun only renders what is new.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import shutil
import time
import warnings
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from . import elastic_refine as ER
from . import refine_top as RT
from .studies import spec as S

ATLAS = S.ROOT / "atlas"
DEST = ATLAS / "media" / "top"
MANIFEST = ATLAS / "top-media.json"
HQ_OPTIONS = {"window_size": (1600, 1200), "quality": 90.0, "speed": 1.0}   # as elastic_atlas.render_hq
FREQS = (0.75, 1.0, 1.25)


def coarse_numerics(freq):
    return {"span_panels": 8, "chord_panels": 4, "steps_per_cycle": 50, "cycles": 4, "dt_refinements": [1, 2], "freq": freq}


def tasks(summaries: list[Path], freqs) -> list[dict]:
    out, seen = [], set()
    for f in freqs:
        for s in RT.pick_seeds(RT.atlas_cases(f), RT.LEVELS, freq=f):
            c = s["case"]
            if c["key"][:16] in seen:
                continue
            seen.add(c["key"][:16])
            ch = [x for x in c["chords_mm"] if x > 0]
            out.append({"key": c["key"][:16], "label": s["id"], "kind": "pick", "freq": f,
                        "chords_m": [x / 1000 for x in ch], "span_m": RT.effective_span_mm(c) / 1000,
                        "numerics": coarse_numerics(f), "thrust": c["thrust_N"], "torque": c["torque_Nm"]})
    for p in summaries:
        for x in S.read_json(p)["seeds"]:
            fin, num = x.get("final") or {}, x.get("numerics") or {}
            if not fin.get("ctrl") or fin.get("thrust") is None:
                continue
            ctrl, span = [round(v, 5) for v in fin["ctrl"]], round(fin["span"], 5)
            k = ER.key_of("t0.50", ctrl, span, num)[:16]
            if k in seen:
                continue
            seen.add(k)
            out.append({"key": k, "label": x["id"] + " optimized", "kind": "optimized", "freq": num.get("freq", 1.0),
                        "chords_m": list(ER.chords_from_ctrl(ctrl, num["stations"], num.get("param"))), "span_m": span,
                        "numerics": {**num, "freq": num.get("freq", 1.0)}, "thrust": fin["thrust"], "torque": fin["torque"]})
    return out


def render(t: dict) -> dict:
    warnings.filterwarnings("ignore")
    from PIL import Image
    from . import cases as _cases
    from . import elastic
    from . import elastic_runner as R
    t0 = time.time()
    dest = DEST / t["key"]
    template, settings = _cases.load_case(7657)
    case = R.sections_case(template, settings, t["chords_m"], t["span_m"], t["label"])
    num = t["numerics"]
    case["frequency_hz"] = num["freq"]
    ov = {"dt_s": 1.0 / (num["steps_per_cycle"] * num["freq"]), "cycles": num["cycles"],
          "span_panels": num["span_panels"], "chord_panels": num["chord_panels"]}
    spec = {"stiffness_model": "plate", "thickness_m": 0.5e-3, "material": ER.MATERIAL, "rod": {}}
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        v = R.run_verified(case, settings, elastic.ElasticConfig.from_dict(spec), ov, dt_refinements=tuple(num["dt_refinements"]))
    if v.get("status") not in ("verified", "ok") or v.get("mean_thrust_N") is None:
        return {**t, "error": f"verification run {v.get('status')}: {v.get('error')}"}
    dev = 100 * (v["mean_thrust_N"] / t["thrust"] - 1)
    factor = v.get("added_mass_factor") or (v.get("elastic") or {}).get("added_mass_factor") or 0.5
    cfg = elastic.ElasticConfig.from_dict({**spec, "added_mass_factor": factor})
    R.ANIMATION_OPTIONS.update(HQ_OPTIONS)
    tmp = dest.with_name(dest.name + ".tmp")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        r = R.run(case, settings, cfg, {**ov, "dt_s": v["dt_s"], "cycles": v.get("cycles", ov["cycles"])}, output_dir=tmp)
    if r.get("status") != "ok" or not (tmp / "animation_front.webp").exists():
        return {**t, "error": f"animation run {r.get('status')}: {r.get('error')}"}
    dest.mkdir(parents=True, exist_ok=True)
    for src, name in (("animation.webp", "main.webp"), ("animation_front.webp", "front.webp"), ("animation_top.webp", "top.webp")):
        shutil.copyfile(tmp / src, dest / name)
    with Image.open(dest / "front.webp") as im:
        im.seek(max(0, im.n_frames - 20))
        im.convert("RGB").save(dest / "poster.webp")
    shutil.rmtree(tmp, ignore_errors=True)
    pre = f"top/{t['key']}/"
    return {**t, "media": {k: pre + k + ".webp" for k in ("main", "front", "top", "poster")},
            "replay": {"thrust": v["mean_thrust_N"], "torque": v["peak_abs_root_torque_Nm"], "status": v["status"],
                       "dt_s": v["dt_s"], "added_mass_factor": factor, "thrust_dev_pct": round(dev, 2)},
            "elapsed_s": round(time.time() - t0, 1)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m wingstudy.top_media", description=__doc__.split("\n\n")[0])
    ap.add_argument("summaries", type=Path, nargs="*", help="second-stage refine_top summaries (default atlas/refine-top/*/stage2.json)")
    ap.add_argument("--freqs", type=float, nargs="+", default=list(FREQS))
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    summaries = a.summaries or sorted((ATLAS / "refine-top").glob("*/stage2.json"))
    man = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    todo = [t for t in tasks(summaries, a.freqs) if t["key"] not in man or not (DEST / t["key"] / "poster.webp").exists()]
    for t in todo:
        print(f"{t['key']}  {t['kind']:9s} {t['freq']:g} Hz  {t['label']}  {t['thrust']:.3f} N", flush=True)
    print(f"{len(todo)} to render ({len(man)} already in {MANIFEST.name})", flush=True)
    if a.dry or not todo:
        return 0
    todo.sort(key=lambda t: t["numerics"]["span_panels"] * t["numerics"]["chord_panels"])    # quick coarse ones first
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        for job in as_completed([pool.submit(render, t) for t in todo]):
            r = job.result()
            if r.get("error"):
                print(time.strftime("%H:%M:%S"), r["key"], "FAILED", r["error"], flush=True)
                continue
            man[r["key"]] = {**r["media"], "label": r["label"], "kind": r["kind"], "freq": r["freq"], "replay": r["replay"]}
            S.write_json(MANIFEST, dict(sorted(man.items())))
            print(time.strftime("%H:%M:%S"), r["key"], f"thrust {r['replay']['thrust']:.3f} N ({r['replay']['thrust_dev_pct']:+.2f} %)",
                  f"{r['elapsed_s']:.0f} s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
