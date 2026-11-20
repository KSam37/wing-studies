"""Process report for the elastic wing study (PDF). Re-run any time; results sections fill in
from the campaign database as chunks finish (read-only, safe while the campaign runs).

  python -m wingstudy.elastic_report [CAMPAIGN_DIR] [--out PDF]
"""
from __future__ import annotations

import argparse
import io
import json
import math
import sqlite3
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from .elastic_figures import STIFFNESS_COLORS, INK, INK2, GRID  # noqa: E402

CAMPAIGN = ROOT / "outputs" / "elastic" / "campaigns" / "weekend"
STIFF = ROOT / "outputs" / "elastic" / "stiffness"

# ----------------------------------------------------------------------------------------
# Figures generated for the report
# ----------------------------------------------------------------------------------------


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family": "serif", "font.serif": ["DejaVu Serif"], "font.size": 9,
                         "axes.spines.top": False, "axes.spines.right": False})
    return plt


def fig_model(out):
    """Planform discretization and the torsional strip chain."""
    plt = _plt()
    fig, (a, b) = plt.subplots(1, 2, figsize=(10, 3.6), gridspec_kw={"width_ratios": [1.25, 1]})
    ch = [0.200, 0.166, 0.072, 0.061, 0.045, 0.037, 0.025, 0.022]
    hs = 0.40
    ys = [hs * i / 7 for i in range(8)]
    a.fill(ys + ys[::-1], [0] * 8 + [-c for c in ch][::-1], color="#2a78d6", alpha=0.18, lw=0)
    a.plot(ys + ys[::-1] + [0], [0] * 8 + [-c for c in ch][::-1] + [0], color="#2a78d6", lw=1.4)
    for y, c in zip(ys, ch):
        a.plot([y, y], [0, -c], color="#2a78d6", lw=0.6, ls=":")
        a.plot([y], [-c], "o", ms=4, color="#2a78d6")
    a.plot([0, hs], [0, 0], color=INK, lw=2.4)
    a.annotate("leading edge = twist axis (straight)", (0.24, 0.0), xytext=(0.2, 0.05), fontsize=8,
               arrowprops=dict(arrowstyle="-", color=INK2, lw=0.6))
    a.annotate("root chord fixed at 200 mm\n(mount)", (0, -0.1), xytext=(-0.13, -0.16), fontsize=8,
               arrowprops=dict(arrowstyle="-", color=INK2, lw=0.6))
    a.annotate("8 chord stations, equally spaced;\nchords non-increasing toward tip;\n>= 10 mm or zero (tip may shorten)",
               (ys[4], -ch[4]), xytext=(0.17, -0.2), fontsize=8, arrowprops=dict(arrowstyle="-", color=INK2, lw=0.6))
    a.annotate("", (0.05, 0.075), xytext=(0.0, 0.075), arrowprops=dict(arrowstyle="->", color=INK2))
    a.text(0.0, 0.085, "flapping axis at root (x along chord, y along span)", fontsize=7.5, color=INK2)
    a.set_xlim(-0.16, 0.44); a.set_ylim(-0.25, 0.11); a.set_aspect("equal"); a.axis("off")
    a.set_title("(a) Half-wing geometry: 0.5 mm best design at 1 Hz, to scale", loc="left", fontsize=9)
    # (b) strip chain
    n = 6
    for j in range(n):
        x0 = 0.1 + j * 0.15
        b.add_patch(plt.Rectangle((x0, 0.2), 0.12, 0.5 - 0.05 * j, color="#2a78d6", alpha=0.25, lw=0))
        b.text(x0 + 0.06, 0.12, f"strip {j + 1}", ha="center", fontsize=7, color=INK2)
        if j < n - 1:
            xs = [x0 + 0.115 + 0.04 * k / 10 for k in range(11)]
            b.plot(xs, [0.8 + (0.03 * (-1) ** k if 0 < k < 10 else 0) for k in range(11)], color=INK, lw=0.9)
    b.plot([0.04, 0.04], [0.1, 0.9], color=INK, lw=3)
    b.text(0.03, 0.93, "root (clamped)", fontsize=7.5)
    b.text(0.1, 0.97, r"torsion springs $k_j = G\,c_j t^3/(3\,\Delta y)$  +  warping $E\Gamma\,\phi''$", fontsize=8.5)
    b.text(0.1, 0.02, "each joint carries the UVLM pitching moment of every strip outboard of it", fontsize=7.5, color=INK2)
    b.set_xlim(0, 1.05); b.set_ylim(0, 1.05); b.axis("off")
    b.set_title("(b) Structural model: chain of rigid strips twisting about the LE", loc="left", fontsize=9)
    fig.tight_layout()
    fig.savefig(out, dpi=200, facecolor="white"); plt.close(fig)


def fig_seeds(out):
    from . import elastic_campaign as EC
    plt = _plt()
    p = EC.default_plan()
    spans = [0.15, 0.28, 0.40]
    fig, axes = plt.subplots(len(spans), 5, figsize=(10, 3.4))
    for i, hs in enumerate(spans):
        for j, fam in enumerate(EC.FAMILIES):
            ax = axes[i][j]; ch = EC.seed_chords(p, fam); n = len(ch)
            ys = [hs * q / (n - 1) for q in range(n)]
            ax.fill(ys + ys[::-1], [0] * n + [-c for c in ch][::-1], color="#6b6a66", alpha=0.25, lw=0)
            ax.plot(ys + ys[::-1] + [0], [0] * n + [-c for c in ch][::-1] + [0], color="#6b6a66", lw=1)
            ax.set_xlim(-0.01, 0.41); ax.set_ylim(-0.21, 0.01); ax.set_aspect("equal"); ax.axis("off")
            if i == 0:
                ax.set_title(fam, fontsize=9)
            if j == 0:
                ax.text(-0.03, -0.1, f"{hs * 1000:.0f} mm", ha="right", va="center", fontsize=8)
    fig.suptitle("Seed families (columns) at three of the five starting half-spans (rows), to scale", fontsize=9, x=0.01, ha="left")
    fig.tight_layout(rect=(0.03, 0, 1, 0.95))
    fig.savefig(out, dpi=200, facecolor="white"); plt.close(fig)


def fig_evolution_still(db_path, sid, out):
    """Last frame of the evolution animation for one search."""
    from . import elastic_evolution as EV
    from PIL import Image
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    s = EV.load_search(db, sid)
    tmp = Path(out).with_suffix(".gif")
    EV.render_gif(s, tmp, max_frames=2)
    im = Image.open(tmp); im.seek(im.n_frames - 1); im.convert("RGB").save(out)
    tmp.unlink()


def fig_rechecks(db_path, out):
    """Finalist re-check deltas (16 spanwise panels) per frequency."""
    plt = _plt()
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    rows = db.execute("select b.level,b.freq,s.objective,b.thrust,b.torque,d.numerics,d.status,d.thrust,d.torque "
                      "from rechecks x join designs d on d.key=x.key join designs b on b.key=x.base_key "
                      "join searches s on s.search_id=x.search_id where d.numerics='span16' and b.thrust>0.05").fetchall()
    if not rows:
        return False
    fig, ax = plt.subplots(figsize=(7, 3.2))
    for lv, f, obj, t0, m0, num, st, t1, m1 in rows:
        if t1 is None:
            continue
        c = STIFFNESS_COLORS.get(lv, "#888")
        ax.plot(100 * (m1 - m0) / m0, 100 * (t1 - t0) / t0, "o", ms=6, color=c, mec="white")
    ax.axhline(0, color=GRID); ax.axvline(0, color=GRID)
    ax.set_xlabel("Peak root torque change, 8 -> 16 spanwise panels (%)")
    ax.set_ylabel("Mean thrust change (%)")
    from matplotlib.lines import Line2D
    used = sorted({r[0] for r in rows}, key=list(STIFFNESS_COLORS).index)
    ax.legend(handles=[Line2D([], [], marker="o", ls="", color=STIFFNESS_COLORS[l], label=l) for l in used],
              frameon=False, fontsize=8, loc="upper left")
    ax.grid(True, color=GRID, lw=0.6)
    fig.tight_layout(); fig.savefig(out, dpi=200, facecolor="white"); plt.close(fig)
    return True


# ----------------------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------------------


def campaign_data(camp: Path):
    db = sqlite3.connect(f"file:{camp / 'campaign.sqlite'}?mode=ro", uri=True)
    plan = json.loads(db.execute("select v from meta where k='plan'").fetchone()[0])
    done_chunks = json.loads((db.execute("select v from meta where k='chunks_done'").fetchone() or ["[]"])[0] or "[]")
    chunks = []
    for c in plan["chunks"]:
        f = c["freq"]
        searches = db.execute("select count(*), sum(status='complete') from searches where abs(freq-?)<1e-9", (f,)).fetchone()
        n_planned = sum(len(p.get("searches", [])) for p in plan["phases"] if p.get("chunk") == c["id"])
        complete = (c["id"] in [str(x) for x in done_chunks]) or (searches[0] == n_planned and searches[1] == n_planned
                                                                  and (camp / "reports" / f"chunk_{c['id']}_{f:g}Hz.png").exists())
        counts = dict(db.execute("select status,count(*) from designs where abs(freq-?)<1e-9 and numerics='base' group by status", (f,)).fetchall())
        best = []
        for lv in plan["levels"]:
            r = db.execute("select key,thrust,torque,chords,half_span,tip_twist,status from designs where level=? and abs(freq-?)<1e-9 "
                           "and numerics='base' and status in ('verified','ok') and torque<=? order by thrust desc limit 1",
                           (lv["id"], f, plan["torque_target_nm"])).fetchone()
            src = db.execute("select group_concat(distinct source) from uses where key=?", (r[0],)).fetchone()[0] if r else None
            best.append((lv, r, src))
        winners = db.execute("select s.objective,s.level,d.thrust,d.torque from searches s left join designs d on d.key=s.best_key "
                             "where abs(s.freq-?)<1e-9 order by s.level,s.objective", (f,)).fetchall()
        steps = db.execute("select count(*) from accepted a join searches s on s.search_id=a.search_id where abs(s.freq-?)<1e-9", (f,)).fetchone()[0]
        chunks.append({"chunk": c, "complete": complete, "counts": counts, "best": best, "winners": winners, "steps": steps,
                       "report": camp / "reports" / f"chunk_{c['id']}_{f:g}Hz.png"})
    times = dict(db.execute("select level,avg(elapsed) from designs where numerics='base' group by level").fetchall())
    return plan, chunks, times


# ----------------------------------------------------------------------------------------
# PDF
# ----------------------------------------------------------------------------------------


def build(camp: Path, out_pdf: Path):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
                                    TableStyle, ListFlowable, ListItem)

    fdir = Path("/usr/share/fonts/truetype/dejavu")
    if not (fdir / "DejaVuSerif.ttf").exists():
        import matplotlib
        fdir = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
    pdfmetrics.registerFont(TTFont("Serif", str(fdir / "DejaVuSerif.ttf")))
    pdfmetrics.registerFont(TTFont("Serif-Bold", str(fdir / "DejaVuSerif-Bold.ttf")))
    pdfmetrics.registerFont(TTFont("Serif-Italic", str(fdir / "DejaVuSerif-Italic.ttf") if (fdir / "DejaVuSerif-Italic.ttf").exists()
                                   else str(fdir / "DejaVuSerif.ttf")))
    pdfmetrics.registerFont(TTFont("Mono", str(fdir / "DejaVuSansMono.ttf")))
    from reportlab.lib.fonts import addMapping
    addMapping("Serif", 0, 0, "Serif"); addMapping("Serif", 1, 0, "Serif-Bold")
    addMapping("Serif", 0, 1, "Serif-Italic"); addMapping("Serif", 1, 1, "Serif-Bold")

    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["Normal"], fontName="Serif", fontSize=9.4, leading=13.2, spaceAfter=5)
    small = ParagraphStyle("s", parent=body, fontSize=8, leading=10.5, textColor=colors.HexColor(INK2))
    cap = ParagraphStyle("c", parent=small, spaceBefore=2, spaceAfter=10)
    h1 = ParagraphStyle("h1", parent=body, fontName="Serif-Bold", fontSize=14, leading=18, spaceBefore=12, spaceAfter=6)
    h2 = ParagraphStyle("h2", parent=body, fontName="Serif-Bold", fontSize=11, leading=14, spaceBefore=8, spaceAfter=4)
    title = ParagraphStyle("t", parent=body, fontName="Serif-Bold", fontSize=19, leading=24, spaceAfter=4)
    eq = ParagraphStyle("e", parent=body, alignment=TA_CENTER, fontName="Serif-Italic", spaceBefore=2, spaceAfter=7)
    code = ParagraphStyle("k", parent=body, fontName="Mono", fontSize=7.8, leading=10, leftIndent=12,
                          backColor=colors.HexColor("#f3f2ee"), borderPadding=4, spaceAfter=8)
    cell = ParagraphStyle("cell", parent=body, fontSize=8, leading=10, spaceAfter=0)
    cellb = ParagraphStyle("cellb", parent=cell, fontName="Serif-Bold")

    W = 7.0 * inch
    fig_no = [0]
    story = []
    P = lambda t, s=body: story.append(Paragraph(t, s))
    H1 = lambda t: story.append(Paragraph(t, h1))
    H2 = lambda t: story.append(Paragraph(t, h2))
    EQ = lambda t: story.append(Paragraph(t, eq))

    def bullets(items):
        story.append(ListFlowable([ListItem(Paragraph(i, body), leftIndent=12, value="•") for i in items],
                                  bulletType="bullet", start="•", leftIndent=12, bulletFontName="Serif"))

    def table(rows, widths, header=True, align_right_from=1):
        data = [[Paragraph(str(c), cellb if (header and i == 0) else cell) for c in r] for i, r in enumerate(rows)]
        t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
        st = [("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor(INK)), ("VALIGN", (0, 0), (-1, -1), "TOP"),
              ("LINEBELOW", (0, -1), (-1, -1), 0.4, colors.HexColor("#9a9993")),
              ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
        t.setStyle(TableStyle(st))
        story.append(t); story.append(Spacer(1, 8))

    def figure(path, caption, width=W):
        from PIL import Image as PI
        if not Path(path).exists():
            P(f"<i>[figure not available: {Path(path).name}]</i>", small); return
        import re as _re
        fig_no[0] += 1
        caption = f"<b>Figure {fig_no[0]}.</b> " + _re.sub(r"^Figure( \d+)?\.\s*", "", caption)
        w, h = PI.open(path).size
        story.append(KeepTogether([Image(str(path), width=width, height=width * h / w), Paragraph(caption, cap)]))

    figs = out_pdf.parent / "figures"; figs.mkdir(parents=True, exist_ok=True)
    fig_model(figs / "model.png")
    fig_seeds(figs / "seeds.png")
    db_path = camp / "campaign.sqlite"
    plan, chunks, times = campaign_data(camp)
    done = [c for c in chunks if c["complete"]]
    have_rechecks = fig_rechecks(db_path, figs / "rechecks.png")
    if done:
        try:
            fig_evolution_still(db_path, f"t0.50@{done[0]['chunk']['freq']:g}Hz/torque_1Nm", figs / "evolution.png")
        except Exception as exc:  # noqa: BLE001
            print("evolution still skipped:", exc)

    # ---------------- title ----------------
    P("Elastic carbon-fibre flapping wings in water", title)
    P("Process report: solver, structural model, verification and the design campaign", h2)
    P(f"Generated {time.strftime('%Y-%m-%d %H:%M')} from <font face='Mono'>{camp.relative_to(ROOT) if camp.is_relative_to(ROOT) else camp}</font>. "
      f"Chunks complete: {len(done)} of {len(chunks)}. Results sections update when this script is re-run.", small)
    story.append(Spacer(1, 6))

    H1("1  Summary")
    P("The rigid-wing coordinate studies chose wing outlines assuming a perfectly stiff plate. The real wings are "
      "waterjet- or laser-cut monolithic plain-weave carbon sheets of 0.5 or 0.25 mm. This work adds plate elasticity "
      "to the Ptera UVLM simulation, makes the coupled solve stable in water, measures each result's numerical uncertainty, "
      "checks the method on the three manufactured candidates, and runs a multi-day design campaign across stiffness and frequency.")
    bullets([
        "<b>Ptera's native aeroelastic solver cannot run these wings.</b> In water the fluid added inertia of a pitching strip is "
        "roughly 10–400× the strip's own inertia. Ptera's explicit (loosely coupled) update is unconditionally unstable at that ratio. "
        "Heavy damping hides this, but then the damper, not the carbon, sets the deformation.",
        "<b>The stabilized solver</b> moves an added-mass estimate to the structural side, integrates the strip chain implicitly "
        "(generalized-α), and models the plate as St. Venant torsion plus Vlasov warping. Ptera's own code is untouched; one "
        "method is overridden in a subclass.",
        "<b>Every elastic result reports its own reliability.</b> The stabilization factor is numerical and must not change the answer, "
        "so each design is solved at two factors. Agreement within 3% is <i>verified</i>; disagreement is kept as <i>uncertain</i> "
        "with a range, which is plotted as an error bar.",
        "<b>Flexibility matters a lot.</b> For the Top wing at 1 Hz, going from rigid to 0.5 mm drops thrust from 2.02 to 1.57 N and "
        "peak root torque from 1.00 to 0.66 N·m. At 0.25 mm the tip twists ±57° and thrust falls to 0.48 N.",
        "<b>The real wing has a 5/3 mm carbon tube bolted along the leading edge.</b> Modelled as torsional stiffness in parallel "
        "with the plate and held at the root, it makes the wing nearly rigid in twist (±1–2° at the tip) for either sheet (§8). "
        "Under a 1 N·m budget at 1 Hz, on the fine mesh, the best is <b>2.34 N (0.5 mm + tube, campaign outline at 344 mm "
        "half-span)</b>, against 2.28 N for the best rigid outline; at 1.25 Hz the campaign-mesh best is 2.63 N. The smooth-curve "
        "optimization did not beat the campaign outlines for these models. A second, budget-matched search from the geometry-sweep "
        "winner reached <b>2.42 N</b> (about +6%) by slimming the outer wing to the 10 mm minimum chord and lengthening it to 369 mm. "
        "That strip outline is at the model's edge; a less extreme intermediate gives 2.38 N (§10.1).",
        "<b>Without the tube, 0.5 mm reaches more thrust</b> (2.82 N refined at 1 Hz; up to about 3.6 N at 1.25 Hz), but only through "
        "±50–70° of passive tip twist. That is outside the model's small-deformation range and is mesh-sensitive by about 10%. "
        "Which model describes the hardware depends on how well the tube holds the plate; a bench twist test decides it (§13).",
        "<b>All winners put the 200 mm root chord to use and then taper fast</b> to a narrow outer wing, often at the 10 mm minimum "
        "chord. The bare-plate winners sit at the 400 mm maximum span; with the tube or rigid, the best spans are 286–400 mm, "
        "shorter at higher frequency.",
    ])

    # ---------------- setup ----------------
    H1("2  Simulation setup")
    P("One wing of the swimming robot is simulated in isolation (mirror-image loads assumed for the pair) with the "
      "unsteady ring-vortex-lattice method of PteraSoftware 5.1.0 (pinned upstream commit 17a98a10). Settings are inherited "
      "unchanged from the rigid studies (catalog case 7657), so rigid elastic-pipeline numbers reproduce the rigid catalog exactly.")
    table([["Quantity", "Value", "Note"],
           ["Fluid", "water, ρ = 998.2 kg/m³, ν = 1.004×10⁻⁶ m²/s", ""],
           ["Forward speed", "0.5 m/s", ""],
           ["Stroke", "custom waveform, −26° to +34° (≈30° amplitude)", "same as rigid studies"],
           ["Frequency", "1.0 Hz (design); 0.75 and 1.25 Hz in the campaign", ""],
           ["Time step", "dt = 1/(50 f): 50 steps per cycle (0.02 s at 1 Hz)", "refined automatically for soft plates (§4)"],
           ["Duration", "4 cycles (8 if not repeating)", "metrics from the last cycle"],
           ["Mesh", "8 spanwise × 4 chordwise (cosine) panels", "finalists re-checked at 16 spanwise"],
           ["Wake", "prescribed, 2 cycles retained", ""],
           ["Settled test", "last two cycles differ < 5% (forces and root torque)", "time-interpolated, any dt"],
           ["Metrics", "mean thrust per wing; peak |root roll moment| per wing", "'torque' below"]],
          [1.3 * inch, 3.2 * inch, 2.5 * inch])
    P("<b>Geometry.</b> The leading edge is straight and is the root-to-tip twist axis. Eight chord stations are spaced evenly "
      "along the half-span. The rules are the same as the rigid coordinate studies: the root chord is fixed at 200 mm "
      "(mechanical mount); chords never increase toward the tip; a positive chord is at least 10 mm; and zero chords "
      "may only form a contiguous tip suffix, which shortens the active span. Every design in the campaign database has "
      "exactly a 200 mm root chord (checked on all 16,661 records).")
    figure(figs / "model.png", "Figure 1. (a) Shape description used everywhere in this work. (b) The structural idealisation: "
           "each spanwise panel strip is rigid chordwise and twists about the leading edge; neighbouring strips are joined "
           "by torsion springs whose stiffness follows the local chord.")

    # ---------------- model ----------------
    H1("3  Structural model of the carbon plate")
    P("Ptera's aeroelastic mode treats each spanwise strip as a rigid body on a torsion spring about the leading edge, with "
      "one spring constant for all strips, each driven only by its own aerodynamic moment. That is not a plate: a real sheet's "
      "torsional stiffness depends on the local chord and thickness, and the twist at any station is driven by all the moment "
      "outboard of it. The plate model here keeps Ptera's kinematics (rigid strips, twist about the LE) and replaces the "
      "stiffness and loading.")
    H2("3.1  St. Venant torsion")
    P("A thin strip of chord <i>c</i> and thickness <i>t</i> has torsion constant <i>J</i> = <i>c t</i>³/3. Between stations "
      "<i>j</i> and <i>j</i>+1 (spacing Δ<i>y</i>) the relative twist spring is")
    EQ("k<sub>j</sub> = G c<sub>j</sub> t<sup>3</sup> / (3 Δy<sub>j</sub>)")
    P("and each joint carries the summed pitching moment of every strip outboard of it (the generalized force "
      "<b>L</b><super>T</super><b>M</b>, where <b>L</b> maps relative to absolute twist). Stiffness therefore follows the "
      "outline, so wings cut from the same sheet are compared fairly. Thickness enters as <i>t</i>³: halving the sheet "
      "from 0.5 to 0.25 mm makes it 8× softer in torsion.")
    H2("3.2  Warping (bending) stiffness")
    P("St. Venant torsion alone leaves a mode almost free in which neighbouring strips twist in opposite directions. A "
      "continuous plate resists that through bending. It is added as Vlasov warping stiffness, with strain energy "
      "½ <i>E</i>Γ(φ″)² along the span and Γ = <i>c</i>³<i>t</i>³/144 for a flat strip, with the root clamped (φ = φ′ = 0) "
      "and the tip free. This term was not in the first version. It was added after the wide Rectangle wing showed a "
      "zigzag instability (§5.3). It stiffens wide-chord regions, mostly near the root, and changed earlier results noticeably "
      "(Top at 0.5 mm: 1.34 → 1.57 N).")
    H2("3.3  Material")
    table([["Property", "Value", "Basis"],
           ["In-plane shear modulus G", "4.5 GPa", "plain-weave 0/90 carbon/epoxy (typical 3.5–5 GPa)"],
           ["Bending modulus E", "50 GPa", "plain-weave flexural modulus"],
           ["Density", "1550 kg/m³", ""],
           ["Structural damping", "2% of critical, stiffness-proportional at the flap frequency", "small; does not set the response"],
           ["Thickness levels", "rigid, 1.0, 0.5, 0.25, 0.2 mm", "0.5 and 0.25 mm are the stock sheets"]],
          [1.8 * inch, 2.4 * inch, 2.8 * inch])
    P("Torsion of a 0/90 woven sheet is governed by its low in-plane shear modulus. A ±45° layup would be about 4× stiffer in "
      "torsion. G is the single most influential input and is a literature value; a simple torsion test on an offcut of the "
      "actual sheet would remove the largest physical uncertainty in this study.")
    c, t = 0.2, 0.5e-3
    ratio = (27 * math.pi / 128) * 998.2 * c / (1550 * t)
    P(f"<b>Inertia.</b> Strip pitch inertia about the LE is ρ<sub>s</sub><i>t c</i>³Δ<i>y</i>/3. Inertial forcing uses the "
      f"strip's heave acceleration times its chordwise centre-of-mass offset. Both are small next to the fluid's added "
      f"inertia, (9π/128)ρ<i>c</i>⁴Δ<i>y</i> for a flat plate pitching about its leading edge. For a 200 mm chord at 0.5 mm the "
      f"ratio of added to structural inertia is {ratio:.0f}; at 0.25 mm it doubles.")

    # ---------------- stabilization ----------------
    H1("4  Making the coupled solve stable and checking it")
    H2("4.1  Why the native coupling diverges")
    P("Ptera advances the structure explicitly: the UVLM moment from step <i>n</i> drives the springs from <i>n</i> to "
      "<i>n</i>+1. In a partitioned fluid–structure solve this loose coupling is unconditionally unstable once the fluid's "
      "added mass exceeds the structure's (Causin, Gerbeau &amp; Nobile, 2005), whatever the time step. Here the ratio is "
      "10–400, so twist grows from step to step until Ptera rejects an angle beyond 90°. The earlier setup kept runs alive "
      "with a damping constant of 2.0 N·m·s/rad per strip. At 1 Hz the damper's impedance cω ≈ 12.6 N·m/rad is "
      "about 3× the 4.27 N·m/rad spring that was paired with it, and many times the stiffness of a real 0.5 mm strip (about 1–2 N·m/rad for a 200 mm chord), so the damper, not the carbon, "
      "was setting the deformation.")
    H2("4.2  The stabilized update (one overridden method)")
    bullets([
        "<b>Added-mass partitioning.</b> An analytic flat-plate estimate of each strip's added inertia, scaled by a factor "
        "α<sub>am</sub> (default 0.5), is moved to the structural left-hand side. The same estimate times the lagged structural "
        "acceleration is added back on the force side, so the correction cancels as the solution settles and the physics is unchanged. "
        "It acts on the backward second difference of twist, the same discrete operator through which the UVLM reports the "
        "fluid's inertial reaction one step later. A first version built on the Newmark acceleration did not match that operator "
        "and was less effective.",
        "<b>Implicit generalized-α integration</b> of the whole strip chain (ρ<sub>∞</sub> = 0.6): unconditionally stable "
        "for the structure, second-order accurate, one small linear solve per step, and faster than per-strip ODE integration.",
        "<b>Moments projected on each strip's actual leading-edge axis</b>, which rolls with the flap, rather than on the fixed "
        "geometric y-axis.",
        "<b>Start-up.</b> The aerodynamic load is ramped in over a quarter cycle after 5 discarded steps. A hard 80° twist "
        "limit flags runs where the small-deformation torsion model is out of its depth.",
    ])
    H2("4.3  Verification ladder: each result measures its own reliability")
    P("The factor α<sub>am</sub> is numerical. If the answer depends on it, the answer is not trustworthy. Every elastic design is "
      "therefore solved at α<sub>am</sub> = 0.5, then 0.4, 0.6, 0.35 and 0.7 as needed, until two settled runs agree within 3% on "
      "both thrust and peak torque.")
    table([["Status", "Meaning", "How it is used"],
           ["verified", "two factors settle and agree within 3%", "may become a search parent; plotted solid"],
           ["uncertain", "several settle but disagree; value = midpoint, range kept", "plotted hollow with error bars; never a parent"],
           ["unverified", "only one factor settled", "kept for the record; never a parent"],
           ["unresolved", "no factor settled", "kept for the record"]],
          [1.0 * inch, 3.0 * inch, 3.0 * inch])
    P("Two automatic retries come before giving up. A run that finishes but has not yet repeated cycle-to-cycle (slow structural "
      "mode on a soft plate) is re-run with twice the cycles. If it still does not verify, the time step is halved, then quartered. "
      "Stiff plates verify at the base step and never pay for retries. Soft plates frequently need dt/2 or dt/4 (§6).")
    H2("4.4  Checks on the method")
    table([["Check", "Result"],
           ["Rigid baseline through the elastic pipeline", "matches the rigid catalog to 5 decimals (2.01851 N, 0.99771 N·m)"],
           ["Very stiff plate → rigid limit", "within 0.01 N and 0.01 N·m of rigid"],
           ["Independence from α<sub>am</sub> on a realistic plate", "< 1% change in thrust across factors"],
           ["Time step (dt vs dt/2)", "2.5–5% on the validation wings"],
           ["Spanwise mesh (8 vs 16 panels)", "0.4–4% on the validation wings; 1–11% on campaign finalists (§7)"],
           ["Determinism and resume", "re-running from the cache reproduces the same searches and winners"]],
          [3.0 * inch, 4.0 * inch])
    P("The first three are automated tests (<font face='Mono'>tests/test_elastic.py</font>). Note that "
      "<i>verified</i> means numerically repeatable, not experimentally validated (§11).", small)

    # ---------------- validation ----------------
    H1("5  The three manufactured candidates")
    P("Top (#7657), Middle (#3894) and Rectangle (#7835) were each run at five stiffness levels at 1 Hz. #7835 is not "
      "in this repository's catalogs, so it was reconstructed as a 200 mm-chord rectangle whose span (187 mm) reproduces the "
      "recorded rigid loads (0.999 N·m peak torque, 0.78 N thrust).")
    table([["Wing", "Rigid", "1.0 mm", "0.5 mm", "0.25 mm", "0.2 mm"],
           ["Top #7657", "2.02 / 1.00", "1.96 / 0.94", "1.57 / 0.66", "0.48 / 0.16", "0.29 / 0.10"],
           ["Middle #3894", "1.51 / 1.00", "1.48 / 0.93", "1.28 / 0.64", "0.50 / 0.22", "0.34 / 0.14"],
           ["Rectangle #7835", "0.79 / 1.02", "1.20 / 1.13", "0.85 / 0.45", "0.29 / 0.12 (unc.)", "0.27 / 0.10 (unc.)"],
           ["Top tip twist", "0°", "±4°", "±26°", "±57°", "±60°"]],
          [1.3 * inch] + [1.14 * inch] * 5)
    P("Mean thrust (N) / peak root torque (N·m), 1 Hz. 'unc.' = uncertain, with ranges 0.28–0.30 N / 0.10–0.13 N·m and "
      "0.27–0.28 N / 0.09–0.11 N·m.", small)
    figure(STIFF / "stiffness_comparison.png", "Figure 2. Thrust, peak root torque and tip twist against sheet thickness for "
           "the three manufactured wings. Hollow markers are uncertain results; the bar spans every stabilization setting that settled.")
    figure(STIFF / "thrust_torque_stiffness.png", "Figure 3. The same results in thrust–torque space. Each line runs from rigid "
           "to the softest sheet. Softening moves every wing down and to the left, but not along a fixed thrust-per-torque line.", width=5.6 * inch)
    H2("5.1  What the results say")
    bullets([
        "<b>1.0 mm is effectively rigid</b> for the tapered wings (±4° tip twist, 1–3% thrust loss).",
        "<b>0.5 mm is the useful middle ground.</b> About ±20–26° of passive tip pitch costs 15–22% of the thrust but removes about 35% "
        "of the root torque, so thrust per torque improves.",
        "<b>0.25 mm and below over-feather.</b> With ±50–60° of twist the outer wing mostly slices through the water and thrust "
        "collapses to a quarter of rigid.",
        "<b>The Rectangle behaves differently.</b> At 1.0 mm it gains 51% thrust over rigid (0.79 → 1.20 N) with slightly more torque: "
        "on a short, wide plate a little passive pitch improves the effective angle of attack. It is also the hardest case numerically.",
    ])
    H2("5.2  Seeing the deformation")
    P("Ptera's own animation is rendered for every case, plus a second view looking upstream into the leading edge, in which a "
      "rigid wing is edge-on and any twist shows as visible surface. The camera is changed by intercepting one argument Ptera passes "
      "to PyVista, so Ptera's code is not modified.")
    figure(STIFF / "top_7657" / "stiffness_montage_frame.png", "Figure 4. Top #7657 at the same instant of the stroke for each sheet, "
           "front view (single frame of stiffness_montage.webp).", width=2.3 * inch)
    H2("5.3  Why the Rectangle failed at first, and the error bars")
    P("With St. Venant torsion only, the Rectangle at 0.25 and 0.2 mm diverged into a zigzag in which alternate strips twisted in "
      "opposite directions. For a wide constant-chord plate that mode had almost no stiffness: torsion springs resist <i>relative</i> "
      "twist, but a sawtooth pattern costs little of it. A real plate resists the same pattern through bending, which is the warping "
      "term of §3.2. Adding it removed the instability. The soft Rectangle points then solved but the stabilization factors disagreed "
      "by 13–18% (they agree within 3% for the other wings), so they are kept as uncertain and drawn with error bars rather "
      "than dropped.")

    # ---------------- campaign ----------------
    H1("6  Design campaign")
    H2("6.1  Plan")
    lv_txt = ", ".join(l["label"] + (" (focus)" if l["tier"] == "focus" else "") for l in plan["levels"])
    P(f"<b>Stiffness:</b> {lv_txt}. Focus levels are the sheets in stock and get the full treatment; context levels show the trend. "
      f"<b>Frequencies:</b> {', '.join(f'{f:g}' for f in plan['frequencies_hz'])} Hz, each with 50 steps per cycle. "
      "The campaign runs as three chunks of about 6–7 hours, one per frequency, starting with 1 Hz. Each chunk runs four phases: "
      "focus searches, context searches, a shape map, and a finalist re-check.")
    P("<b>Objectives</b> (each search maximizes one):")
    bullets([
        "<b>torque_1Nm</b>: maximize mean thrust subject to peak root torque ≤ 1.0 N·m. Score = <i>T</i>/<i>T</i><sub>ref</sub> when "
        "<i>M</i> ≤ 1, otherwise −10 − (<i>M</i> − 1)/<i>M</i><sub>ref</sub>, so seeds over the limit first walk down in torque and then climb in thrust. "
        "This is the objective that matches the robot's actuator budget and the one to use for decisions.",
        "<b>lambda_x</b>: <i>S</i> = <i>T</i>/<i>T</i><sub>ref</sub> − λ <i>M</i>/<i>M</i><sub>ref</sub>, λ ∈ {0.75, 1.25, 1.75} "
        "(focus levels) or {1.25} (context levels), with <i>T</i><sub>ref</sub>, <i>M</i><sub>ref</sub> fixed from that search's own seeds, "
        "as in the rigid studies.",
    ])
    P("<b>Search.</b> The move rule is the rigid studies' <font face='Mono'>coordinate_search.climb()</font> itself, called unchanged; "
      "an optional score function was the only addition. Each lineage cycles through the chord stations, trying ±20 mm on one chord. "
      "Once a chord has improved, its direction is remembered. A failed full step gets one half-step (10 mm) retry, after which that chord "
      "is retired. A lineage ends when every chord is retired or after 60 evaluations. Only verified elastic or settled rigid results "
      "may become parents. Every search starts from 25 lineages for focus levels (5 shape families × 5 half-spans of 150–400 mm) "
      "or 15 for context levels (3 spans).")
    figure(figs / "seeds.png", "Figure 5. Seed outlines. Every family has the 200 mm root chord; spans 150–400 mm.")
    P(f"<b>Shape map.</b> In addition to the searches, a fixed set of scrambled-Sobol outlines that obey the same rules "
      f"({plan['map']['focus_shapes']} for focus levels, {plan['map']['context_shapes']} for context levels, half-spans "
      "150–400 mm) is solved at every stiffness and frequency. Because the shapes are identical across stiffness, the map gives "
      "a direct 'same shape, different sheet' comparison and an independent check on the local searches.")
    P("<b>Finalists.</b> The best design of every search is re-solved at 16 spanwise panels and at half the time step.")
    H2("6.2  Infrastructure")
    bullets([
        "14 worker processes; each design's verification ladder runs inside one worker.",
        "Single-writer SQLite store (WAL). Each design is keyed by a hash of stiffness, frequency, chords, span and numerics, "
        "so any restart replays from the cache deterministically and resumes where it stopped. Crashed workers are replaced without losing the run.",
        "Local browser dashboard (127.0.0.1:8777): plan, progress with the original estimate, elapsed and remaining time, "
        "pause/stop, a per-chunk checklist, a design explorer, and on-demand replay of any stored design as a Ptera animation.",
        "No animations are rendered during the campaign; each design keeps its final-cycle traces and can be re-solved with "
        "full Ptera output from its key.",
        "Read-only post-processing: evolution animations and a sanity check that every accepted step raised the score "
        "(<font face='Mono'>elastic_evolution.py</font>), chunk reports, and this report.",
    ])
    P("Mean worker time per design, including the verification ladder: " + ", ".join(
        f"{lv['label']} {times[lv['id']]:.0f} s" for lv in plan["levels"] if lv["id"] in times) +
      ". Soft sheets cost 3–10× more because they need retries and smaller time steps.", small)

    # ---------------- results ----------------
    def chunk_block(c, number, label=""):
        ch = c["chunk"]
        H2(f"{number}  {label}{ch['title']}")
        tot = sum(c["counts"].values())
        q = ", ".join(f"{k} {v:,}" for k, v in sorted(c["counts"].items(), key=lambda kv: -kv[1]))
        P(f"{tot:,} designs ({q})" + (f"; {c['steps']:,} accepted search steps." if c["steps"] else "."))
        rows = [["Sheet", "Thrust", "Torque", "Half-span", "Tip twist", "Chords (mm, root → tip)", "Found by"]]
        for lv, r, src in c["best"]:
            if r:
                ch_ = json.loads(r[3]); eff_ = r[4] * (sum(1 for x in ch_ if x > 0) - 1) / (len(ch_) - 1)
                rows.append([lv["label"], f"{r[1]:.2f} N", f"{r[2]:.2f} N·m", f"{eff_ * 1000:.0f} mm",
                             f"±{r[5]:.0f}°" if r[5] is not None else "—", " ".join(f"{x * 1000:.0f}" for x in json.loads(r[3])),
                             (src or "").replace(",", " + ")])
            else:
                rows.append([lv["label"], "—", "", "", "", "no verified design ≤ 1 N·m", ""])
        table(rows, [0.85 * inch, 0.55 * inch, 0.7 * inch, 0.82 * inch, 0.6 * inch, 2.28 * inch, 1.1 * inch])
        P("Best verified (elastic) or settled (rigid) design with peak root torque ≤ 1 N·m, from every design evaluated at this "
          "frequency, whether found by a search or by the shape map. Half-span is the effective span: trailing zero chords shorten the wing.", small)
        figure(c["report"], f"Figure. {label}{ch['title']}: every design in thrust–torque space (left) and the best shape per "
               "model, to scale (right).")

    H1("7  Results: plate without the leading-edge tube")
    if not done:
        P("<i>No chunk is complete yet.</i>")
    for c in chunks:
        ch = c["chunk"]
        if not c["complete"]:
            P(f"<b>{ch['title']}</b>: pending.", body)
            continue
        chunk_block(c, f"7.{ch['id']}")
        if ch["freq"] == 1.25:
            H2("Interpretation (1.25 Hz)")
            bullets([
                "<b>0.5 mm gives the highest thrust of the whole study</b> (about 3.6 N under 1 N·m), but its tip twists ±68°. "
                "On 16 spanwise panels the 0.5 mm search winner rises from 3.43 N / 0.99 N·m to 3.82 N / 1.12 N·m, which is over the limit, "
                "and the 0.25 mm winner's torque changes by 74% (uncertain). At this frequency the soft-sheet numbers are "
                "trends, not predictions.",
                "<b>1.0 mm stays near rigid</b> (±5° twist) and gives the same thrust as rigid (2.46 vs 2.49 N) on a shorter 280 mm wing.",
            ])
        if ch["freq"] == 1.0:
            H2("Interpretation (1 Hz)")
            bullets([
                "<b>0.5 mm wins under a 1 N·m budget</b>: 2.87 N, 37% more than the best rigid wing (2.09 N) and the best 1.0 mm wing (2.10 N). "
                "The 0.5 mm sheet lowers torque more than thrust, so a larger 400 mm half-span wing fits the budget. Its outline "
                "drops quickly from the 200 mm root to about 70 mm by 30% of the span. Taking area away from the root keeps "
                "the root moment down while the long outer span adds thrust.",
                "<b>0.25 mm</b> reaches 2.14 N with an almost uniform 100 mm chord: the 'narrow' seed family barely changed. "
                "<b>0.2 mm</b> reaches 1.60 N at only 0.71 N·m; no 0.2 mm design reached the torque limit at all.",
                "<b>The span limit is now active.</b> All three elastic winners sit at the 400 mm maximum seed span, which suggests "
                "that longer wings would help the soft sheets if the robot can carry them.",
                "<b>The shape map found the best design at four of the five levels</b>, slightly above the searches (e.g. 0.5 mm: map 2.87 N vs "
                "search 2.85 N; 0.2 mm: map 1.60 N vs search 1.07 N). The local searches converge close to, but not exactly on, "
                "the best region, and for the softest sheet they got stuck well short of it. Keeping the map was worth its cost.",
                f"<b>Searches behaved.</b> All 340 lineages finished (44 seed solves did not verify and so could not start a lineage); across "
                f"{c['steps']:,} accepted steps none lowered the score.",
            ])
            H2("The λ objectives are not comparable across sheets")
            P("At λ = 1.75 the 0.5 and 0.25 mm searches shrank the wing to nothing: the winner is a 33 mm stub with 0.15 mN of thrust. "
              "At λ = 1.25 the 0.2 mm search nearly did the same (0.07 N). Meanwhile the rigid λ = 1.25 search grew to 9.1 N at 5.5 N·m. This is the objective doing "
              "what it says, not a solver failure. Shrinking a wing lowers thrust and torque roughly together, so whenever the marginal "
              "gain in <i>T</i>/<i>T</i><sub>ref</sub> is smaller than λ times the gain in <i>M</i>/<i>M</i><sub>ref</sub>, the best wing is no wing. "
              "Because <i>T</i><sub>ref</sub> and <i>M</i><sub>ref</sub> come from each search's own seeds, the same λ means a different "
              "trade-off at each stiffness. The torque_1Nm objective has none of these problems and should be used for decisions; "
              "λ = 0.75 gave nearly the same 0.5 mm answer (2.86 N at 0.99 N·m).")
            figure(figs / "evolution.png", "Figure. Final frame of the evolution animation for the 0.5 mm, 1 Hz, ≤ 1 N·m search. "
                   "Left: every lineage's accepted shape over its faint seed outline (rows = family, columns = starting span). "
                   "Right: each lineage's path through thrust–torque space; the dashed line is the 1 N·m limit.")
    if have_rechecks:
        H2("Finalist re-checks")
        P("Search winners were re-solved at 16 instead of 8 spanwise panels. Thrust and torque move together, typically by 1–5% and at most 11%. "
          "The 0.5 mm finalists rise by about 4–8%: the 0.5 mm, 1 Hz ≤ 1 N·m winner goes from 2.85 N / 0.98 N·m to 3.03 N / 1.06 N·m, "
          "so on the fine mesh it slightly exceeds the torque limit. Coarse-mesh winners sitting just under 1 N·m should be "
          "expected to land 5–10% above it. The fine-mesh refinement step should therefore apply the limit on the fine mesh.")
        figure(figs / "rechecks.png", "Figure. Change in finalist thrust and torque from 8 to 16 spanwise panels "
               "(stub winners of the λ = 1.75 searches omitted).", width=4.6 * inch)
        P("<b>Known issue with the half-time-step re-check.</b> When a finalist had already needed dt/2 to verify (most 0.5 and "
          "0.25 mm finalists), its 'dt/2' re-check started the same retry ladder at that same step and reproduced it exactly. "
          "For those designs the time-step re-check is not an independent test. Rigid and 1.0 mm finalists were re-checked "
          "properly (2–3% change). The fix, halving the time step the design actually used, was in place for chunk 3 (1.25 Hz) "
          "and the whole tube campaign: there the re-check moves thrust by −5 to +2.5% and torque by up to −17% for the softest "
          "sheets, and by at most 4% (thrust) for the tube models. Chunks 1–2 of this campaign were not re-run.", body)

    # ---------------- rod campaign ----------------
    rod_dir = camp.parent / "rod"
    if (rod_dir / "campaign.sqlite").exists():
        rplan, rchunks, _ = campaign_data(rod_dir)
        J = math.pi / 32 * (5e-3 ** 4 - 3e-3 ** 4)
        H1("8  The leading-edge tube")
        P("The manufactured wings carry a carbon tube (5 mm outer, 3 mm inner diameter) along the leading edge, fastened with M2 "
          "screws at five points through 3D-printed clips, and the tube is held against rotation at the root. The tube was left "
          "out of §5–7. It is added here as torsional stiffness in parallel with the plate along the twist axis, plus its mass:")
        EQ("k<sub>j</sub> = (G c<sub>j</sub> t<sup>3</sup>/3 + G<sub>r</sub> J<sub>r</sub>) / Δy<sub>j</sub>,   "
           "J<sub>r</sub> = π(D<sup>4</sup> − d<sup>4</sup>)/32")
        P(f"With G<sub>r</sub> = 4.5 GPa (conservative for a pultruded tube) the tube's GJ is {4.5e9 * J:.2f} N·m², about "
          f"{4.5e9 * J / (4.5e9 * 0.2 * 0.5e-3 ** 3 / 3):.0f}× the 0.5 mm plate at the 200 mm root and far more at the narrow outer "
          "wing, where the plate alone has almost nothing. The plate's own stiffness hardly matters any more: tip twist falls from "
          "±50–70° to ±1–2°. Fluid drag on the tube is not modelled (UVLM is inviscid); a rough estimate for a 340 mm "
          "wing is −0.25 N of thrust and +0.1 N·m of torque, which should be subtracted before comparing with a tank test.")
        P(f"The campaign ({', '.join(l['label'] for l in rplan['levels'])}) used the same plan, seeds, objectives and checks as §6.")
        for i, c in enumerate([c for c in rchunks if c["complete"]], 1):
            chunk_block(c, f"8.{i}", "Tube campaign, ")
        bullets([
            "<b>Tube + 0.5 mm beats rigid at every frequency</b> (1.94 / 2.33 / 2.63 N against 1.73 / 2.09 / 2.49 N at 0.75 / 1 / "
            "1.25 Hz), and 0.25 mm is within 1% of 0.5 mm. With twist this small the gain is mostly a better outline, not "
            "elasticity: the 1 Hz tube winners solved as rigid plates give 2.36 N at 1.00 N·m and 2.38 N at 1.02 N·m.The tube searches found a shape the rigid "
            "searches missed; the geometric sweep (§9) confirms rigid can reach 2.30 N.",
            "<b>Higher frequency pays</b>: 1.25 Hz gives 13% more thrust than 1 Hz within the same torque budget, on a shorter wing "
            "(286 mm effective half-span against 340 mm at 1 Hz): the extra flapping speed lets less span reach the torque budget.",
            "<b>The thin tip is real, not an artefact.</b> Winners narrow to the 10 mm minimum chord over the outer third. That "
            "outer strip adds span-wise lift far from the root for little root torque. With the tube present, a 10 mm plate strip "
            "is half tube by width, and the tube's drag (unmodelled) would cost most there.",
            "<b>Finalist re-checks are small</b>: 16 spanwise panels change thrust by −4 to +5% and halving the used time step by −4 to +2%.",
        ])

    # ---------------- geometric sweep ----------------
    sw_dir = camp.parent / "sweep"
    if (sw_dir / "campaign.sqlite").exists():
        splan, schunks, _ = campaign_data(sw_dir)
        H1("9  Geometric sweep")
        P(f"A search only climbs from its seeds. To check for good regions the searches never visited, {splan['map']['focus_shapes']:,} "
          "scrambled-Sobol outlines were solved at 1 Hz for each of rigid, 0.5 mm + tube, 0.25 mm + tube and 0.5 mm without the "
          "tube. The half-span is continuous over 280–400 mm (the searches used discrete 280 / 340 / 400 mm), the root chord is "
          "exactly 200 mm and the minimum chord is 10 mm. No climbing: one solve per outline.")
        for c in [c for c in schunks if c["complete"]]:
            chunk_block(c, "9.1", "Sweep, ")
        bullets([
            "<b>The sweep found a better rigid wing</b> (2.30 N at 327 mm effective half-span) than the rigid searches of either campaign (2.09 N). "
            "The rigid search space has better regions than its seeds reached.",
            "<b>For the elastic models the searches held up</b>: the sweep's best are within 2–3% of the campaign winners "
            "(0.5 mm + tube 2.27 vs 2.33 N; 0.5 mm without tube 2.80 vs 2.87 N).",
            "Every elastic sweep design verified, because none of these outlines needed the soft-sheet retries.",
        ])

    # ---------------- refinement ----------------
    ref_dir = ROOT / "outputs" / "elastic" / "refine"
    if (ref_dir / "summary.csv").exists():
        import csv
        H1("10  Fine-mesh refinement of the winners")
        P("The best 1 Hz design per model (from the campaigns or the sweep, 280–400 mm span, ≤ 1 N·m) was turned into a smooth "
          "trailing edge: a monotone PCHIP curve through the fixed 200 mm root chord and six control chords, sampled at 25 stations. "
          "It was then re-solved on a finer 24 × 6 panel mesh, with dt refinement allowed. A pattern search moved each control chord "
          "and the half-span by ±10 mm, then ±5 mm, in parallel, keeping the best move each round, with the 1 N·m limit applied "
          "on the fine mesh. The final design was solved again at half its time step.")
        rows = [["Model", "Coarse winner", "Smooth fit, fine mesh", "Refined", "Refined at dt/2", "Half-span", "Tip twist"]]
        names = {"rigid": "Rigid", "t0.50r": "0.5 mm + tube", "t0.25r": "0.25 mm + tube", "t0.50": "0.5 mm, no tube"}
        for r in csv.DictReader(open(ref_dir / "summary.csv")):
            m = r["model"]
            hist = json.loads((ref_dir / m / "history.json").read_text())
            st = hist["history"][0]
            dtc = json.loads((ref_dir / m / "dt_check.json").read_text())
            tw = f"±{float(r['tip_twist_deg']):.0f}°" if r["tip_twist_deg"] else "—"
            rows.append([names.get(m, m), f"{float(r['coarse_thrust_N']):.2f} N / {float(r['coarse_torque_Nm']):.2f}",
                         f"{st['thrust']:.2f} N / {st['torque']:.2f}",
                         f"<b>{float(r['refined_thrust_N']):.2f} N / {float(r['refined_torque_Nm']):.2f}</b>",
                         f"{dtc['thrust']:.2f} N / {dtc['torque']:.2f}", f"{float(r['refined_half_span_mm']):.0f} mm", tw])
        table(rows, [1.2 * inch, 1.0 * inch, 1.05 * inch, 1.0 * inch, 1.0 * inch, 0.85 * inch, 0.65 * inch])
        P("Thrust (N) / peak root torque (N·m) per wing at 1 Hz.", small)
        figure(ref_dir / "summary.png", "Figure. Refined outlines at 1 Hz, to scale. The leading edge (top) is straight and "
               "perpendicular to the flow; the trailing edge carries all of the taper.", width=5.4 * inch)
        rows = [["Model", "Same outline, fine mesh", "Same outline resized to 1 N·m", "Optimized curve", "Change"]]
        for r in csv.DictReader(open(ref_dir / "summary.csv")):
            m = r["model"]; d = ref_dir / m
            if not (d / "baseline_at_budget.json").exists():
                continue
            f = json.loads((d / "baseline_fine.json").read_text()); b = json.loads((d / "baseline_at_budget.json").read_text())
            t = float(r["refined_thrust_N"])
            rows.append([names.get(m, m), f"{f['thrust']:.2f} N / {f['torque']:.2f}",
                         f"<b>{b['thrust']:.2f} N</b> / {b['torque']:.2f} · {b['effective_span'] * 1000:.0f} mm",
                         f"<b>{t:.2f} N</b> / {float(r['refined_torque_Nm']):.2f} · {float(r['refined_half_span_mm']):.0f} mm",
                         f"{100 * (t - b['thrust']) / b['thrust']:+.1f}%"])
        if len(rows) > 1:
            P("<b>Like-for-like check.</b> To separate shape from mesh and size, each coarse winner's exact 8-station outline was "
              "solved with the same fine-mesh numerics, then its span was scaled (secant iterations) until it also used exactly "
              "the 1 N·m budget. The optimized curve is compared against that resized outline.")
            table(rows, [1.2 * inch, 1.5 * inch, 1.75 * inch, 1.6 * inch, 0.75 * inch])
        bullets([
            "<b>For the rigid and tube models the optimization did not help.</b> The optimized curves are 1–2% below the campaign "
            "outline resized to the budget. The six-point smooth curve cannot reproduce the winners' sharp drop just outboard of "
            "the root, and the ±10 → 5 mm search stalled near its smooth starting point. The best 0.5 mm + tube design is the "
            "campaign outline at 344 mm half-span: 2.34 N at 1.00 N·m on the fine mesh.",
            "<b>For the bare 0.5 mm plate the optimization did help</b> (+10%). On the fine mesh that winner was over budget "
            "(3.20 N at 1.13 N·m); shrinking it to the budget gives 2.55 N, while reshaping gives 2.82 N.",
            "<b>Mesh effect.</b> The same outline loses 3–5% of thrust and 2–4% of torque from the campaign mesh to the fine mesh "
            "for the rigid and tube models, so thrust per torque barely changes. Soft bare plates move the other way in torque.",
            "<b>Time step</b>: halving it changes the refined results by at most 1.3% in thrust and 1.1% in torque.",
            "<b>Implication for refinement.</b> A smooth parameterisation should be able to represent the coarse winner exactly, "
            "for example by starting from the campaign stations with extra control points near the root.",
            "Outlines for manufacture (optimized CSV/SVG, and the resized campaign outline as CSV) are in the dashboard's files/optimized folder.",
        ])

    sw_dir = ROOT / "outputs" / "elastic" / "refine_sweep"
    if (sw_dir / "summary.csv").exists():
        import csv
        H1("10.1  Budget-matched search from the geometry-sweep winner")
        P("The geometry-sweep 1 Hz winner (chords 200, 66, 57, 28, 12, 11, 10 mm; 327 mm effective half-span) was optimized again "
          "for the rigid and both tube models, with two changes. First, the search starts from the exact outline: the six outboard "
          "station chords are the variables, with straight segments between them, so nothing is lost to smoothing. Second, every "
          "candidate's half-span is rescaled (secant iterations on torque) until peak torque sits at the 1 N·m budget. Each step "
          "therefore compares shapes at equal torque. Chords moved ±10, ±5, then ±2 mm. A first attempt without the span "
          "rescaling stalled at 2.25 N: it spent the outline's spare torque on wider tip chords and could not reach longer spans.")
        names = {"rigid": "Rigid", "t0.50r": "0.5 mm + tube", "t0.25r": "0.25 mm + tube"}
        rows = [["Model", "Exact outline, fine mesh", "Resized to 1 N·m (start)", "Round 5", "Optimized", "At dt/2", "Tip twist"]]
        for r in csv.DictReader(open(sw_dir / "summary.csv")):
            m = r["model"]; d = sw_dir / m
            h = json.loads((d / "history.json").read_text())["history"]
            f = json.loads((d / "baseline_fine.json").read_text()); dtc = json.loads((d / "dt_check.json").read_text())
            r5 = h[min(5, len(h) - 1)]
            tw = f"±{float(r['tip_twist_deg']):.1f}°" if r["tip_twist_deg"] else "—"
            rows.append([names.get(m, m), f"{f['thrust']:.2f} N / {f['torque']:.2f}",
                         f"{h[0]['thrust']:.2f} N · {h[0]['span'] * 1000:.0f} mm",
                         f"{r5['thrust']:.2f} N · {r5['span'] * 1000:.0f} mm",
                         f"<b>{float(r['refined_thrust_N']):.2f} N</b> · {float(r['refined_half_span_mm']):.0f} mm",
                         f"{dtc['thrust']:.2f} N / {dtc['torque']:.2f}", tw])
        table(rows, [1.1 * inch, 1.15 * inch, 1.2 * inch, 0.95 * inch, 1.0 * inch, 0.95 * inch, 0.6 * inch])
        P("Thrust (N) / peak root torque (N·m) per wing at 1 Hz on the 24 × 6 mesh; every resized, round-5 and optimized design is "
          "at 0.997–1.000 N·m.", small)
        figure(sw_dir / "t0.50r" / "outline.png", "Figure. 0.5 mm + tube: geometry-sweep winner (dashed) and the budget-matched "
               "optimum, to scale. The outer wing has collapsed onto the 10 mm minimum chord.", width=5.6 * inch)
        bullets([
            "<b>This search does beat the resizing baseline</b>: about +6% for all three models (2.42 N against 2.27–2.29 N), and "
            "about +3% over the best campaign outline resized to the budget (2.34 N). The tube models end about 0.006 N above rigid; "
            "at this shape, plate stiffness hardly matters.",
            "<b>The optimum sits on a constraint.</b> All outboard chords end at 10–12 mm: the 200 mm root tapers within about 60 mm "
            "into a strip roughly 10 mm wide, out to 369 mm. The model rewards trading area for span, and would go narrower if allowed.",
            "<b>Most of the gain comes early.</b> Five rounds of thinning the mid-span give 2.38 N at 349 mm "
            "(chords 66, 18, 18, 12, 11, 10 mm); the remaining twelve rounds add about 0.04 N.",
            "<b>Model validity.</b> A 10 mm chord is only twice the 5 mm tube, whose round section and drag are not modelled, and at "
            "about 1.2 m/s tip speed in water the chord Reynolds number is near 10<super>4</super>, where viscous losses this method "
            "omits become significant. The strip outline is best read as a direction; the round-5 shape is the more credible build.",
            "<b>Time step</b>: at dt/2 the optimized designs change by +0.2% in thrust and −0.2% in torque.",
        ])

    sf_dir = ROOT / "outputs" / "elastic" / "campaigns" / "spanfree"
    if (sf_dir / "fine_check.json").exists():
        H1("10.2  Span-free search")
        P("Earlier campaigns searched at five fixed half-spans, so their best designs sat on 280, 340 or 400 mm. This search drops "
          "span as a variable: every candidate is rescaled to exactly the 1 N·m budget (280–400 mm), and a pattern search moves "
          "the outboard chords (±20, 10, 5 mm) on the campaign mesh. 29 starts per model, 87 in all (the best campaign outlines, the five seed "
          "families and Sobol outlines); 32 of the 87 were over budget even at 280 mm. The run took 4.9 h.")
        fc = json.loads((sf_dir / "fine_check.json").read_text())
        names = {"rigid": "Rigid", "t0.50r": "0.5 mm + tube", "t0.25r": "0.25 mm + tube"}
        rows = [["Model", "Outboard chords (mm)", "Campaign mesh", "Fine mesh (24 × 6), at budget"]]
        seen = set()
        for r in fc:
            if r["model"] in seen:
                continue
            seen.add(r["model"])
            rows.append([names[r["model"]], ", ".join(f"{c:.0f}" for c in r["chords_mm"][1:]),
                         f"{r['coarse_thrust']:.3f} N · {r['coarse_span']:.0f} mm",
                         f"<b>{r['thrust']:.2f} N</b> · {r['span'] * 1000:.0f} mm"])
        table(rows, [1.2 * inch, 2.0 * inch, 1.6 * inch, 1.9 * inch])
        bullets([
            "<b>Every start converged to the same shape</b>: 2.42–2.48 N on the campaign mesh, half-span 355–369 mm, the 200 mm "
            "root tapering within one station into a strip on the 10 mm minimum chord.",
            "<b>On the fine mesh the winners give 2.41–2.42 N</b>, the same as the budget-matched sweep optimum (§10.1). Two "
            "independent searches from very different starts reach the same answer, so 2.42 N is the optimum this model allows "
            "with a 10 mm minimum chord. The campaign mesh reads about 2% high here.",
            "The same caveats as §10.1 apply: the optimum sits on the minimum chord, where tube drag and viscous losses matter.",
        ])

    # ---------------- lessons ----------------
    H1("11  Limitations")
    bullets([
        "<b>Twist only.</b> The plate twists about its leading edge; spanwise bending and chordwise camber are not modelled. This "
        "matches the hardware's leading-edge tube well (§8). Without the tube, a bare plate's shear centre is nearer mid-chord and "
        "it also bends spanwise, which a full plate model would capture.",
        "<b>The tube's grip is idealised.</b> The tube is assumed to carry the plate's twist perfectly along the whole span. Five "
        "screw points, printed clips and some slip between them make the real wing softer, somewhere between the two models. "
        "Tube drag is also not modelled.",
        "<b>Large twist.</b> The soft-sheet winners twist ±60° at the tip. That is beyond small-deformation torsion and into the "
        "range where flow separates and leading-edge vortices form, which the attached-flow, inviscid UVLM does not represent. "
        "Treat 0.25 and 0.2 mm results as trends, not predictions.",
        "<b>Material.</b> G = 4.5 GPa is a literature value and enters linearly into stiffness, against t³ for thickness. "
        "A torsion test on the actual sheet is cheap and would tighten every elastic result.",
        "<b>Numerical vs. physical confidence.</b> 'Verified' means the stabilization does not affect the answer. Agreement with "
        "the real wing needs a tank test: ideally the Top or the 0.5 mm winner, measuring thrust, root torque and tip twist.",
        "<b>Mesh.</b> 8 spanwise panels resolve trends; absolute thrust and torque shift by 1–5% typically at 16 panels, more for "
        "soft sheets with large twist (§7). The refinement (§10) re-solves the chosen designs on 24 × 6 panels.",
        "<b>Local search.</b> Coordinate climbing finds a good local design from each seed, not a global optimum. The 25 seeds "
        "and the shape map are what provide coverage.",
    ])
    H1("12  Lessons learned while building this")
    P("Problems found and fixed along the way, recorded because each one could silently bias a large study:", body)
    bullets([
        "<b>Damping as a stabilizer</b> hid the explicit-coupling instability and made the damper set the deformation (§4.1).",
        "<b>A cycle comparison by array index</b> broke when the step did not divide the period (dt = 0.03 s): the Middle wing was "
        "wrongly reported as not settling. Cycles are now compared by time interpolation.",
        "<b>A missing warping term</b> left a near-free zigzag mode that destabilized wide plates (§5.3).",
        "<b>Soft plates need time.</b> Without automatic cycle doubling and time-step refinement, most 0.25 and 0.2 mm designs would "
        "have been unresolved; with them, 96% of 0.25 mm designs at 1 Hz verify.",
        "<b>Deterministic resume needs care.</b> When results come back instantly from the cache, a search could be declared finished "
        "before all its lineages existed, which picked a different winner after a restart. All lineages are now created before any advances.",
        "<b>Animations must use the verified solve.</b> An early animation rendered a single unverified run that differed from the "
        "reported numbers. The animation path now runs the same verification first.",
        "<b>λ-weighted objectives degenerate</b> across stiffness (§7); a hard torque budget is the robust formulation.",
        "<b>The dt/2 finalist re-check</b> was not independent for designs that already used a refined step (§7).",
        "<b>A simplification left out of the model mattered most.</b> The leading-edge tube changes tip twist from tens of degrees "
        "to one or two (§8). Hardware details should be checked against the model before a long campaign, not after.",
        "<b>Running campaigns side by side did not save time.</b> Two jobs shared the same 16 cores, so each ran at half speed. "
        "Running them in series with all workers finished every stage sooner.",
    ])
    H1("13  Next steps")
    bullets([
        "<b>Bench twist test</b> (decides between §7 and §8): clamp a manufactured wing at the root, hang about 50 g at the "
        "trailing-edge tip corner, and measure tip twist. The tube model predicts about 4°; a bare 0.5 mm plate tens of degrees.",
        "Measure the sheet's shear modulus on an offcut; check how firmly the clips and screws hold the plate to the tube.",
        "Tank-test the 0.5 mm + tube refined wing against its prediction (thrust, peak root torque, tip twist), after "
        "subtracting the estimated tube drag.",
        "Refine at 1.25 Hz if the actuator can run there: it gave 13% more thrust within the same torque budget.",
        "Before building the budget-matched optimum (§10.1), check the narrow outer wing: model tube drag and a viscous "
        "correction, or tank-test the round-5 shape against the sweep winner.",
        "Revisit the 10 mm minimum chord with tube drag included. Only the bare-plate winners press against the 400 mm span limit.",
    ])
    H1("Appendix: reproducing this work")
    P("Code at wing-studies commit 3b30927 plus <font face='Mono'>elastic_evolution.py</font> and this script; "
      "PteraSoftware 5.1.0 (upstream commit 17a98a10), unmodified.", body)
    story.append(Paragraph(
        "wingstudy/elastic.py            structural model + stabilized update<br/>"
        "wingstudy/elastic_runner.py     solve one design; verification ladder; Ptera outputs<br/>"
        "wingstudy/elastic_study.py      validate | stiffness (three candidates x five sheets)<br/>"
        "wingstudy/elastic_campaign.py   campaign plan, scheduler, store, replay<br/>"
        "wingstudy/elastic_dashboard.py  browser dashboard (127.0.0.1:8777)<br/>"
        "wingstudy/elastic_evolution.py  CAMPAIGN --check | evolution GIFs<br/>"
        "wingstudy/elastic_refine.py     smooth-curve fine-mesh refinement of the winners<br/>"
        "wingstudy/elastic_report.py     this report<br/><br/>"
        "python -m wingstudy.elastic_study stiffness<br/>"
        "python -m wingstudy.elastic_campaign dashboard --campaign outputs/elastic/campaigns/rod --variant rod<br/>"
        "python -m wingstudy.elastic_campaign dashboard --campaign outputs/elastic/campaigns/sweep --variant sweep<br/>"
        "python -m wingstudy.elastic_campaign replay outputs/elastic/campaigns/weekend KEY<br/>"
        "python -m wingstudy.elastic_refine --workers 14<br/>"
        "python -m wingstudy.elastic_refine --models rigid,t0.50r,t0.25r --campaigns sweep --out outputs/elastic/refine_sweep "
        "--numerics '{\"param\":\"exact\",\"project\":true,\"steps\":[0.01,0.005,0.002]}'<br/>"
        "python -m wingstudy.elastic_report", code))

    def on_page(cv, doc):
        cv.saveState(); cv.setFont("Serif", 7.5); cv.setFillColor(colors.HexColor(INK2))
        cv.drawString(0.75 * inch, 0.5 * inch, "Elastic flapping wings: process report")
        cv.drawRightString(7.75 * inch, 0.5 * inch, str(doc.page)); cv.restoreState()

    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(out_pdf), pagesize=letter, leftMargin=0.75 * inch, rightMargin=0.75 * inch,
                            topMargin=0.7 * inch, bottomMargin=0.75 * inch, title="Elastic flapping wings: process report")
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return out_pdf


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("campaign", type=Path, nargs="?", default=CAMPAIGN)
    ap.add_argument("--out", type=Path, default=ROOT / "outputs" / "elastic" / "report" / "elastic_process_report.pdf")
    a = ap.parse_args(argv)
    print(build(a.campaign.resolve(), a.out.resolve()))


if __name__ == "__main__":
    main()
