"""Static figures for elastic studies (PNG), sharing the dashboard's stiffness colors.

  thrust_torque_paths   one line per wing through thrust-torque space as the plate softens
  chunk_report          end-of-chunk summary: every design at that frequency + best per stiffness
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

# Rigid is a neutral reference; then stiff -> soft runs cool -> warm (matches the dashboard).
STIFFNESS_COLORS = {"rigid": "#6b6a66", "t1.00": "#4b4bc8", "t0.50": "#2a78d6", "t0.40": "#1a9e8f",
                    "t0.30": "#6aa121", "t0.25": "#e08a00", "t0.20": "#d9502a"}
LABEL_TO_ID = {"Rigid": "rigid", "1.0mm": "t1.00", "0.5mm": "t0.50", "0.4mm": "t0.40", "0.3mm": "t0.30",
               "0.25mm": "t0.25", "0.2mm": "t0.20"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e8e7e2"


def _style():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "serif", "font.serif": ["Times New Roman", "DejaVu Serif"], "font.size": 10,
                         "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#9a9993",
                         "axes.labelcolor": INK, "xtick.color": INK2, "ytick.color": INK2})
    return plt


def thrust_torque_paths(rows, out_path, title="Plate stiffness moves each wing through thrust-torque space",
                        target=1.0):
    """rows: dicts with wing, level (label like '0.5mm' or id), status, thrust, torque and
    optional *_range min/max. One line per wing ordered rigid -> softest; marker color =
    stiffness; hollow markers + bars = uncertain."""
    plt = _style()
    rows = [dict(r, thrust=r.get("thrust", r.get("mean_thrust_N")), torque=r.get("torque", r.get("peak_abs_root_torque_Nm")))
            for r in rows]
    wing_style = {"Top #7657": ("-", "o"), "Middle #3894": ("--", "s"), "Rectangle #7835": ("-.", "^")}
    order = ["rigid", "t1.00", "t0.50", "t0.40", "t0.30", "t0.25", "t0.20"]
    labels = {"rigid": "Rigid", "t1.00": "1.0 mm", "t0.50": "0.5 mm", "t0.40": "0.4 mm", "t0.30": "0.3 mm",
              "t0.25": "0.25 mm", "t0.20": "0.2 mm"}
    fig, ax = plt.subplots(figsize=(9.5, 6.2))
    used = set()
    for wing in dict.fromkeys(r["wing"] for r in rows):
        pts = []
        for r in rows:
            if r["wing"] != wing or r.get("status") not in ("ok", "verified", "uncertain") or r.get("thrust") is None:
                continue
            lid = LABEL_TO_ID.get(r["level"], r["level"])
            pts.append((order.index(lid), lid, r))
        pts.sort()
        ls, mk = wing_style.get(wing, ("-", "o"))
        ax.plot([p[2]["torque"] for p in pts], [p[2]["thrust"] for p in pts], ls, color="#8a8984", lw=1.4, zorder=1)
        for _, lid, r in pts:
            c = STIFFNESS_COLORS[lid]; used.add(lid)
            if r["status"] == "uncertain":
                ax.errorbar(r["torque"], r["thrust"],
                            xerr=[[r["torque"] - r["torque_range_Nm_min"]], [r["torque_range_Nm_max"] - r["torque"]]],
                            yerr=[[r["thrust"] - r["thrust_range_N_min"]], [r["thrust_range_N_max"] - r["thrust"]]],
                            fmt=mk, ms=9, mfc="white", mec=c, mew=2, ecolor=c, elinewidth=1.4, capsize=3, zorder=3)
            else:
                ax.plot(r["torque"], r["thrust"], mk, ms=9, color=c, mec="white", mew=1.2, zorder=3)
        start = pts[0][2] if pts else None
        if start:
            ax.annotate(wing, (start["torque"], start["thrust"]), xytext=(8, 6), textcoords="offset points",
                        fontsize=10, color=INK, weight="bold")
    ax.axvline(target, color=INK2, ls=(0, (5, 4)), lw=1)
    ax.set_ylim(bottom=0)
    ax.text(target, 0.02 * ax.get_ylim()[1], f" {target:g} N·m target", va="bottom", fontsize=9, color=INK2)
    ax.set_xlabel("Peak root torque per wing (N·m)")
    ax.set_ylabel("Mean thrust per wing (N)")
    ax.set_xlim(left=0); ax.set_ylim(bottom=0)
    ax.grid(True, color=GRID, lw=0.7)
    from matplotlib.lines import Line2D
    handles = [Line2D([], [], marker="o", ls="", ms=9, color=STIFFNESS_COLORS[l], mec="white", label=labels[l])
               for l in order if l in used]
    handles += [Line2D([], [], color="#8a8984", ls=wing_style[w][0], marker=wing_style[w][1], mfc="#8a8984", label=w)
                for w in wing_style if any(r["wing"] == w for r in rows)]
    ax.legend(handles=handles, frameon=False, fontsize=9, loc="upper left", ncol=2, title="Plate stiffness · wing",
              title_fontsize=9)
    fig.suptitle(title, x=0.01, ha="left", fontsize=13)
    fig.text(0.01, 0.01, "Each line runs from rigid to the softest plain-weave plate. Marker colour = plate stiffness; marker shape = wing.\n"
             "Hollow + bars = uncertain (range over stabilization settings). 1 Hz, 0.5 m/s, 30° stroke; G = 4.5 GPa, E = 50 GPa; twist about the leading edge.",
             fontsize=8, color=INK2)
    fig.tight_layout(rect=(0, 0.07, 1, 0.95))
    fig.savefig(out_path, dpi=200, facecolor="white")
    plt.close(fig)
    return out_path


def chunk_report(db_path, plan, chunk, out_dir) -> str:
    """Summary PNG for one finished chunk (one frequency). Returns path relative to the campaign dir."""
    plt = _style()
    out_dir = Path(out_dir); out_dir.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    f, target = chunk["freq"], plan["torque_target_nm"]
    rows = db.execute("select key,level,status,thrust,torque,chords,half_span,tip_twist from designs "
                      "where abs(freq-?)<1e-9 and numerics='base' and thrust is not null", (f,)).fetchall()
    counts = dict(db.execute("select status,count(*) from designs where abs(freq-?)<1e-9 and numerics='base' group by status", (f,)).fetchall())
    levels = plan["levels"]
    fig = plt.figure(figsize=(14, 6.6))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.45, 1], wspace=0.18)
    ax = fig.add_subplot(gs[0, 0])
    best = {}
    for lv in levels:                                    # stiff first, soft on top
        pts = [r for r in rows if r[1] == lv["id"]]
        c = STIFFNESS_COLORS.get(lv["id"], "#2a78d6")
        good = [r for r in pts if r[2] in ("verified", "ok")]
        unc = [r for r in pts if r[2] == "uncertain"]
        ax.scatter([r[4] for r in good], [r[3] for r in good], s=9, color=c, alpha=0.55, lw=0, label=lv["label"])
        if unc:
            ax.scatter([r[4] for r in unc], [r[3] for r in unc], s=14, facecolors="none", edgecolors=c, lw=0.8, alpha=0.8)
        feas = [r for r in good if r[4] <= target]
        if feas:
            best[lv["id"]] = max(feas, key=lambda r: r[3])
    for lid, r in best.items():
        ax.scatter([r[4]], [r[3]], s=150, marker="*", color=STIFFNESS_COLORS.get(lid), edgecolors=INK, lw=0.8, zorder=5)
    ax.axvline(target, color=INK2, ls=(0, (5, 4)), lw=1)
    ax.set_xlabel("Peak root torque per wing (N·m)"); ax.set_ylabel("Mean thrust per wing (N)")
    ax.set_xlim(left=0); ax.grid(True, color=GRID, lw=0.7)
    leg = ax.legend(frameon=False, fontsize=9, loc="upper left", markerscale=2.5, title="Plate stiffness", title_fontsize=9)
    ax.set_title(f"Every design at {f:g} Hz (large star = highest thrust at ≤ {target:g} N·m)", loc="left", fontsize=11)
    # Best shapes, physical scale, one row per stiffness.
    axs = fig.add_subplot(gs[0, 1])
    axs.set_title(f"Best shape at ≤ {target:g} N·m, to scale", loc="left", fontsize=11)
    y = 0.0
    for lv in levels:
        r = best.get(lv["id"])
        c = STIFFNESS_COLORS.get(lv["id"], "#2a78d6")
        axs.text(-0.02, y - 0.03, lv["label"], ha="right", va="top", fontsize=10, color=INK, weight="bold")
        if r:
            ch = json.loads(r[5]); hs = r[6]; n = len(ch)
            xs = [hs * i / (n - 1) for i in range(n)]
            axs.fill(xs + xs[::-1], [y] * n + [y - c_ for c_ in ch][::-1], color=c, alpha=0.3, lw=0)
            axs.plot(xs + xs[::-1] + [xs[0]], [y] * n + [y - c_ for c_ in ch][::-1] + [y], color=c, lw=1.6)
            tw = f"\ntip twist ±{r[7]:.0f}°" if r[7] is not None else ""
            axs.text(-0.02, y - 0.075, f"{r[3]:.2f} N at {r[4]:.2f} N·m\n{hs * 1000:.0f} mm half-span{tw}",
                     ha="right", va="top", fontsize=8.5, color=INK2)
        else:
            axs.text(0.0, y - 0.1, "no verified design ≤ target", va="center", fontsize=9, color=INK2)
        y -= 0.26
    axs.set_xlim(-0.2, 0.42); axs.set_ylim(y + 0.04, 0.03); axs.set_aspect("equal"); axs.axis("off")
    total = sum(counts.values())
    q = ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))
    fig.suptitle(f"{chunk['title']}: {total:,} designs", x=0.01, ha="left", fontsize=14)
    fig.text(0.01, 0.01, f"Result quality: {q}. Filled = verified elastic / settled rigid; hollow = uncertain. "
             "Plain weave G = 4.5 GPa, E = 50 GPa; root chord 200 mm; 0.5 m/s, 30° stroke.", fontsize=8.5, color=INK2)
    fig.subplots_adjust(left=0.06, right=0.98, top=0.88, bottom=0.1)
    name = f"chunk_{chunk['id']}_{f:g}Hz.png"
    fig.savefig(out_dir / name, dpi=170, facecolor="white")
    plt.close(fig)
    db.close()
    return f"reports/{name}"
