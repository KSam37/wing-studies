"""Batch driver for elastic (stabilized aeroelastic) wing studies. Linux/macOS/Windows.

Commands
--------
  validate  The three manufactured candidates (7657, 3894, 7835) across plate
            thickness and layup, plus numerical-independence checks.
  run       Any JSON spec: wings x elastic configs x solver overrides.
  sample    Write a spec of space-filling wings under the original search
            constraints (root <= 0.2 m, positive chords >= 0.01 m, optional
            non-increasing chords, zero chords only as an outboard suffix).
  report    Summary CSV + figure for a results directory.
  stiffness The three candidates at rigid / 1.0 / 0.5 / 0.25 / 0.2 mm plain weave, with
            Ptera animations and a side-by-side montage per wing.

Every run is resumable: results append to results.jsonl keyed by a hash of
(wing, config, overrides), and finished keys are skipped on restart.

Examples
--------
  python -m wingstudy.elastic_study validate --workers 14
  python -m wingstudy.elastic_study sample --count 3000 --out outputs/elastic/overnight/spec.json
  python -m wingstudy.elastic_study run outputs/elastic/overnight/spec.json --workers 14
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parent
DEFAULT_OUT = ROOT / "outputs" / "elastic"

CANDIDATES = [  # label, wing reference
    ("Top #7657", {"catalog": 7657}),
    ("Middle #3894", {"catalog": 3894}),
    ("Rectangle #7835", {"builtin": "rect7835"}),
]
WOVEN = {"name": "woven_cf_0_90", "shear_modulus_pa": 4.5e9, "density_kg_m3": 1550.0}
BIAS = {"name": "cf_pm45_or_quasi_iso", "shear_modulus_pa": 18e9, "density_kg_m3": 1550.0}


# --------------------------------------------------------------------------------------
# Spec handling
# --------------------------------------------------------------------------------------
def resolve_wing(ref: dict, template_no: int = 7657):
    """Wing reference -> (case, settings). Generated wings inherit template motion/settings."""
    from . import elastic_runner as R
    if "catalog" in ref:
        return R.load_catalog_case(int(ref["catalog"]))
    if ref.get("builtin") == "rect7835":
        return R.rectangle_7835(None)
    if "chords_m" in ref:
        template, settings = R.load_catalog_case(template_no)
        chords = [c for c in ref["chords_m"]]
        active = [c for c in chords if c > 0]
        if len(active) < 2:
            raise ValueError("A wing needs at least two positive chords.")
        span = ref["span_m"] * (len(active) - 1) / (len(chords) - 1)
        return R.sections_case(template, settings, active, span, ref.get("name", "Sampled wing")), settings
    raise ValueError(f"Unrecognised wing reference {ref}")


def job_key(wing, config, overrides) -> str:
    blob = json.dumps([wing, config, overrides], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()[:20]


def expand(spec: dict) -> list[dict]:
    jobs = []
    for wing in spec["wings"]:
        for config in spec["configs"]:
            for ov in spec.get("overrides", [{}]):
                jobs.append({"wing": wing, "config": config, "overrides": ov,
                             "template": spec.get("template_case", 7657),
                             "key": job_key(wing, config, ov)})
    return jobs


# --------------------------------------------------------------------------------------
# Worker
# --------------------------------------------------------------------------------------
def _init_worker():
    # One numerical thread per process; parallelism comes from processes.
    for var in ("NUMBA_NUM_THREADS", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[var] = "1"


def _run_job(job: dict) -> dict:
    from . import elastic
    from . import elastic_runner as R
    try:
        case, settings = resolve_wing(job["wing"], job["template"])
    except Exception as exc:  # noqa: BLE001
        return {**job, "status": "invalid", "error": str(exc)}
    cfg = None if job["config"] is None else elastic.ElasticConfig.from_dict(job["config"])
    if job.get("verify", True) and cfg is not None:
        result = R.run_verified(case, settings, cfg, job["overrides"])
    else:
        result = R.run(case, settings, cfg, job["overrides"])
    if not job.get("keep_history"):
        result.pop("history", None)
    return {**job, **result}


def _animate_job(label, wing, config, out_dir: Path) -> dict:
    from . import elastic
    from . import elastic_runner as R
    case, settings = resolve_wing(wing)
    cfg = None if config is None else elastic.ElasticConfig.from_dict(config)
    verification = None
    if cfg is not None:
        # Animate a verified solution, or for an uncertain point the settled factor
        # nearest the middle of its range; re-solve with that factor, saving outputs.
        verification = R.run_verified(case, settings, cfg, dt_refinements=(1, 2, 4))
        out_dir.mkdir(parents=True, exist_ok=True)
        if verification["status"] not in ("verified", "uncertain"):
            r = {"status": "beyond_model", "verification_status": verification["status"],
                 "dt_attempts": verification.get("dt_attempts"), "attempts": verification["attempts"]}
            (out_dir / "metrics.json").write_text(json.dumps({"label": label, **r}, indent=1))
            return r
        cfg = elastic.ElasticConfig.from_dict({**cfg.to_dict(), "added_mass_factor": verification["added_mass_factor"]})
        overrides = {"dt_s": verification["dt_s"], "cycles": verification["cycles"]}
    else:
        overrides = {}
    r = R.run(case, settings, cfg, overrides, output_dir=out_dir)
    if verification is not None:
        r["verification_status"] = verification["status"]
        r["verification_spread_pct"] = verification.get("verification_spread_pct")
        if verification["status"] == "uncertain":
            for k in ("mean_thrust_N", "peak_abs_root_torque_Nm", "tip_twist_amplitude_deg", "thrust_per_torque",
                      "thrust_range_N", "torque_range_Nm", "tip_twist_range_deg", "settled_factors"):
                r[k] = verification[k]
            r["status"] = "uncertain"
    r.pop("history", None)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "metrics.json").write_text(json.dumps({"label": label, **r}, indent=1))
    return r


# Plain-weave carbon/epoxy sheet (monolithic, laser/waterjet cut). Torsion is set by the
# in-plane shear modulus G12 ~ 3.5-5 GPa for plain weave; 4.5 GPa assumed (measure to refine).
PLAIN_WEAVE = {"name": "plain_weave_cf", "shear_modulus_pa": 4.5e9, "density_kg_m3": 1550.0, "youngs_modulus_pa": 50e9}
STIFFNESS_LEVELS = [("Rigid", None), ("1.0 mm", 1.0), ("0.5 mm", 0.5), ("0.25 mm", 0.25), ("0.2 mm", 0.2)]


def _slug(label):
    return label.split("#")[0].strip().lower() + "_" + label.split("#")[1]


def stiffness_study(out: Path, workers: int):
    jobs = []
    for label, wing in CANDIDATES:
        for level, t in STIFFNESS_LEVELS:
            cfg = None if t is None else {"stiffness_model": "plate", "thickness_m": t * 1e-3, "material": PLAIN_WEAVE}
            jobs.append((label, wing, cfg, out / _slug(label) / level.replace(" ", "")))
    rows = []
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as pool:
        futures = {pool.submit(_animate_job, *j): j for j in jobs}
        for fut in as_completed(futures):
            label, _, cfg, path = futures[fut]
            r = fut.result()
            level = path.name
            rows.append({"wing": label, "level": level, **{k: r.get(k) for k in (
                "status", "mean_thrust_N", "peak_abs_root_torque_Nm", "tip_twist_amplitude_deg", "dt_s",
                "verification_spread_pct")},
                **{f"{k}_{end}": (r.get(k) or [None, None])[i] for k in ("thrust_range_N", "torque_range_Nm", "tip_twist_range_deg")
                   for i, end in enumerate(("min", "max"))}})
            print(f"{label:16s} {level:8s} {r['status']:12s} T={r.get('mean_thrust_N') or float('nan'):.3f} "
                  f"M={r.get('peak_abs_root_torque_Nm') or float('nan'):.3f} tip=±{r.get('tip_twist_amplitude_deg') or 0:.0f}°", flush=True)
    order = {lvl.replace(" ", ""): i for i, (lvl, _) in enumerate(STIFFNESS_LEVELS)}
    rows.sort(key=lambda r: ([c[0] for c in CANDIDATES].index(r["wing"]), order[r["level"]]))
    with (out / "stiffness_summary.csv").open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    plot_stiffness(rows, out)
    from . import elastic_figures
    elastic_figures.thrust_torque_paths(rows, out / "thrust_torque_stiffness.png")
    for label, _ in CANDIDATES:
        montage(out / _slug(label), label)


def plot_stiffness(rows, out: Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "serif", "font.serif": ["Times New Roman", "DejaVu Serif"],
                         "font.size": 10, "axes.spines.top": False, "axes.spines.right": False})
    colors = {"Top #7657": "#0072B2", "Middle #3894": "#009E73", "Rectangle #7835": "#D55E00"}
    styles = {"Top #7657": ("-", "o"), "Middle #3894": ("--", "s"), "Rectangle #7835": ("-.", "^")}
    levels = [l for l, _ in STIFFNESS_LEVELS]
    x = range(len(levels))
    panels = [("mean_thrust_N", "Mean thrust (N)"), ("peak_abs_root_torque_Nm", "Peak root torque (N·m)"),
              ("tip_twist_amplitude_deg", "Tip twist amplitude (°)")]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.3))
    rng = {"mean_thrust_N": "thrust_range_N", "peak_abs_root_torque_Nm": "torque_range_Nm",
           "tip_twist_amplitude_deg": "tip_twist_range_deg"}
    for ax, (key, title) in zip(axes, panels):
        for i, (label, _) in enumerate(CANDIDATES):
            pts, uncertain, missing = [], [], []
            for xi, lvl in zip(x, levels):
                r = next(r for r in rows if r["wing"] == label and r["level"] == lvl.replace(" ", ""))
                v = r.get(key)
                if lvl == "Rigid" and key == "tip_twist_amplitude_deg":
                    v = 0.0
                if r["status"] not in ("ok", "uncertain") or v is None:
                    missing.append(xi); continue
                pts.append((xi, v))
                if r["status"] == "uncertain":
                    uncertain.append((xi, v, r.get(rng[key] + "_min"), r.get(rng[key] + "_max")))
            ls, mk = styles[label]
            ax.plot([p[0] for p in pts], [p[1] for p in pts], ls, marker=mk, ms=7, lw=2, color=colors[label], label=label)
            for xi, v, lo, hi in uncertain:
                ax.errorbar(xi, v, yerr=[[v - lo], [hi - v]], fmt=mk, ms=8, mfc="white", mec=colors[label],
                            mew=1.8, ecolor=colors[label], elinewidth=1.6, capsize=5, zorder=3)
            for xi in missing:
                ax.plot(xi + (i - 1) * 0.08, 0, marker="x", ms=8, mew=2, color=colors[label], clip_on=False)
        ax.set_xticks(list(x), levels)
        ax.set_title(title, fontsize=11, loc="left")
        ax.set_ylim(bottom=0)
        ax.grid(True, axis="y", color="#dde3ea", lw=0.7)
    axes[0].legend(frameon=False, fontsize=9)
    axes[1].set_xlabel("Plain-weave carbon sheet thickness  (stiffer → softer)")
    fig.suptitle("Flexibility cuts thrust and root torque on all three wings", x=0.01, ha="left", fontsize=13)
    fig.text(0.01, 0.01, "Hollow marker + bar = lower confidence: stabilization settings disagree by more than 3%; bar spans every setting that settled, "
             "marker is the midpoint.  × = no settled solution.\nPlain weave, G = 4.5 GPa, E = 50 GPa; twist about the leading edge; 1 Hz, 0.5 m/s.",
             fontsize=8, color="#4a5563")
    fig.tight_layout(rect=(0, 0.06, 1, 0.95))
    fig.savefig(out / "stiffness_comparison.png", dpi=200, facecolor="white")
    plt.close(fig)


def montage(wing_dir: Path, label: str, frames=50):
    """Stacked, time-synchronized front views (Ptera's animation_front.webp) of every
    stiffness level for one wing. From the front a rigid zero-pitch wing is edge-on,
    so any visible surface is twist. Final flapping cycle, sampled at common phases."""
    from PIL import Image, ImageDraw, ImageFont
    import numpy as np
    try:
        big = ImageFont.truetype("DejaVuSans-Bold.ttf", 26)
        small = ImageFont.truetype("DejaVuSans.ttf", 20)
    except OSError:
        big = small = ImageFont.load_default()
    rows = []
    for lvl, _ in STIFFNESS_LEVELS:
        d = wing_dir / lvl.replace(" ", "")
        m = json.loads((d / "metrics.json").read_text())
        path = d / "animation_front.webp"
        seq = None
        if m.get("status") in ("ok", "uncertain") and path.exists():
            im = Image.open(path)
            # frames per cycle from the file itself (Ptera may keep only every Nth step at true speed)
            n = im.n_frames; per = int(round(n / m["cycles"])) if m.get("cycles") else int(round(1.0 / m["dt_s"]))
            seq = []
            for k in range(frames):
                im.seek(min(n - 1, n - per + int(k * per / frames)))
                seq.append(im.convert("RGB"))
        rows.append((lvl, m, seq))
    # Crop every level to the union of where the wing appears (colorbar excluded).
    boxes = []
    for _, _, seq in rows:
        if seq:
            for f in seq[::5]:
                a = np.asarray(f)[: int(f.height * 0.78)]
                ys, xs = np.nonzero(a.max(axis=2) > 40)
                if len(xs):
                    boxes.append((xs.min(), ys.min(), xs.max(), ys.max()))
    x0 = max(min(b[0] for b in boxes) - 20, 0); y0 = max(min(b[1] for b in boxes) - 20, 0)
    x1 = max(b[2] for b in boxes) + 20; y1 = max(b[3] for b in boxes) + 20
    tw, th = x1 - x0, y1 - y0
    label_w = 300
    out = []
    for k in range(frames):
        canvas = Image.new("RGB", (label_w + tw, th * len(rows)), "black")
        draw = ImageDraw.Draw(canvas)
        for j, (lvl, m, seq) in enumerate(rows):
            top = j * th
            if j:
                draw.line([(0, top), (label_w + tw, top)], fill="#2b3340", width=2)
            draw.text((16, top + 14), lvl, fill="white", font=big)
            if seq is None:
                draw.text((16, top + 52), "beyond model", fill="#9aa4b2", font=small)
                draw.text((label_w + 30, top + th // 2 - 12), "no settled solution at any stabilization setting",
                          fill="#6b7280", font=small)
            else:
                canvas.paste(seq[k].crop((x0, y0, x1, y1)), (label_w, top))
                if m.get("status") == "uncertain":
                    tl, th_ = m["thrust_range_N"]; ml, mh = m["torque_range_Nm"]
                    draw.text((16, top + 52), f"thrust  {tl:.2f}–{th_:.2f} N", fill="#cfd6df", font=small)
                    draw.text((16, top + 80), f"torque  {ml:.2f}–{mh:.2f} N·m", fill="#cfd6df", font=small)
                    draw.text((16, top + 136), "lower confidence", fill="#f0b429", font=small)
                else:
                    draw.text((16, top + 52), f"thrust  {m['mean_thrust_N']:.2f} N", fill="#cfd6df", font=small)
                    draw.text((16, top + 80), f"torque  {m['peak_abs_root_torque_Nm']:.2f} N·m", fill="#cfd6df", font=small)
                if m.get("tip_twist_amplitude_deg"):
                    draw.text((16, top + 108), f"tip twist ±{m['tip_twist_amplitude_deg']:.0f}°", fill="#cfd6df", font=small)
        out.append(canvas)
    title = Image.new("RGB", (out[0].width, 50), "black")
    ImageDraw.Draw(title).text((16, 10), f"{label} — front view (looking upstream into the leading edge)", fill="white", font=small)
    framed = []
    for f in out:
        c = Image.new("RGB", (f.width, f.height + 50), "black"); c.paste(title, (0, 0)); c.paste(f, (0, 50)); framed.append(c)
    framed[0].save(wing_dir / "stiffness_montage.webp", save_all=True, append_images=framed[1:], duration=70, loop=0, quality=85)
    framed[0].save(wing_dir / "stiffness_montage.gif", save_all=True, append_images=framed[1:], duration=70, loop=0)
    framed[frames // 8].save(wing_dir / "stiffness_montage_frame.png")


# --------------------------------------------------------------------------------------
# Space-filling sampler under the original search constraints
# --------------------------------------------------------------------------------------
def sample_wings(count, nodes=8, spans=(0.4, 0.5, 0.6, 0.7, 0.8), gap=0.04, root_max=0.2,
                 min_chord=0.01, decreasing=True, allow_zero_tip=True, seed=0):
    """Scrambled-Sobol chord fractions mapped to monotone, constraint-valid wings.

    Each sample draws a root chord in [min_chord, root_max] and successive
    fractions so chord_i = chord_{i-1} * u_i (non-increasing), snapping values
    below min_chord to zero for the outboard suffix when allowed. Spans are the
    full two-wing spans used in the original searches (half span = (span-gap)/2).
    """
    from scipy.stats import qmc
    sob = qmc.Sobol(d=nodes + 1, scramble=True, seed=seed)
    u = sob.random(count)
    wings = []
    for i, row in enumerate(u):
        span = spans[int(row[0] * len(spans)) % len(spans)]
        chords = [min_chord + (root_max - min_chord) * row[1]]
        for x in row[2:]:
            nxt = chords[-1] * (0.35 + 0.65 * x) if decreasing else min_chord + (root_max - min_chord) * x
            chords.append(nxt)
        out, zero = [], False
        for j, c in enumerate(chords):
            if zero or (c < min_chord and allow_zero_tip and j >= 2):
                zero = True; out.append(0.0)
            else:
                out.append(round(max(c, min_chord), 4))
        wings.append({"chords_m": out, "span_m": round((span - gap) / 2, 6), "name": f"sobol_{seed}_{i:05d}"})
    return wings


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("validate"); v.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    v.add_argument("--out", type=Path, default=DEFAULT_OUT / "validation")
    r = sub.add_parser("run"); r.add_argument("spec", type=Path)
    r.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2)); r.add_argument("--out", type=Path)
    s = sub.add_parser("sample"); s.add_argument("--count", type=int, default=2048); s.add_argument("--nodes", type=int, default=8)
    s.add_argument("--seed", type=int, default=0); s.add_argument("--out", type=Path, required=True)
    s.add_argument("--thickness-mm", type=float, nargs="+", default=[0.5])
    s.add_argument("--shear-gpa", type=float, default=4.5)
    s.add_argument("--no-decreasing", action="store_true")
    rep = sub.add_parser("report"); rep.add_argument("dir", type=Path)
    st = sub.add_parser("stiffness", help="Three candidates at rigid/1.0/0.5/0.25/0.2 mm plain weave: plot + Ptera animations + montage")
    st.add_argument("--out", type=Path, default=DEFAULT_OUT / "stiffness")
    st.add_argument("--workers", type=int, default=8)
    a = p.parse_args(argv)

    if a.cmd == "validate":
        jobs = validation_spec()["jobs"]
        rows = run_jobs(jobs, a.out, a.workers, keep_history=False)
        for j, row in zip(jobs, rows):
            row.setdefault("label", j["label"]); row.setdefault("group", j["group"])
        write_summary(rows, a.out); plot_validation(rows, a.out)
        print(f"Wrote {a.out/'summary.csv'} and {a.out/'validation_three_candidates.png'}")
    elif a.cmd == "run":
        spec = json.loads(a.spec.read_text())
        out = a.out or a.spec.parent
        rows = run_jobs(expand(spec), out, a.workers)
        write_summary(rows, out)
    elif a.cmd == "sample":
        mat = {"name": "custom", "shear_modulus_pa": a.shear_gpa * 1e9, "density_kg_m3": 1550.0}
        spec = {"template_case": 7657,
                "note": "Motion, speed, fluid and solver settings inherit from catalog case 7657.",
                "wings": sample_wings(a.count, nodes=a.nodes, seed=a.seed, decreasing=not a.no_decreasing),
                "configs": [{"stiffness_model": "plate", "thickness_m": t * 1e-3, "material": mat} for t in a.thickness_mm],
                "overrides": [{}]}
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(spec, indent=1))
        print(f"Wrote {len(spec['wings'])} wings x {len(spec['configs'])} configs to {a.out}")
    elif a.cmd == "stiffness":
        stiffness_study(a.out, a.workers)
        print(f"Wrote {a.out/'stiffness_comparison.png'}, {a.out/'stiffness_summary.csv'} and per-wing stiffness_montage.webp")
    elif a.cmd == "report":
        rows = [json.loads(l) for l in (a.dir / "results.jsonl").read_text().splitlines() if l.strip()]
        write_summary(rows, a.dir)
        if any(r.get("group") for r in rows):
            plot_validation(rows, a.dir)


if __name__ == "__main__":
    main()
