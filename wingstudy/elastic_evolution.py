"""Evolution GIFs and sanity checks for elastic campaign searches (read-only, safe while running).

  python -m wingstudy.elastic_evolution CAMPAIGN_DIR --check            # text summary of every search
  python -m wingstudy.elastic_evolution CAMPAIGN_DIR                    # GIFs for every search with progress
  python -m wingstudy.elastic_evolution CAMPAIGN_DIR --search "t0.50@1Hz/torque_1Nm"
  python -m wingstudy.elastic_evolution CAMPAIGN_DIR --atlas-winners rod  # top performers' evolution, for the atlas

The campaign database is opened read-only, so this can run while the campaign is solving.
GIFs go to CAMPAIGN_DIR/evolution/. Each frame is one accepted step: left, the 25 seed
lineages as a grid (shape family x starting half-span) showing the current accepted shape to
scale over the faint seed outline; right, every lineage's path in thrust-torque space so far.
"""
from __future__ import annotations

import argparse
import io
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from .elastic_figures import STIFFNESS_COLORS, INK, INK2, GRID  # noqa: E402

FAMILY_ORDER = ["triangle", "square", "concave", "convex", "narrow"]


def connect(campaign: Path):
    return sqlite3.connect(f"file:{Path(campaign) / 'campaign.sqlite'}?mode=ro", uri=True, timeout=30)


def load_search(db, sid):
    s = db.execute("select search_id,level,freq,objective,status,tref,mref from searches where search_id=?", (sid,)).fetchone()
    if s is None:
        raise KeyError(sid)
    lins = {r[0]: {"id": r[0], "half_span": r[1], "family": r[2], "status": r[3], "evals": r[4], "steps": []}
            for r in db.execute("select lineage,half_span,family,status,evals from lineages where search_id=?", (sid,))}
    for lin, seq, key, score, ps, node, kind, chords, hs, thrust, torque, status in db.execute(
            "select a.lineage,a.seq,a.key,a.score,a.pass,a.node,a.kind,d.chords,d.half_span,d.thrust,d.torque,d.status "
            "from accepted a join designs d on d.key=a.key where a.search_id=? order by a.lineage,a.seq", (sid,)):
        if lin in lins:
            lins[lin]["steps"].append({"seq": seq, "key": key, "score": score, "pass": ps, "node": node, "kind": kind,
                                       "chords": json.loads(chords), "half_span": hs, "thrust": thrust, "torque": torque,
                                       "status": status})
    return {"id": s[0], "level": s[1], "freq": s[2], "objective": s[3], "status": s[4], "tref": s[5], "mref": s[6],
            "lineages": [lins[k] for k in sorted(lins)]}


def check(search) -> list[str]:
    """Each accepted step must raise the score; report gains and anything suspicious."""
    out, problems = [], 0
    gains = []
    for lin in search["lineages"]:
        st = lin["steps"]
        if not st:
            continue
        for a, b in zip(st, st[1:]):
            if b["score"] is None or a["score"] is None or b["score"] <= a["score"]:
                problems += 1
                out.append(f"    ! {lin['id']} step {b['seq']}: score {a['score']} -> {b['score']} (not an increase)")
        gains.append((lin, st[0], st[-1]))
    n_steps = sum(len(l["steps"]) for l in search["lineages"])
    done = sum(l["status"] not in ("running",) for l in search["lineages"])
    head = (f"{search['id']:<30} {search['status']:<10} lineages {done}/{len(search['lineages'])} finished, "
            f"{n_steps} accepted steps, {problems} non-increasing step(s)")
    lines = [head]
    if gains:
        dt = [g[2]["thrust"] - g[1]["thrust"] for g in gains if g[1]["thrust"] is not None and g[2]["thrust"] is not None]
        best = max(gains, key=lambda g: g[2]["score"] if g[2]["score"] is not None else -1e9)
        lines.append(f"    thrust change seed->current: median {sorted(dt)[len(dt) // 2]:+.3f} N, best lineage "
                     f"{best[0]['id']} ({best[0]['family']}, {best[0]['half_span'] * 1000:.0f} mm): "
                     f"{best[1]['thrust']:.3f} N @ {best[1]['torque']:.3f} N·m -> {best[2]['thrust']:.3f} N @ {best[2]['torque']:.3f} N·m")
    return lines + out


def render_gif(search, out_path: Path, max_frames=80, target=1.0):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    plt.rcParams.update({"font.family": "serif", "font.serif": ["Times New Roman", "DejaVu Serif"], "font.size": 9,
                         "axes.spines.top": False, "axes.spines.right": False})
    lins = [l for l in search["lineages"] if l["steps"]]
    if not lins:
        return None
    color = STIFFNESS_COLORS.get(search["level"], "#2a78d6")
    spans = sorted({l["half_span"] for l in search["lineages"]})
    fams = [f for f in FAMILY_ORDER if any(l["family"] == f for l in search["lineages"])]
    longest = max(len(l["steps"]) for l in lins)
    frames_idx = list(range(longest)) if longest <= max_frames else \
        sorted({round(i * (longest - 1) / (max_frames - 1)) for i in range(max_frames)})
    frames_idx += [longest - 1] * 8          # hold the final state
    allT = [s["thrust"] for l in lins for s in l["steps"] if s["thrust"] is not None]
    allM = [s["torque"] for l in lins for s in l["steps"] if s["torque"] is not None]
    xmax, ymax = max(allM + [target]) * 1.08, max(allT) * 1.1
    images = []
    for k in frames_idx:
        fig = plt.figure(figsize=(13, 6.4))
        gs = fig.add_gridspec(len(fams), len(spans) + 1, width_ratios=[1] * len(spans) + [len(spans) * 0.95],
                              hspace=0.35, wspace=0.12)
        for i, fam in enumerate(fams):
            for j, hs in enumerate(spans):
                ax = fig.add_subplot(gs[i, j]); ax.axis("off")
                lin = next((l for l in search["lineages"] if l["family"] == fam and abs(l["half_span"] - hs) < 1e-9), None)
                if lin is None or not lin["steps"]:
                    ax.text(0.5, 0.5, "invalid seed" if lin else "", ha="center", fontsize=7, color=INK2, transform=ax.transAxes)
                    continue
                seed, cur = lin["steps"][0], lin["steps"][min(k, len(lin["steps"]) - 1)]

                def poly(st):
                    ch, n = st["chords"], len(st["chords"])
                    xs = [st["half_span"] * q / (n - 1) for q in range(n)]
                    return xs + xs[::-1] + [xs[0]], [0.0] * n + [-c for c in ch][::-1] + [0.0]
                x0, y0 = poly(seed); x1, y1 = poly(cur)
                ax.plot(x0, y0, color="#b9b8b2", lw=0.8)
                ax.fill(x1, y1, color=color, alpha=0.3, lw=0); ax.plot(x1, y1, color=color, lw=1.3)
                ax.set_xlim(-0.01, 0.41); ax.set_ylim(-0.21, 0.01); ax.set_aspect("equal")
                ax.set_title(f"{cur['thrust']:.2f} N · {cur['torque']:.2f} N·m", fontsize=7, color=INK2, pad=1)
                if j == 0:
                    ax.text(-0.04, -0.1, fam, ha="right", va="center", fontsize=8, color=INK, transform=ax.transData)
                if i == len(fams) - 1:
                    ax.text(0.2, -0.26, f"seed {hs * 1000:.0f} mm", ha="center", fontsize=7, color=INK2)
        axp = fig.add_subplot(gs[:, -1])
        for lin in lins:
            st = lin["steps"][: min(k, len(lin["steps"]) - 1) + 1]
            axp.plot([s["torque"] for s in st], [s["thrust"] for s in st], "-", color=color, lw=0.9, alpha=0.6)
            axp.plot([st[0]["torque"]], [st[0]["thrust"]], "o", ms=3, color="#b9b8b2")
            axp.plot([st[-1]["torque"]], [st[-1]["thrust"]], "o", ms=4.5, color=color, mec="white", mew=0.6)
        axp.axvline(target, color=INK2, ls=(0, (5, 4)), lw=1)
        axp.set_xlim(0, xmax); axp.set_ylim(0, ymax); axp.grid(True, color=GRID, lw=0.6)
        axp.set_xlabel("Peak root torque (N·m)"); axp.set_ylabel("Mean thrust (N)")
        axp.set_title("Lineage paths (grey = seed, colour = current)", loc="left", fontsize=9)
        fig.suptitle(f"{search['id']}   accepted step {min(k + 1, longest)} / {longest}   "
                     f"({search['status']})", x=0.01, ha="left", fontsize=12)
        buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=72, facecolor="white"); plt.close(fig)
        buf.seek(0); images.append(Image.open(buf).convert("P", palette=Image.ADAPTIVE))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(out_path, save_all=True, append_images=images[1:], duration=180, loop=0, optimize=True)
    return out_path


def objective_label(objective: str) -> dict:
    """What a search optimised, in the atlas's words. lambda_* searches score
    S = T/Tref - lambda * M/Mref; torque_1Nm maximises thrust subject to the budget."""
    if objective.startswith("lambda_"):
        lam = float(objective.split("_", 1)[1])
        return {"objective": objective, "lambda": lam, "label": f"λ = {lam:g} (score T/Tref − {lam:g}·M/Mref)"}
    if objective == "torque_1Nm":
        return {"objective": objective, "lambda": None, "label": "max thrust with peak torque ≤ 1 N·m (no λ)"}
    return {"objective": objective, "lambda": None, "label": objective}


def lineages_reaching(db, key: str) -> list[tuple[str, str, int]]:
    """(search_id, lineage, seq) for every accepted step that is this design."""
    return [tuple(r) for r in db.execute("select search_id,lineage,seq from accepted where key=? order by search_id,lineage,seq", (key,))]


def render_lineage_gif(search, lineage_id: str, upto_seq: int, out_path: Path, target=1.0, title=""):
    """One winner's evolution: its outline at every accepted step from the seed to the winning
    shape (to scale, earlier steps ghosted), beside the path it took in thrust-torque space."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image
    plt.rcParams.update({"font.family": "serif", "font.serif": ["Times New Roman", "DejaVu Serif"], "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False})
    lin = next(l for l in search["lineages"] if l["id"] == lineage_id)
    steps = [s for s in lin["steps"] if s["seq"] <= upto_seq and s["thrust"] is not None]
    if not steps:
        return None
    color = STIFFNESS_COLORS.get(search["level"], "#2a78d6")

    def poly(st):
        ch, n = st["chords"], len(st["chords"])
        xs = [1000 * st["half_span"] * q / (n - 1) for q in range(n)]
        return xs + xs[::-1] + [xs[0]], [0.0] * n + [-1000 * c for c in ch][::-1] + [0.0]
    xmax = max(1000 * s["half_span"] for s in steps) * 1.05
    ymin = -max(1000 * max(s["chords"]) for s in steps) * 1.08
    T = [s["thrust"] for s in steps]
    M = [s["torque"] for s in steps]
    images = []
    for k in list(range(len(steps))) + [len(steps) - 1] * 10:      # hold the winning shape
        st = steps[k]
        fig, (ax, axp) = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw={"width_ratios": [1.45, 1]})
        for j in range(k):
            x, y = poly(steps[j])
            ax.plot(x, y, color=color, lw=0.7, alpha=0.08 + 0.25 * j / max(k, 1))
        x0, y0 = poly(steps[0]); ax.plot(x0, y0, color="#b9b8b2", lw=1.0, ls=(0, (4, 3)))
        x1, y1 = poly(st); ax.fill(x1, y1, color=color, alpha=0.28, lw=0); ax.plot(x1, y1, color=color, lw=1.6)
        ax.set_xlim(-5, xmax); ax.set_ylim(ymin, 8); ax.set_aspect("equal")
        ax.set_xlabel("Span from root (mm)"); ax.set_ylabel("Chord (mm)")
        ax.set_title(f"{'Seed' if k == 0 else 'Step ' + str(k)} of {len(steps) - 1}:  {st['thrust']:.3f} N at "
                     f"{st['torque']:.3f} N·m,  {1000 * st['half_span']:.0f} mm half-span", loc="left", fontsize=10)
        axp.plot(M[:k + 1], T[:k + 1], "-", color=color, lw=1.2)
        axp.plot(M[:k + 1], T[:k + 1], "o", ms=3, color=color, alpha=0.5)
        axp.plot([M[0]], [T[0]], "o", ms=5, color="#b9b8b2")
        axp.plot([M[k]], [T[k]], "o", ms=7, color=color, mec="white", mew=0.8)
        axp.axvline(target, color=INK2, ls=(0, (5, 4)), lw=1)
        axp.set_xlim(0, max(M + [target]) * 1.1); axp.set_ylim(0, max(T) * 1.12); axp.grid(True, color=GRID, lw=0.6)
        axp.set_xlabel("Peak root torque (N·m)"); axp.set_ylabel("Mean thrust (N)")
        axp.set_title("Path in thrust–torque space", loc="left", fontsize=10)
        fig.suptitle(title or search["id"], x=0.01, ha="left", fontsize=12, color=INK)
        fig.tight_layout(rect=(0, 0, 1, 0.93))
        buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=80, facecolor="white"); plt.close(fig)
        buf.seek(0); images.append(Image.open(buf).convert("P", palette=Image.ADAPTIVE))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(out_path, save_all=True, append_images=images[1:], duration=350, loop=0, optimize=True)
    return out_path


def atlas_winners(campaign: Path, study: str, atlas: Path) -> int:
    """Render the evolution of every top-performing wing of `study` that a search found.

    Writes atlas/media/evolution/<study>/<key16>.gif and index.json (search, objective,
    λ, lineage, number of steps); the site build attaches these to the winners."""
    meta = json.loads((atlas / "data" / "meta.json").read_text(encoding="utf-8"))
    db = connect(campaign)
    out = atlas / "media" / "evolution" / study
    index_path = out / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    cache = {}
    n = 0
    for w in meta["winners"]:
        if w.get("study") != study or not w.get("key"):
            continue
        hits = lineages_reaching(db, w["key"])
        if not hits:
            print(f"  {w['model']} {w['freq']:g} Hz {w['key'][:16]}: not reached by any search (shape map or seed only)")
            continue
        entries = []
        for sid, lid, seq in hits:
            if sid not in cache:
                cache[sid] = load_search(db, sid)
            s = cache[sid]
            lin = next(l for l in s["lineages"] if l["id"] == lid)
            entries.append((sum(1 for x in lin["steps"] if x["seq"] <= seq), sid, lid, seq, s, lin))
        entries.sort(key=lambda e: -e[0])            # show the longest path to this design
        steps, sid, lid, seq, s, lin = entries[0]
        obj = objective_label(s["objective"])
        title = (f"{s['level']} · {s['freq']:g} Hz · {obj['label']} · lineage {lin['family']}, "
                 f"seed {1000 * lin['half_span']:.0f} mm")
        gif = out / f"{w['key'][:16]}.gif"
        render_lineage_gif(s, lid, seq, gif, title=title)
        index[w["key"][:16]] = {"gif": f"evolution/{study}/{gif.name}", "search": sid, **obj,
                                "lineage": lid, "family": lin["family"], "seed_half_span_mm": round(1000 * lin["half_span"], 1),
                                "steps": steps - 1, "also": sorted({e[1] for e in entries[1:]})}
        n += 1
        print(f"  {w['model']} {w['freq']:g} Hz -> {gif.name} ({sid}, {steps - 1} steps)")
    db.close()
    out.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(index, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("campaign", type=Path)
    ap.add_argument("--search", action="append", help="search id (repeatable); default: all with accepted steps")
    ap.add_argument("--check", action="store_true", help="print the sanity summary only")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--atlas-winners", metavar="STUDY",
                    help="render the evolution of each top performer of this atlas study (rod, weekend) into atlas/media/evolution")
    a = ap.parse_args(argv)
    if a.atlas_winners:
        root = HERE.parent
        print(f"{atlas_winners(a.campaign, a.atlas_winners, root / 'atlas')} evolution animations written")
        return
    db = connect(a.campaign)
    ids = a.search or [r[0] for r in db.execute("select search_id from searches order by phase, search_id")]
    out_dir = a.out or a.campaign / "evolution"
    for sid in ids:
        s = load_search(db, sid)
        for line in check(s):
            print(line)
        if not a.check:
            p = render_gif(s, out_dir / (sid.replace("/", "__").replace("@", "_") + ".gif"))
            if p:
                print(f"    -> {p}")


if __name__ == "__main__":
    main()
