"""Evolution GIFs and sanity checks for elastic campaign searches (read-only, safe while running).

  python WingStudy/elastic_evolution.py CAMPAIGN_DIR --check            # text summary of every search
  python WingStudy/elastic_evolution.py CAMPAIGN_DIR                    # GIFs for every search with progress
  python WingStudy/elastic_evolution.py CAMPAIGN_DIR --search "t0.50@1Hz/torque_1Nm"

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
from elastic_figures import STIFFNESS_COLORS, INK, INK2, GRID  # noqa: E402

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


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("campaign", type=Path)
    ap.add_argument("--search", action="append", help="search id (repeatable); default: all with accepted steps")
    ap.add_argument("--check", action="store_true", help="print the sanity summary only")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
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
