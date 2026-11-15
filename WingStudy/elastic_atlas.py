"""Elastic wing atlas: every elastic study in one offline, shareable dashboard.

  python WingStudy/elastic_atlas.py render [--workers 6]   # Ptera animations for every category winner
  python WingStudy/elastic_atlas.py build                  # outputs/elastic/atlas/ (index.html + media) and a ZIP

The build is read-only on the campaign databases. The result is a folder whose index.html embeds all
data and references media/ by relative path, so it opens by double-click with no Python, server or
internet connection. The ZIP next to it is the same folder, ready to send.
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
import sys
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
ELASTIC = ROOT / "outputs" / "elastic"
CAMPAIGNS = ELASTIC / "campaigns"
OUT = ELASTIC / "atlas"

# Studies, in display order. "rod" is the hardware configuration (5/3 mm tube along the leading edge).
STUDIES = [
    {"id": "rod", "dir": "rod", "label": "Rod campaign", "short": "Rod",
     "about": "Searches + shape map with the 5/3 mm carbon tube bolted along the leading edge (the hardware). 0.75, 1 and 1.25 Hz."},
    {"id": "weekend", "dir": "weekend", "label": "Plate campaign (no rod)", "short": "Plate",
     "about": "Searches + shape map for the bare carbon plate, five stiffness levels. 0.75, 1 and 1.25 Hz."},
    {"id": "sweep", "dir": "sweep", "label": "Geometric sweep", "short": "Sweep",
     "about": "2,048 scrambled-Sobol outlines at 1 Hz, continuous 280–400 mm half-span, solved for each model. No climbing."},
]
CATALOG_STUDY = {"id": "catalog", "label": "Rigid catalog (before elasticity)", "short": "Rigid catalog",
                 "about": "Every successful rigid single-wing simulation from the earlier coordinate and λ studies (master "
                          "catalog), exact repeats merged. Root chord was free in some of these studies; conditions groups "
                          "differ in time step and stroke waveform."}
MODELS = [  # id, label, thickness, rod
    ("rigid", "Rigid", None, False),
    ("t1.00", "1.0 mm", 1.0, False),
    ("t0.50", "0.5 mm (no rod)", 0.5, False),
    ("t0.25", "0.25 mm (no rod)", 0.25, False),
    ("t0.20", "0.2 mm (no rod)", 0.2, False),
    ("t0.50r", "0.5 mm + rod", 0.5, True),
    ("t0.25r", "0.25 mm + rod", 0.25, True),
]
TORQUE_LIMIT = 1.0
# Search objective bits (16 = the design was a search seed)
OBJECTIVE_BITS = {"torque_1Nm": 1, "lambda_0.75": 2, "lambda_1.25": 4, "lambda_1.75": 8}
# Where a design came from when no campaign search evaluated it (bits combine with the objective bits)
ORIGIN_BITS = {"shape_map": 32, "sweep": 64, "rigid_search": 128, "rigid_sweep": 256}


def connect(study_dir: str):
    return sqlite3.connect(f"file:{CAMPAIGNS / study_dir / 'campaign.sqlite'}?mode=ro", uri=True)


def plan_of(db):
    return json.loads(db.execute("select v from meta where k='plan'").fetchone()[0])


def category_winners():
    """Best verified (elastic) / settled (rigid) design at <= 1 N·m per study x frequency x model."""
    out = []
    for st in STUDIES:
        db = connect(st["dir"]); plan = plan_of(db)
        for f in plan["frequencies_hz"]:
            for lv in plan["levels"]:
                r = db.execute("select key,thrust,torque,half_span,tip_twist,chords,status from designs where level=? "
                               "and abs(freq-?)<1e-9 and numerics='base' and status in ('verified','ok') and torque<=? "
                               "order by thrust desc limit 1", (lv["id"], f, TORQUE_LIMIT)).fetchone()
                n = db.execute("select count(*) from designs where level=? and abs(freq-?)<1e-9 and numerics='base'",
                               (lv["id"], f)).fetchone()[0]
                out.append({"study": st["id"], "dir": st["dir"], "freq": f, "model": lv["id"], "evaluated": n,
                            **({"key": r[0], "thrust": r[1], "torque": r[2], "half_span": r[3], "tip_twist": r[4],
                                "chords": json.loads(r[5]), "status": r[6]} if r else {"key": None})})
    return out


def animation_dir(key: str):
    """Existing animation folder for a design key in any campaign, else None."""
    for st in STUDIES:
        d = CAMPAIGNS / st["dir"] / "animations" / key
        if (d / "animation.webp").exists():
            return d
    return None


def _replay(study_dir, key):
    import elastic_campaign as EC
    t = time.time()
    EC.replay(CAMPAIGNS / study_dir, key)
    return key, time.time() - t


def render(workers: int):
    todo, seen = [], set()
    for w in category_winners():
        if w["key"] and w["key"] not in seen and animation_dir(w["key"]) is None:
            seen.add(w["key"]); todo.append((w["dir"], w["key"]))
    print(f"{len(todo)} winner animations to render with {workers} workers", flush=True)
    with ProcessPoolExecutor(workers) as ex:
        futs = {ex.submit(_replay, d, k): k for d, k in todo}
        for i, fu in enumerate(as_completed(futs), 1):
            try:
                k, s = fu.result(); print(f"[{i}/{len(todo)}] {k[:10]} rendered in {s:.0f} s", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"[{i}/{len(todo)}] {futs[fu][:10]} FAILED: {exc}", flush=True)


# ----------------------------------------------------------------------------------------
# Media: Ptera's 1024 px animations re-encoded for sharing (full resolution, every 2nd frame at true speed)
# ----------------------------------------------------------------------------------------
def _shrink(src: str, dst: str, width: int = 1024, step: int = 2, poster: str | None = None):
    from PIL import Image, ImageSequence
    src, dst = Path(src), Path(dst)
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime and (poster is None or Path(poster).exists()):
        return dst.name
    dst.parent.mkdir(parents=True, exist_ok=True)
    im = Image.open(src)
    frames, durs = [], []
    for i, fr in enumerate(ImageSequence.Iterator(im)):
        if i % step:
            continue
        g = fr.convert("RGB")
        if g.width != width:
            g = g.resize((width, round(g.height * width / g.width)), Image.LANCZOS)
        frames.append(g); durs.append((fr.info.get("duration") or im.info.get("duration") or 20) * step)
    if src.suffix == ".gif" or len(frames) == 1:
        frames[0].save(dst, save_all=len(frames) > 1, append_images=frames[1:], duration=durs, loop=0)
    else:
        frames[0].save(dst, "WEBP", save_all=True, append_images=frames[1:], duration=durs, loop=0, quality=88, method=4)
    if poster:
        frames[len(frames) // 3].save(poster, "WEBP", quality=88)
    return dst.name


VIEWS = {"main": "animation.webp", "front": "animation_front.webp", "top": "animation_top.webp"}


def _media_jobs(src_dir: Path, rel: str, out: Path, jobs: list):
    """Queue shrink jobs for one Ptera output folder; return the relative media map."""
    media = {}
    for view, name in VIEWS.items():
        if (src_dir / name).exists():
            jobs.append((str(src_dir / name), str(out / rel / f"{view}.webp"),
                         str(out / rel / "poster.webp") if view == "main" else None))
            media[view] = f"{rel}/{view}.webp"
    if "main" in media:
        media["poster"] = f"{rel}/poster.webp"
    return media


# ----------------------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------------------
def campaign_rows():
    """All base designs of every study, columnar."""
    model_ix = {m[0]: i for i, m in enumerate(MODELS)}
    freqs = [0.75, 1.0, 1.25]
    statuses = ["verified", "ok", "uncertain", "unverified", "unresolved", "unsettled", "failed"]
    cols = {k: [] for k in ("s", "m", "f", "T", "Q", "H", "W", "S", "C", "src", "k", "obj")}
    ranges = {}
    n_unique = set()
    for si, st in enumerate(STUDIES):
        db = connect(st["dir"])
        src = {}
        for key, s in db.execute("select key, group_concat(distinct source) from uses group by key"):
            src[key] = (1 if "search" in s else 0) | (2 if "map" in s else 0)
        # which search objectives evaluated each design (a design can serve several searches)
        obj = {}
        for key, o, role in db.execute("select u.key, s.objective, u.role from uses u join searches s on s.search_id=u.search_id "
                                       "where u.source='search'"):
            obj[key] = obj.get(key, 0) | OBJECTIVE_BITS.get(o, 0) | (16 if role == "seed" else 0)
        for (key, status, level, freq, chords, hs, thrust, torque, twist, tlo, thi, qlo, qhi) in db.execute(
                "select key,status,level,freq,chords,half_span,thrust,torque,tip_twist,thrust_lo,thrust_hi,torque_lo,torque_hi "
                "from designs where numerics='base' and thrust is not null and torque is not null"):
            if status not in statuses:
                statuses.append(status)
            i = len(cols["s"])
            cols["s"].append(si); cols["m"].append(model_ix[level]); cols["f"].append(freqs.index(round(freq, 2)))
            cols["T"].append(round(thrust, 4)); cols["Q"].append(round(torque, 4)); cols["H"].append(round(hs * 1000, 1))
            cols["W"].append(None if twist is None else round(twist, 1)); cols["S"].append(statuses.index(status))
            cols["C"].extend(round(c * 1000, 1) for c in json.loads(chords))
            o = obj.get(key, 0)
            if st["id"] == "sweep":
                o |= ORIGIN_BITS["sweep"]
            elif src.get(key, 0) & 2:
                o |= ORIGIN_BITS["shape_map"]
            cols["src"].append(src.get(key, 0)); cols["k"].append(key); cols["obj"].append(o)
            n_unique.add(key)
            if status == "uncertain" and tlo is not None:
                ranges[i] = [round(tlo, 4), round(thi, 4), round(qlo, 4), round(qhi, 4)]
    return {"cols": cols, "ranges": ranges, "freqs": freqs, "statuses": statuses, "unique": len(n_unique)}


def rigid_search_studies():
    """Rigid catalog studies run as adaptive objective searches (their cases carry an adaptive_trial).
    The rest were shape sweeps (search_mode 'shape_sweep') or a few hand-picked variants."""
    out = set()
    for name in ("master_runs.sqlite3", "master_runs_old.sqlite3"):
        f = ROOT / "outputs" / name
        if not f.exists():
            continue
        db = sqlite3.connect(f"file:{f}?mode=ro", uri=True)
        for study, payload in db.execute("select o.study, c.payload from occurrences o join cases c on c.case_no=o.case_no "
                                         "where o.state='ok'"):
            if study not in out and (json.loads(payload).get("case") or {}).get("adaptive_trial") is not None:
                out.add(study)
    return out


def catalog_rows(data):
    """Append the rigid master catalog (all studies before elasticity) to the columnar rows.

    Uses wing_atlas.bundle, the same source as the all-wings atlas: every retained successful
    single-wing simulation, exact repeats merged. Outlines are kept as polygons because these
    wings have varying station counts and root chords.
    """
    import model as WM
    import wing_atlas
    b = wing_atlas.bundle(WM)
    cols = data["cols"]
    si = len(STUDIES)
    studies = {s["id"]: k for k, s in enumerate(b["studies"])}
    cohorts = {g["id"]: k for k, g in enumerate(b["cohorts"])}
    import re
    study_obj = {}
    for s_ in b["studies"]:
        m_ = re.search(r"lambda[ -]?(\d)[.-](\d+)", s_["id"].lower() + " " + s_["name"].lower())
        if m_:
            study_obj[s_["id"]] = OBJECTIVE_BITS.get(f"lambda_{m_.group(1)}.{m_.group(2)}", 0)
    searched = rigid_search_studies()
    statuses = data["statuses"]
    for st in ("ok", "unsettled"):
        if st not in statuses:
            statuses.append(st)
    cat = {"first": len(cols["s"]), "poly": [], "area": [], "root": [], "study": [], "cohort": [], "number": [], "name": []}
    for r in b["rows"]:
        if r["load_scope"] != "single" or r["thrust"] is None or r["torque"] is None:
            continue
        cols["s"].append(si); cols["m"].append(0); cols["f"].append(data["freqs"].index(1.0))
        cols["T"].append(round(r["thrust"], 4)); cols["Q"].append(round(r["torque"], 4))
        cols["H"].append(round(r["span"] * 1000, 1)); cols["W"].append(None)
        cols["S"].append(statuses.index("ok" if r["settled"] else "unsettled"))
        cols["C"].extend([0] * 8); cols["src"].append(4); cols["k"].append(r["key"][:24])
        cols["obj"].append(study_obj.get(r["study"], 0) | ORIGIN_BITS["rigid_search" if r["study"] in searched else "rigid_sweep"])
        cat["poly"].append([v for p in r["outline"] for v in (round(p[0] * 1000, 1), round(p[1] * 1000, 1))])
        cat["area"].append(round(r["area"] * 1e4, 2) if r["area"] else None)
        cat["root"].append(round(r["root"] * 1000, 1) if r["root"] else None)
        cat["study"].append(studies[r["study"]]); cat["cohort"].append(cohorts[r["cohort"]])
        cat["number"].append(r["number"]); cat["name"].append(r["name"])
    cat["locations"] = {r["key"][:24]: r["locations"] for r in b["rows"]}
    cat["studies"] = [{"id": s["id"], "name": s["name"], "generation": s["generation"]} for s in b["studies"]]
    cat["cohorts"] = [{"id": g["id"], "label": g["label"], "count": g["count"],
                       "dt": g["conditions"]["dt_s"], "waveform": g["conditions"]["waveform"].get("mode", "sine"),
                       "panels": f"{g['conditions']['span_panels']}×{g['conditions']['chord_panels']}"} for g in b["cohorts"]]
    return cat


def catalog_winners(data, cat, out: Path, jobs: list):
    """Best settled rigid catalog wing <= 1 N·m per conditions group, plus the best with a 200 mm root."""
    cols, first = data["cols"], cat["first"]
    ok = data["statuses"].index("ok")
    rows = [i for i in range(first, len(cols["s"])) if cols["S"][i] == ok and cols["Q"][i] <= TORQUE_LIMIT]
    picks = []
    for g, co in enumerate(cat["cohorts"]):
        cand = [i for i in rows if cat["cohort"][i - first] == g]
        if cand:
            picks.append((max(cand, key=lambda i: cols["T"][i]), co["label"].split(" · group")[0], sum(cat["cohort"][j - first] == g for j in range(first, len(cols["s"])))))
    cand = [i for i in rows if cat["root"][i - first] and abs(cat["root"][i - first] - 200) < 0.5]
    if cand:
        picks.append((max(cand, key=lambda i: cols["T"][i]), "200 mm root chord, any conditions group",
                      sum(1 for j in range(first, len(cols["s"])) if cat["root"][j - first] and abs(cat["root"][j - first] - 200) < 0.5)))
    res, seen = [], set()
    for i, label, n in picks:
        k = cols["k"][i]
        media = {}
        for loc in cat["locations"].get(k, []):
            d = ROOT / "outputs" / "studies" / loc["study"] / loc["case"]
            if (d / "animation.webp").exists():
                media = _media_jobs(d, f"catalog/{k[:16]}", out / "media", jobs); break
        res.append({"study": "catalog", "freq": 1.0, "model": "rigid", "group": label, "key": k, "row": i,
                    "thrust": cols["T"][i], "torque": cols["Q"][i], "half_span": cols["H"][i], "tip_twist": None,
                    "status": "ok", "evaluated": n, "root": cat["root"][i - first], "name": cat["name"][i - first],
                    "number": cat["number"][i - first], "media": media, "duplicate": k in seen})
        seen.add(k)
    return res


def candidates(out: Path, jobs: list):
    import elastic_study as S
    rows = list(csv.DictReader(open(ELASTIC / "stiffness" / "stiffness_summary.csv")))
    folder = {"Top #7657": "top_7657", "Middle #3894": "middle_3894", "Rectangle #7835": "rectangle_7835"}
    res = []
    for label, ref in S.CANDIDATES:
        case, _ = S.resolve_wing(ref)
        outline = [[round(s["y_m"] * 1000, 1), round(s["chord_m"] * 1000, 1)] for s in case["sections"]]
        d = ELASTIC / "stiffness" / folder[label]
        levels = []
        for r in (r for r in rows if r["wing"] == label):
            f = lambda k: float(r[k]) if r.get(k) not in (None, "") else None  # noqa: E731
            lvl = r["level"]
            levels.append({"level": lvl, "status": r["status"], "thrust": f("mean_thrust_N"), "torque": f("peak_abs_root_torque_Nm"),
                           "twist": f("tip_twist_amplitude_deg"), "dt": f("dt_s"),
                           "thrust_range": [f("thrust_range_N_min"), f("thrust_range_N_max")] if r.get("thrust_range_N_min") else None,
                           "torque_range": [f("torque_range_Nm_min"), f("torque_range_Nm_max")] if r.get("torque_range_Nm_min") else None,
                           "media": _media_jobs(d / lvl, f"cand/{folder[label]}/{lvl}", out / "media", jobs)})
        montage = None
        if (d / "stiffness_montage.webp").exists():
            jobs.append((str(d / "stiffness_montage.webp"), str(out / "media" / "cand" / folder[label] / "montage.webp"), None))
            montage = f"cand/{folder[label]}/montage.webp"
        res.append({"label": label, "outline": outline, "levels": levels, "montage": montage})
    return res


def refined(out: Path, jobs: list):
    ref = ELASTIC / "refine"
    if not (ref / "summary.csv").exists():
        return []
    res = []
    files = out / "files" / "optimized"; files.mkdir(parents=True, exist_ok=True)
    for r in csv.DictReader(open(ref / "summary.csv")):
        m = r["model"]; d = ref / m
        hist = json.loads((d / "history.json").read_text())
        dtc = json.loads((d / "dt_check.json").read_text())
        outline = [[float(x["spanwise_mm"]), float(x["chord_mm"])] for x in csv.DictReader(open(d / "final_outline.csv"))]
        for ext in ("csv", "svg"):
            shutil.copy2(d / f"final_outline.{ext}", files / f"{m}_outline.{ext}")
        resized_csv = None
        if (d / "baseline_at_budget.json").exists():
            bb = json.loads((d / "baseline_at_budget.json").read_text())
            act = [c for c in bb["chords"] if c > 0]
            resized_csv = f"files/optimized/{m}_campaign_outline_resized.csv"
            with open(out / resized_csv, "w") as fh:
                fh.write("station,spanwise_mm,chord_mm\n")
                for k, c in enumerate(act):
                    fh.write(f"{k},{bb['effective_span'] * 1000 * k / (len(act) - 1):.2f},{c * 1000:.2f}\n")
        if (d / "evolution.gif").exists():
            jobs.append((str(d / "evolution.gif"), str(out / "media" / "refined" / m / "evolution.gif"), None))
        h = hist["history"]
        res.append({
            "model": m, "source": r["source"], "coarse_key": r["coarse_key"],
            "coarse": {"thrust": float(r["coarse_thrust_N"]), "torque": float(r["coarse_torque_Nm"]),
                       "chords": [round(c * 1000, 1) for c in hist["winner"]["chords"]],
                       "half_span": round(hist["winner"]["half_span"] * 1000, 1)},
            "start": {"thrust": h[0]["thrust"], "torque": h[0]["torque"], "status": h[0]["status"]},
            "final": {"thrust": float(r["refined_thrust_N"]), "torque": float(r["refined_torque_Nm"]),
                      "half_span": float(r["refined_half_span_mm"]),
                      "twist": float(r["tip_twist_deg"]) if r["tip_twist_deg"] else None},
            "dt": {"thrust": dtc["thrust"], "torque": dtc["torque"], "status": dtc["status"]},
            # like-for-like baselines on the same fine mesh: the coarse winner's exact outline, as is and
            # with its span resized so peak torque sits at the budget
            **{name: (lambda j: {"thrust": j["thrust"], "torque": j["torque"], "status": j["status"],
                                 "span": round(j["effective_span"] * 1000, 1)})(json.loads((d / f"{name}.json").read_text()))
               for name in ("baseline_fine", "baseline_at_budget") if (d / f"{name}.json").exists()},
            "note": r["note"], "outline": outline, "numerics": hist["numerics"],
            "history": [{"round": x.get("round"), "tag": x.get("tag"), "thrust": x.get("thrust"), "torque": x.get("torque"),
                         "span": round((x.get("span") or 0) * 1000), "status": x.get("status")} for x in h],
            "media": {**_media_jobs(d / "ptera", f"refined/{m}", out / "media", jobs),
                      **({"evolution": f"refined/{m}/evolution.gif"} if (d / "evolution.gif").exists() else {})},
            "files": {"csv": f"files/optimized/{m}_outline.csv", "svg": f"files/optimized/{m}_outline.svg",
                      **({"resized_csv": resized_csv} if resized_csv else {})},
        })
    return res


def build(out: Path = OUT, zip_it: bool = True, workers: int = 8):
    t0 = time.time()
    out.mkdir(parents=True, exist_ok=True)
    jobs: list = []
    data = campaign_rows()
    cat = catalog_rows(data)
    key_index = {k: i for i, k in enumerate(data["cols"]["k"])}
    # winners (+ their animations)
    wins = []
    for w in category_winners():
        if w["key"]:
            d = animation_dir(w["key"])
            w["media"] = _media_jobs(d, f"designs/{w['key'][:16]}", out / "media", jobs) if d else {}
            w["chords"] = [round(c * 1000, 1) for c in w["chords"]]; w["half_span"] = round(w["half_span"] * 1000, 1)
            w["row"] = next((i for i, (k, s) in enumerate(zip(data["cols"]["k"], data["cols"]["s"]))
                             if k == w["key"] and STUDIES[s]["id"] == w["study"]), key_index.get(w["key"]))
        w.pop("dir", None)
        wins.append(w)
    wins += catalog_winners(data, cat, out, jobs)
    cands = candidates(out, jobs)
    refs = refined(out, jobs)
    # extra animations already rendered for any other design (e.g. earlier leaders) are linked from the map
    extra = {}
    for st in STUDIES:
        for d in sorted((CAMPAIGNS / st["dir"] / "animations").glob("*")) if (CAMPAIGNS / st["dir"] / "animations").exists() else []:
            if (d / "animation.webp").exists() and d.name not in extra:
                extra[d.name] = _media_jobs(d, f"designs/{d.name[:16]}", out / "media", jobs)
    # reports and outlines to download
    files = out / "files"; files.mkdir(exist_ok=True)
    pdf = ELASTIC / "report" / "elastic_process_report.pdf"
    if pdf.exists():
        shutil.copy2(pdf, files / pdf.name)
    reports = []
    for st in STUDIES:
        for p in sorted((CAMPAIGNS / st["dir"] / "reports").glob("chunk_*.png")):
            dst = files / "reports" / f"{st['id']}_{p.name}"; dst.parent.mkdir(exist_ok=True); shutil.copy2(p, dst)
            reports.append({"study": st["id"], "file": f"files/reports/{dst.name}", "name": p.stem})
    # shrink media in parallel (skips files already up to date)
    uniq = {j[1]: j for j in jobs}.values()
    with ProcessPoolExecutor(workers) as ex:
        list(ex.map(_shrink_job, uniq))
    payload = {
        "built": time.strftime("%Y-%m-%d %H:%M"), "torque_limit": TORQUE_LIMIT,
        "studies": [{k: v for k, v in s.items() if k != "dir"} for s in STUDIES] + [CATALOG_STUDY],
        "catalog": {k: v for k, v in cat.items() if k != "locations"},
        "models": [{"id": m[0], "label": m[1], "thickness": m[2], "rod": m[3]} for m in MODELS],
        **{k: data[k] for k in ("freqs", "statuses", "unique")},
        "cols": data["cols"], "ranges": data["ranges"],
        "winners": wins, "candidates": cands, "refined": refs,
        "media": {k[:16]: v for k, v in extra.items()},
        "reports": reports, "pdf": f"files/{pdf.name}" if pdf.exists() else None,
    }
    blob = json.dumps(payload, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    page = (HERE / "elastic_atlas.html").read_text(encoding="utf-8")
    marker = "/*__ATLAS_DATA__*/"
    if marker not in page:
        raise ValueError("data marker missing from elastic_atlas.html")
    (out / "index.html").write_text(page.replace(marker, blob), encoding="utf-8")
    (out / "README.txt").write_text(README, encoding="utf-8")
    result = {"folder": str(out), "designs": len(data["cols"]["s"]), "unique": data["unique"],
              "data_mb": round(len(blob) / 1e6, 1), "seconds": round(time.time() - t0)}
    if zip_it:
        z = out.parent / "Elastic_Wing_Atlas.zip"
        with zipfile.ZipFile(z, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for p in sorted(out.rglob("*")):
                if p.is_file():
                    zf.write(p, Path("Elastic_Wing_Atlas") / p.relative_to(out))
        result["zip"] = str(z); result["zip_mb"] = round(z.stat().st_size / 1e6, 1)
    return result


def _shrink_job(j):
    try:
        return _shrink(j[0], j[1], poster=j[2])
    except Exception as exc:  # noqa: BLE001
        print("media failed:", j[0], exc, flush=True)


README = """ELASTIC WING ATLAS

1. Unzip this folder (keep index.html next to the media/ and files/ folders).
2. Double-click index.html. It opens in any modern browser (Chrome, Firefox, Edge, Safari).

No installation, Python, Ptera, server or internet connection is needed.

Tabs
  Overview          headline results, what each study is, how to read the numbers
  Wing map          every simulated design; scroll to zoom, drag to pan, hover to see the wing,
                    click for details and its Ptera animation when one was rendered
  Winners           best design per study, frequency and plate model under the 1 N·m torque budget
  Stiffness effects the three manufactured wings across sheets, same-shape comparisons,
                    and frequency trends
  Optimized shapes  the fine-mesh smooth-curve refinements, with CSV/SVG outlines to download

All loads are per wing. Thrust = mean thrust over the last cycle; torque = peak |root roll moment|.
"Verified" means numerically repeatable (two stabilization settings agree within 3%), not
experimentally validated. The full method is in files/elastic_process_report.pdf.
"""


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("render"); r.add_argument("--workers", type=int, default=6)
    b = sub.add_parser("build"); b.add_argument("--out", type=Path, default=OUT); b.add_argument("--no-zip", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "render":
        render(a.workers)
    else:
        print(build(a.out, zip_it=not a.no_zip))


if __name__ == "__main__":
    main()
