"""Fine-mesh smooth-outline refinement of campaign winners (1 Hz, peak root torque <= 1 N m).

  python WingStudy/elastic_refine.py [--workers N] [--out DIR] [--models rigid,t0.50r,...]
  python WingStudy/elastic_refine.py --baseline     # coarse winners' exact outlines on the fine mesh

For each structural model, the best verified (elastic) / settled (rigid) design with peak root
torque <= 1 N m at 1 Hz is taken from every campaign folder that exists (weekend, rod, sweep).
Its outline is re-described as a smooth trailing edge: a monotone cubic (PCHIP) through the
fixed 200 mm root chord and 6 control chords at equal fractions of the half-span, evaluated
at 25 stations for a fine 24-strip mesh. The leading edge stays straight (zero sweep and
dihedral). Variables: the 6 control chords (non-increasing, 10-200 mm) and the half-span
(280-400 mm). Each round tries +/- one step on every variable in parallel and accepts the best
improvement; steps 10 mm, then 5 mm; stops when neither improves. The score is the campaign's
torque_1Nm rule, evaluated on the fine mesh: thrust if peak torque <= 1 N m, otherwise
-10 - (torque - 1). Only verified elastic / settled rigid solves count.

Resumable: every solve is cached in OUT/cache.jsonl. Outputs per model in OUT/<model>/:
history.json, outline.png (coarse winner vs smooth result, to scale), progress.png,
evolution.gif, final outline as CSV and 1:1 SVG, and Ptera's animations of the final design.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import math
import os
import sqlite3
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))

CAMPAIGNS = [ROOT / "outputs" / "elastic" / "campaigns" / n for n in ("weekend", "rod", "sweep")]
OUT = ROOT / "outputs" / "elastic" / "refine"
ROD = {"diameter_m": 5e-3, "hollow_inner_diameter_m": 3e-3, "shear_modulus_pa": 4.5e9, "density_kg_m3": 1550.0}
MATERIAL = {"name": "plain_weave_cf", "shear_modulus_pa": 4.5e9, "density_kg_m3": 1550.0, "youngs_modulus_pa": 50e9}
MODELS = {"rigid": ("Rigid", None, None), "t0.50r": ("0.5 mm + rod", 0.5, ROD),
          "t0.25r": ("0.25 mm + rod", 0.25, ROD), "t0.50": ("0.5 mm (no rod)", 0.5, None)}
ROOT_CHORD, MIN_CHORD, MAX_CHORD = 0.200, 0.010, 0.200
SPAN_RANGE = (0.280, 0.400)
N_CTRL = 6
STEPS = (0.010, 0.005)
TORQUE_LIMIT = 1.0
FREQ = 1.0
DEFAULT_NUMERICS = {"stations": 25, "span_panels": 24, "chord_panels": 6, "steps_per_cycle": 50, "cycles": 4,
                    "dt_refinements": [1, 2]}


# ----------------------------------------------------------------------------------------
# Geometry
# ----------------------------------------------------------------------------------------

def chords_from_ctrl(ctrl, stations):
    import numpy as np
    from scipy.interpolate import PchipInterpolator
    eta = np.linspace(0, 1, N_CTRL + 1)
    f = PchipInterpolator(eta, [ROOT_CHORD] + list(ctrl))   # monotone data -> monotone curve
    c = f(np.linspace(0, 1, stations))
    c[0] = ROOT_CHORD
    return [round(float(max(MIN_CHORD, min(MAX_CHORD, x))), 6) for x in c]


def fit_ctrl(chords, half_span):
    """Control chords and effective span from a coarse campaign outline (zero tip suffix trimmed)."""
    import numpy as np
    active = [c for c in chords if c > 0]
    n = len(chords)
    span = half_span * (len(active) - 1) / (n - 1)
    ys = np.linspace(0, span, len(active))
    ctrl = [float(np.interp(k / N_CTRL * span, ys, active)) for k in range(1, N_CTRL + 1)]
    out, prev = [], ROOT_CHORD
    for c in ctrl:
        prev = min(prev, max(MIN_CHORD, c)); out.append(round(prev, 4))
    return out, min(SPAN_RANGE[1], max(SPAN_RANGE[0], round(span, 3))), span


def valid(ctrl, span):
    prev = ROOT_CHORD
    for c in ctrl:
        if c < MIN_CHORD - 1e-12 or c > prev + 1e-12:
            return False
        prev = c
    return SPAN_RANGE[0] - 1e-12 <= span <= SPAN_RANGE[1] + 1e-12


# ----------------------------------------------------------------------------------------
# Solve (worker process)
# ----------------------------------------------------------------------------------------

def key_of(model, ctrl, span, numerics):
    blob = json.dumps([model, [round(c, 5) for c in ctrl], round(span, 4), numerics], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:20]


def _solve(task):
    warnings.filterwarnings("ignore")
    import elastic
    import elastic_runner as R
    t0 = time.time()
    num = task["numerics"]
    template, settings = R.load_catalog_case(7657)
    chords = chords_from_ctrl(task["ctrl"], num["stations"])
    case = R.sections_case(template, settings, chords, task["span"], task["key"])
    case["frequency_hz"] = FREQ
    ov = {"dt_s": 1.0 / (num["steps_per_cycle"] * FREQ), "cycles": num["cycles"],
          "span_panels": num["span_panels"], "chord_panels": num["chord_panels"]}
    _, thick, rod = MODELS[task["model"]]
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        if thick is None:
            r = R.run(case, settings, None, ov)
            status = "ok" if r["status"] == "ok" and r.get("settled") else "unsettled"
        else:
            cfg = elastic.ElasticConfig.from_dict({"stiffness_model": "plate", "thickness_m": thick * 1e-3,
                                                   "material": MATERIAL, "rod": rod or {}})
            r = R.run_verified(case, settings, cfg, ov, dt_refinements=tuple(num["dt_refinements"]))
            status = r["status"]
    return {"key": task["key"], "model": task["model"], "ctrl": task["ctrl"], "span": task["span"], "status": status,
            "thrust": r.get("mean_thrust_N"), "torque": r.get("peak_abs_root_torque_Nm"),
            "tip_twist": r.get("tip_twist_amplitude_deg"), "dt": r.get("dt_s"),
            "factor": r.get("added_mass_factor") or (r.get("elastic") or {}).get("added_mass_factor"),
            "elapsed": round(time.time() - t0, 1), "error": r.get("error")}


def _solve_exact(task):
    """The coarse winner's own 8-station outline (straight segments, zero tip suffix trimmed),
    solved with the refinement numerics: the like-for-like baseline for the optimized shape."""
    warnings.filterwarnings("ignore")
    import elastic
    import elastic_runner as R
    t0 = time.time()
    num = task["numerics"]
    template, settings = R.load_catalog_case(7657)
    chords = [c for c in task["chords"] if c > 0]
    span = task["half_span"] * (len(chords) - 1) / (len(task["chords"]) - 1)
    case = R.sections_case(template, settings, chords, span, "coarse winner, fine mesh")
    case["frequency_hz"] = FREQ
    ov = {"dt_s": 1.0 / (num["steps_per_cycle"] * FREQ), "cycles": num["cycles"],
          "span_panels": num["span_panels"], "chord_panels": num["chord_panels"]}
    _, thick, rod = MODELS[task["model"]]
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        if thick is None:
            r = R.run(case, settings, None, ov)
            status = "ok" if r["status"] == "ok" and r.get("settled") else "unsettled"
        else:
            cfg = elastic.ElasticConfig.from_dict({"stiffness_model": "plate", "thickness_m": thick * 1e-3,
                                                   "material": MATERIAL, "rod": rod or {}})
            r = R.run_verified(case, settings, cfg, ov, dt_refinements=tuple(num["dt_refinements"]))
            status = r["status"]
    return {"model": task["model"], "chords": task["chords"], "half_span": task["half_span"], "effective_span": span,
            "status": status, "thrust": r.get("mean_thrust_N"), "torque": r.get("peak_abs_root_torque_Nm"),
            "tip_twist": r.get("tip_twist_amplitude_deg"), "dt": r.get("dt_s"), "numerics": num,
            "elapsed": round(time.time() - t0, 1), "error": r.get("error")}


def baseline(out: Path, workers: int):
    """Solve every refined model's coarse winner exactly on the fine mesh -> OUT/<model>/baseline_fine.json."""
    jobs = []
    for d in sorted(p for p in out.iterdir() if (p / "history.json").exists()):
        h = json.loads((d / "history.json").read_text())
        jobs.append({"model": d.name, "chords": h["winner"]["chords"], "half_span": h["winner"]["half_span"],
                     "numerics": h["numerics"]})
    with ProcessPoolExecutor(max(1, min(workers, len(jobs)))) as ex:
        for res in ex.map(_solve_exact, jobs):
            (out / res["model"] / "baseline_fine.json").write_text(json.dumps(res, indent=1))
            print(f"{res['model']}: coarse outline on fine mesh {res['status']} {res['thrust']} N @ {res['torque']} N·m "
                  f"({res['elapsed']} s)", flush=True)


def _resize_to_budget(job):
    """Coarse winner's outline (same chords, span scaled) solved on the fine mesh, with the span
    adjusted by secant steps until peak torque is at the budget: isolates shape from size."""
    base = json.loads((job["dir"] / "baseline_fine.json").read_text())
    pts = [(1.0, base["torque"])]
    s = (TORQUE_LIMIT / base["torque"]) ** (1 / 2.5)   # torque grows roughly as span^2.5
    res = None
    for _ in range(5):
        res = _solve_exact({"model": job["model"], "chords": base["chords"], "half_span": base["half_span"] * s,
                            "numerics": base["numerics"]})
        res["scale"] = s
        if res["torque"] is None or res["status"] not in ("ok", "verified"):
            break
        pts.append((s, res["torque"]))
        if abs(res["torque"] - TORQUE_LIMIT) < 0.003:
            break
        (s0, q0), (s1, q1) = pts[-2], pts[-1]
        s = s1 + (TORQUE_LIMIT - q1) * (s1 - s0) / (q1 - q0) if q1 != q0 else s1
    return res


def baseline_at_budget(out: Path, workers: int):
    dirs = sorted(p for p in out.iterdir() if (p / "baseline_fine.json").exists())
    with ProcessPoolExecutor(max(1, min(workers, len(dirs)))) as ex:
        for d, res in zip(dirs, ex.map(_resize_to_budget, [{"dir": d, "model": d.name} for d in dirs])):
            (d / "baseline_at_budget.json").write_text(json.dumps(res, indent=1))
            print(f"{d.name}: coarse outline resized to budget: span x{res['scale']:.3f} -> {res['effective_span'] * 1000:.0f} mm, "
                  f"{res['status']} {res['thrust']:.3f} N @ {res['torque']:.3f} N·m", flush=True)


def score(rec):
    if rec is None or rec["status"] not in ("ok", "verified") or rec["thrust"] is None:
        return None
    return rec["thrust"] if rec["torque"] <= TORQUE_LIMIT else -10.0 - (rec["torque"] - TORQUE_LIMIT)


# ----------------------------------------------------------------------------------------
# Winners
# ----------------------------------------------------------------------------------------

def pick_winners(models):
    best = {}
    for camp in CAMPAIGNS:
        db_path = camp / "campaign.sqlite"
        if not db_path.exists():
            continue
        db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        for m in models:
            for key, chords, hs, t, q in db.execute(
                    "select key,chords,half_span,thrust,torque from designs where level=? and abs(freq-?)<1e-9 and numerics='base' "
                    "and status in ('verified','ok') and torque<=? order by thrust desc limit 20", (m, FREQ, TORQUE_LIMIT)):
                ch = json.loads(chords)
                _, _, eff = fit_ctrl(ch, hs)
                if not (SPAN_RANGE[0] - 0.0005 <= eff <= SPAN_RANGE[1] + 0.0005):
                    continue
                if m not in best or t > best[m]["thrust"]:
                    best[m] = {"model": m, "source": camp.name, "key": key, "chords": ch, "half_span": hs,
                               "effective_span": eff, "thrust": t, "torque": q}
                break
        db.close()
    return best


# ----------------------------------------------------------------------------------------
# Search
# ----------------------------------------------------------------------------------------

class Refiner:
    """Parallel pattern search over (6 control chords, half-span)."""

    def __init__(self, winner, numerics, max_rounds=40):
        self.w = winner
        self.model = winner["model"]
        self.numerics = numerics
        self.ctrl, self.span, _ = fit_ctrl(winner["chords"], winner["half_span"])
        self.step_i = 0
        self.rounds = 0
        self.max_rounds = max_rounds
        self.current = None
        self.history = []
        self.done = False
        self.note = ""

    def task(self, ctrl, span, tag):
        ctrl = [round(c, 4) for c in ctrl]; span = round(span, 3)
        return {"key": key_of(self.model, ctrl, span, self.numerics), "model": self.model, "ctrl": ctrl, "span": span,
                "numerics": self.numerics, "tag": tag}

    def start_tasks(self):
        return [self.task(self.ctrl, self.span, "start")]

    def candidates(self):
        step = STEPS[self.step_i]
        out = []
        for i in range(N_CTRL):
            for sgn in (1, -1):
                c = list(self.ctrl)
                hi = ROOT_CHORD if i == 0 else c[i - 1]
                lo = MIN_CHORD if i == N_CTRL - 1 else max(MIN_CHORD, c[i + 1])
                v = min(hi, max(lo, c[i] + sgn * step))
                if abs(v - c[i]) < 1e-9:
                    continue
                c[i] = v
                if valid(c, self.span):
                    out.append(self.task(c, self.span, f"c{i + 1}{'+' if sgn > 0 else '-'}{step * 1000:g}mm"))
        for sgn in (1, -1):
            s = min(SPAN_RANGE[1], max(SPAN_RANGE[0], self.span + sgn * step))
            if abs(s - self.span) > 1e-9:
                out.append(self.task(self.ctrl, s, f"span{'+' if sgn > 0 else '-'}{step * 1000:g}mm"))
        return out

    def accept_start(self, rec):
        self.current = rec
        self.history.append({"round": 0, "tag": "start (smooth fit of coarse winner)", **rec, "score": score(rec)})
        if score(rec) is None:
            self.done = True; self.note = "start design did not verify on the fine mesh"

    def step(self, results):
        """results: records for self.candidates(). Returns True while searching."""
        self.rounds += 1
        cur = score(self.current)
        best = None
        for rec in results:
            sc = score(rec)
            if sc is not None and sc > cur + 1e-6 and (best is None or sc > best[0]):
                best = (sc, rec)
        if best:
            self.current = best[1]; self.ctrl, self.span = list(best[1]["ctrl"]), best[1]["span"]
            self.history.append({"round": self.rounds, "tag": best[1].get("tag"), **best[1], "score": best[0]})
        elif self.step_i + 1 < len(STEPS):
            self.step_i += 1
        else:
            self.done = True; self.note = "no +/- 5 mm move improves the score"
        if self.rounds >= self.max_rounds and not self.done:
            self.done = True; self.note = f"round limit ({self.max_rounds}) reached"
        return not self.done


# ----------------------------------------------------------------------------------------
# Outputs
# ----------------------------------------------------------------------------------------

def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "serif", "font.serif": ["DejaVu Serif"], "font.size": 9,
                         "axes.spines.top": False, "axes.spines.right": False})
    return plt


def outline_xy(chords, span):
    n = len(chords)
    ys = [span * i / (n - 1) for i in range(n)]
    return ys + ys[::-1] + [0.0], [0.0] * n + [-c for c in chords][::-1] + [0.0]


def write_outputs(ref: Refiner, out: Path, numerics, color):
    import numpy as np
    from elastic_figures import INK2, GRID
    plt = _plt()
    out.mkdir(parents=True, exist_ok=True)
    label = MODELS[ref.model][0]
    w = ref.w
    (out / "history.json").write_text(json.dumps({"winner": w, "numerics": numerics, "note": ref.note,
                                                  "history": ref.history}, indent=1, default=str))
    fin = ref.current
    fch = chords_from_ctrl(fin["ctrl"], numerics["stations"])
    # outline before/after, to scale
    fig, ax = plt.subplots(figsize=(8, 3.4))
    act = [c for c in w["chords"] if c > 0]
    x0, y0 = outline_xy(act, w["effective_span"])
    ax.plot(x0, y0, color="#9a9993", lw=1.2, ls="--", label=f"coarse winner ({w['source']}): {w['thrust']:.2f} N @ {w['torque']:.2f} N·m (8×4 mesh)")
    x1, y1 = outline_xy(fch, fin["span"])
    ax.fill(x1, y1, color=color, alpha=0.25, lw=0)
    ax.plot(x1, y1, color=color, lw=1.8, label=f"refined: {fin['thrust']:.2f} N @ {fin['torque']:.2f} N·m ({numerics['span_panels']}×{numerics['chord_panels']} mesh)")
    ax.plot([fin["span"] * k / N_CTRL for k in range(1, N_CTRL + 1)], [-c for c in fin["ctrl"]], "o", ms=4, color=color)
    ax.set_aspect("equal"); ax.set_xlabel("Half-span position (m)"); ax.set_ylabel("Chord (m, LE at 0)")
    ax.set_xlim(-0.01, 0.41); ax.set_ylim(-0.21, 0.01); ax.grid(True, color=GRID, lw=0.6)
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    ax.set_title(f"{label}: refined outline (dots = control points, root 200 mm)", loc="left", fontsize=10)
    fig.tight_layout(); fig.savefig(out / "outline.png", dpi=200, facecolor="white"); plt.close(fig)
    # progress
    h = ref.history
    fig, axs = plt.subplots(1, 3, figsize=(10, 2.8))
    for a, k, lab in zip(axs, ("thrust", "torque", "span"), ("Mean thrust (N)", "Peak root torque (N·m)", "Half-span (m)")):
        a.plot(range(len(h)), [x[k] for x in h], "o-", color=color, ms=3)
        a.set_title(lab, loc="left", fontsize=9); a.set_xlabel("accepted step"); a.grid(True, color=GRID, lw=0.6)
    axs[1].axhline(TORQUE_LIMIT, color=INK2, ls=(0, (4, 3)), lw=1)
    fig.tight_layout(); fig.savefig(out / "progress.png", dpi=170, facecolor="white"); plt.close(fig)
    # evolution gif
    try:
        from PIL import Image
        frames = []
        for i, st in enumerate(h + [h[-1]] * 6):
            fig, ax = plt.subplots(figsize=(7, 3))
            ax.plot(x0, y0, color="#c8c7c1", lw=1, ls="--")
            xs, ys_ = outline_xy(chords_from_ctrl(st["ctrl"], numerics["stations"]), st["span"])
            ax.fill(xs, ys_, color=color, alpha=0.25, lw=0); ax.plot(xs, ys_, color=color, lw=1.6)
            ax.set_aspect("equal"); ax.set_xlim(-0.01, 0.41); ax.set_ylim(-0.21, 0.01); ax.axis("off")
            ax.set_title(f"{label}  step {min(i, len(h) - 1)}/{len(h) - 1}: {st['thrust']:.2f} N @ {st['torque']:.2f} N·m, "
                         f"half-span {st['span'] * 1000:.0f} mm", fontsize=9, loc="left")
            buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=80, facecolor="white"); plt.close(fig)
            buf.seek(0); frames.append(Image.open(buf).convert("P", palette=Image.ADAPTIVE))
        frames[0].save(out / "evolution.gif", save_all=True, append_images=frames[1:], duration=350, loop=0)
    except Exception as exc:  # noqa: BLE001
        print("gif skipped:", exc)
    # manufacturing outline: CSV + 1:1 SVG (mm), LE straight at y = 0
    n = len(fch)
    ys = [fin["span"] * i / (n - 1) for i in range(n)]
    with open(out / "final_outline.csv", "w") as f:
        f.write("station,spanwise_mm,chord_mm\n")
        for i, (y, c) in enumerate(zip(ys, fch)):
            f.write(f"{i},{y * 1000:.2f},{c * 1000:.2f}\n")
    pts = [(y * 1000, 0.0) for y in ys] + [(y * 1000, c * 1000) for y, c in zip(ys[::-1], fch[::-1])]
    W, H = fin["span"] * 1000 + 20, 220
    poly = " ".join(f"{x + 10:.2f},{yy + 10:.2f}" for x, yy in pts)
    (out / "final_outline.svg").write_text(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.1f}mm" height="{H}mm" viewBox="0 0 {W:.1f} {H}">'
        f'<title>{label} refined half-wing, 1:1 mm, straight leading edge on top (rod line)</title>'
        f'<polygon points="{poly}" fill="none" stroke="black" stroke-width="0.2"/></svg>')


def animate_final(ref: Refiner, out: Path, numerics):
    warnings.filterwarnings("ignore")
    import elastic
    import elastic_runner as R
    fin = ref.current
    template, settings = R.load_catalog_case(7657)
    case = R.sections_case(template, settings, chords_from_ctrl(fin["ctrl"], numerics["stations"]), fin["span"], "refined")
    case["frequency_hz"] = FREQ
    ov = {"dt_s": fin.get("dt") or 1.0 / (numerics["steps_per_cycle"] * FREQ), "cycles": numerics["cycles"],
          "span_panels": numerics["span_panels"], "chord_panels": numerics["chord_panels"]}
    _, thick, rod = MODELS[ref.model]
    cfg = None
    if thick is not None:
        cfg = elastic.ElasticConfig.from_dict({"stiffness_model": "plate", "thickness_m": thick * 1e-3, "material": MATERIAL,
                                               "rod": rod or {}, "added_mass_factor": fin.get("factor") or 0.5})
    with contextlib.redirect_stdout(io.StringIO()):
        R.run(case, settings, cfg, ov, output_dir=out / "ptera")


def summary(refs, out: Path, numerics):
    from elastic_figures import GRID
    plt = _plt()
    colors = {"rigid": "#6b6a66", "t0.50r": "#2a78d6", "t0.25r": "#e08a00", "t0.50": "#4b4bc8"}
    rows = ["model,source,coarse_key,coarse_thrust_N,coarse_torque_Nm,refined_thrust_N,refined_torque_Nm,refined_half_span_mm,tip_twist_deg,steps,note"]
    fig, ax = plt.subplots(figsize=(9, 3.2 + 0.9 * len(refs)))
    y = 0.0
    for r in refs:
        f, w = r.current, r.w
        rows.append(f"{r.model},{w['source']},{w['key']},{w['thrust']:.4f},{w['torque']:.4f},{f['thrust']:.4f},{f['torque']:.4f},"
                    f"{f['span'] * 1000:.0f},{f.get('tip_twist') or ''},{len(r.history) - 1},{r.note}")
        xs, ys = outline_xy(chords_from_ctrl(f["ctrl"], numerics["stations"]), f["span"])
        c = colors.get(r.model, "#2a78d6")
        ax.fill(xs, [v + y for v in ys], color=c, alpha=0.25, lw=0); ax.plot(xs, [v + y for v in ys], color=c, lw=1.6)
        ax.text(-0.02, y - 0.05, f"{MODELS[r.model][0]}\n{f['thrust']:.2f} N @ {f['torque']:.2f} N·m\n"
                f"(coarse {w['thrust']:.2f} N @ {w['torque']:.2f})", ha="right", va="top", fontsize=8.5)
        y -= 0.25
    ax.set_xlim(-0.2, 0.42); ax.set_ylim(y + 0.03, 0.02); ax.set_aspect("equal"); ax.axis("off")
    ax.set_title("Refined outlines at 1 Hz, peak root torque ≤ 1 N·m (fine mesh), to scale", loc="left", fontsize=11)
    fig.tight_layout(); fig.savefig(out / "summary.png", dpi=180, facecolor="white"); plt.close(fig)
    (out / "summary.csv").write_text("\n".join(rows) + "\n")


# ----------------------------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--models", default=",".join(MODELS))
    ap.add_argument("--numerics", default=None, help="JSON overriding mesh/time-step settings")
    ap.add_argument("--max-rounds", type=int, default=40)
    ap.add_argument("--no-animations", action="store_true")
    ap.add_argument("--baseline", action="store_true",
                    help="only solve each coarse winner's exact outline on the fine mesh (like-for-like baseline)")
    a = ap.parse_args(argv)
    numerics = dict(DEFAULT_NUMERICS, **(json.loads(a.numerics) if a.numerics else {}))
    os.environ.update({k: "1" for k in ("NUMBA_NUM_THREADS", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")})
    if a.baseline:
        baseline(a.out, a.workers)
        return baseline_at_budget(a.out, a.workers)
    out = a.out; out.mkdir(parents=True, exist_ok=True)
    log = open(out / "refine.log", "a")

    def say(msg):
        line = time.strftime("%Y-%m-%d %H:%M:%S ") + msg
        print(line, flush=True); log.write(line + "\n"); log.flush()

    models = [m for m in a.models.split(",") if m]
    winners = pick_winners(models)
    say(f"numerics {numerics}; workers {a.workers}")
    for m in models:
        w = winners.get(m)
        say(f"{m}: " + (f"{w['source']} {w['key']} {w['thrust']:.3f} N @ {w['torque']:.3f} N·m, "
                        f"effective half-span {w['effective_span'] * 1000:.0f} mm" if w else "no eligible winner"))
    (out / "winners.json").write_text(json.dumps(winners, indent=1))
    cache_path = out / "cache.jsonl"
    cache = {}
    if cache_path.exists():
        for line in cache_path.read_text().splitlines():
            if line.strip():
                rec = json.loads(line); cache[rec["key"]] = rec
    refs = [Refiner(winners[m], numerics, a.max_rounds) for m in models if m in winners]
    import multiprocessing as mp
    pool = ProcessPoolExecutor(max_workers=a.workers, mp_context=mp.get_context("spawn"))

    def solve_all(tasks):
        todo = {t["key"]: t for t in tasks if t["key"] not in cache}
        futs = {k: pool.submit(_solve, t) for k, t in todo.items()}
        for k, fu in futs.items():
            try:
                rec = fu.result()
            except Exception as exc:  # noqa: BLE001
                rec = {"key": k, "status": "failed", "error": str(exc), "thrust": None, "torque": None}
            cache[k] = rec
            with open(cache_path, "a") as f:
                f.write(json.dumps(rec) + "\n")
        return [dict(cache[t["key"]], tag=t["tag"], ctrl=t["ctrl"], span=t["span"]) for t in tasks]

    t0 = time.time()
    starts = [t for r in refs for t in r.start_tasks()]
    res = solve_all(starts)
    for r, rec in zip(refs, res):
        r.accept_start(rec)
        say(f"{r.model} start (smooth fit, fine mesh): {rec['status']} {rec.get('thrust')} N @ {rec.get('torque')} N·m, "
            f"half-span {rec['span'] * 1000:.0f} mm")
    while any(not r.done for r in refs):
        active = [r for r in refs if not r.done]
        cands = {id(r): r.candidates() for r in active}
        flat = [t for r in active for t in cands[id(r)]]
        say(f"round: {len(active)} refiner(s), {len(flat)} candidate solves")
        res = solve_all(flat)
        i = 0
        for r in active:
            n = len(cands[id(r)])
            r.step(res[i:i + n]); i += n
            c = r.current
            say(f"  {r.model} round {r.rounds}: {c['thrust']:.3f} N @ {c['torque']:.3f} N·m, half-span {c['span'] * 1000:.0f} mm, "
                f"step {STEPS[r.step_i] * 1000:g} mm{' DONE: ' + r.note if r.done else ''}")
        for r in refs:
            if score(r.current) is None:
                continue
            write_outputs(r, out / r.model, numerics, {"rigid": "#6b6a66", "t0.50r": "#2a78d6", "t0.25r": "#e08a00",
                                                          "t0.50": "#4b4bc8"}.get(r.model, "#2a78d6"))
    good = [r for r in refs if score(r.current) is not None]
    # Time-step check of every final design at twice the steps per cycle.
    fine_num = dict(numerics, steps_per_cycle=2 * numerics["steps_per_cycle"])
    checks = solve_all([dict(r.task(r.current["ctrl"], r.current["span"], "dt/2 check"), numerics=fine_num,
                             key=key_of(r.model, r.current["ctrl"], r.current["span"], fine_num)) for r in good])
    for r, rec in zip(good, checks):
        r.dt_check = rec
        say(f"{r.model} final: {r.current['thrust']:.3f} N @ {r.current['torque']:.3f} N·m; at dt/2: "
            f"{rec.get('status')} {rec.get('thrust')} N @ {rec.get('torque')} N·m")
        (out / r.model / "dt_check.json").write_text(json.dumps(rec, indent=1))
    if good:
        summary(good, out, numerics)
    say(f"search finished in {(time.time() - t0) / 3600:.1f} h")
    if not a.no_animations:
        futs = [pool.submit(animate_final, r, out / r.model, numerics) for r in good]
        for r, fu in zip(good, futs):
            try:
                fu.result(); say(f"{r.model}: Ptera animations written")
            except Exception as exc:  # noqa: BLE001
                say(f"{r.model}: animation failed: {exc}")
    pool.shutdown()
    say("refinement complete")


if __name__ == "__main__":
    main()
