"""Commands for planned studies: new, import, validate, plan, run, publish, list,
convergence, convergence-report, polish, favorite."""
from __future__ import annotations

import argparse
import re
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import spec as S

COMMANDS = ("new", "import", "validate", "plan", "run", "publish", "list", "convergence", "convergence-report",
            "polish", "favorite")
FAVORITES = S.ROOT / "atlas" / "favorites.json"
FAV_KEY_RE = re.compile(r"^[0-9a-f]{20}(?:[0-9a-f]{4})?$")   # study designs: 24 hex; refine_top solves: 20

# Studies estimated above this many minutes (the maximum, for searches) need a person's go-ahead:
# `run` asks at a terminal and refuses when no one is there, unless --yes is given.
LARGE_MINUTES = 30


def _id(arg: str) -> str:
    """Accept a study id or a path to its folder or spec.json."""
    p = Path(arg)
    if p.name == "spec.json":
        p = p.parent
    return p.name if (p.exists() or "/" in arg or "\\" in arg) else arg


def cmd_new(a) -> int:
    sid = a.id if S.ID_RE.fullmatch(a.id) else f"{dt.date.today():%Y-%m-%d}-{a.id}"
    folder = S.study_dir(sid)
    if (folder / "spec.json").exists():
        print(f"{folder / 'spec.json'} already exists", file=sys.stderr)
        return 1
    spec = S.template(sid, a.kind, a.author or "")
    S.write_json(folder / "spec.json", spec)
    print(f"wrote {folder / 'spec.json'}\nEdit it, then: python -m wingstudy validate {sid}")
    return 0


def _validate_one(sid: str) -> list[str]:
    folder = S.study_dir(sid)
    try:
        spec = S.load(sid)
    except FileNotFoundError:
        return [f"{folder / 'spec.json'}: missing"]
    except json.JSONDecodeError as exc:
        return [f"spec.json: not valid JSON ({exc})"]
    e = S.validate(spec)
    if not e and spec["id"] != folder.name:
        e.append(f"id: {spec['id']!r} must match the folder name {folder.name!r}")
    e += _atlas_key_errors(spec) if not e else []
    if not e and (folder / "results.json").exists():
        from .run import results_errors
        e += results_errors(S.read_json(folder / "results.json"), spec)
    return e


def _atlas_key_errors(spec: dict) -> list[str]:
    keys = (spec.get("wings") or {}).get("from_atlas") or []
    if not keys or not (S.ROOT / "atlas" / "data" / "rows").exists():
        return []
    try:
        S.atlas_wings(keys)
    except KeyError as exc:
        return [f"wings.from_atlas: {exc.args[0]}"]
    return []


def cmd_import(a) -> int:
    """Put a spec downloaded from the website builder where the study tools expect it."""
    src = Path(a.file)
    try:
        spec = json.loads(src.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read {src}: {exc}", file=sys.stderr)
        return 1
    e = S.validate(spec) or _atlas_key_errors(spec)
    if e:
        print("not a valid study spec:\n  " + "\n  ".join(e), file=sys.stderr)
        return 1
    dest = S.study_dir(spec["id"]) / "spec.json"
    if dest.exists() and S.read_json(dest) != spec:
        print(f"{dest} already exists with different content; choose another id", file=sys.stderr)
        return 1
    S.write_json(dest, spec)
    print(f"imported {spec['id']} ({S.case_count(spec)} cases)\nnext: python -m wingstudy plan {spec['id']}")
    return 0


def cmd_validate(a) -> int:
    ids = sorted(p.name for p in S.STUDIES.glob("*/") if (p / "spec.json").exists()) if a.all else [_id(x) for x in a.ids]
    if not ids:
        print("no studies to validate")
        return 0 if a.all else 2
    bad = 0
    for sid in ids:
        e = _validate_one(sid)
        if e:
            bad += 1
            print(f"FAIL {sid}")
            for x in e:
                print(f"     {x}")
        else:
            print(f"ok   {sid}")
    return 1 if bad else 0


def cmd_plan(a) -> int:
    from .run import plan
    p = plan(_id(a.id), workers=a.workers)
    if a.json:
        print(json.dumps(p, indent=1))
    elif p["kind"] == "evolutionary":
        print(f"{p['study']} (evolutionary): {p['searches']} search(es) x {p['lineages_per_search']} lineage(s), at most {p['cases']} solves, "
              f"typically about {p['to_solve']}.\nEstimated {p['estimated_minutes']} min (at most {p['estimated_minutes_max']}) with "
              f"{p['workers']} worker(s); cached solves are reused. Code identity {p['code']}.")
    else:
        print(f"{p['study']} ({p['kind']}): {p['cases']} cases, {p['cached']} already solved, {p['to_solve']} to solve.\n"
              f"Estimated {p['estimated_minutes']} min with {p['workers']} worker(s). Code identity {p['code']}.")
    return 0


def cmd_run(a) -> int:
    from .run import run
    sid = _id(a.id)
    if not a.yes:
        from .run import plan
        p = plan(sid, workers=a.workers)
        most = p.get("estimated_minutes_max", p["estimated_minutes"])
        print(f"{p['to_solve']} cases to solve, about {p['estimated_minutes']} min"
              + (f" (at most {most})" if most != p["estimated_minutes"] else "") + ".")
        if most > LARGE_MINUTES:
            if not sys.stdin.isatty():
                print(f"Not starting: this study may take more than {LARGE_MINUTES} min and no one is at the terminal. "
                      "Rerun with --yes once a person has approved it.", file=sys.stderr)
                return 3
            if input("Start it? [y/N] ").strip().lower() not in ("y", "yes"):
                print("not started")
                return 1
        print("Starting.")
    out = run(sid, workers=a.workers, force=a.force)
    failed = out["counts"].get("failed", 0)
    print(f"results: {S.study_dir(sid) / 'results.json'}" + (f"  ({failed} failed)" if failed else ""))
    print(f"next: python -m wingstudy publish {sid}")
    return 0


def _git(*args, check=True, capture=False):
    return subprocess.run(["git", *args], cwd=S.ROOT, check=check, text=True,
                          capture_output=capture)


def cmd_publish(a) -> int:
    """Put studies/<id>/ on its own branch and open a pull request. Never merges."""
    sid = _id(a.id)
    e = _validate_one(sid)
    folder = S.study_dir(sid)
    if not a.spec_only and not (folder / "results.json").exists():
        e.append("results.json: missing; run the study first, or use --spec-only to propose it")
    if e:
        print("cannot publish:\n  " + "\n  ".join(e), file=sys.stderr)
        return 1
    spec = S.load(sid)
    results = None if a.spec_only else S.read_json(folder / "results.json")
    branch = f"study/{sid}"
    rel = folder.relative_to(S.ROOT).as_posix()
    add = f"{rel}/spec.json" if a.spec_only else rel
    start = _git("rev-parse", "--abbrev-ref", "HEAD", capture=True).stdout.strip()
    import tempfile
    keep = Path(tempfile.mkdtemp(prefix="wingstudy-publish-")) / sid
    shutil.copytree(folder, keep)       # switching back to `start` may remove files only the study branch tracks
    stash = False
    if _git("status", "--porcelain", "--", ".", f":!{rel}", capture=True).stdout.strip():
        _git("stash", "push", "--include-untracked", "-m", f"wingstudy publish {sid}", "--", ".", f":!{rel}")
        stash = True
    try:
        _git("fetch", "origin", "main")
        _git("checkout", "-B", branch, "origin/main")
        _git("add", "--", add)
        if a.spec_only:
            from .run import plan
            p = plan(sid, workers=4)
            size = (f"at most {p['cases']} solves (typically about {p['to_solve']}), about {p['estimated_minutes']} min "
                    f"(at most {p['estimated_minutes_max']}) on 4 workers" if spec["kind"] == "evolutionary" else
                    f"{p['cases']} cases, about {p['estimated_minutes']} min on 4 workers")
            msg = f"Propose study {sid}: {spec['title']}\n\n{spec['question']}\n\nPlan: {size}; code identity {p['code']}.\n"
        else:
            counts = ", ".join(f"{v} {k}" for k, v in sorted(results["counts"].items()))
            msg = (f"Study {sid}: {spec['title']}\n\n{spec['question']}\n\n"
                   f"{len(results['cases'])} cases ({counts}); code identity {results['code']['digest']}.\n")
        _git("commit", "-m", msg)
        if a.no_push:
            print(f"committed on {branch}; not pushed (--no-push)")
            return 0
        _git("push", "-u", "origin", branch, "--force-with-lease")
        if shutil.which("gh") is None:
            print(f"pushed {branch}. Install the GitHub CLI (gh) or open the pull request on GitHub.")
            return 0
        if a.spec_only:
            body = (f"**Proposed study.** {spec['question']}\n\n**Author.** {spec['author']} · **Kind.** {spec['kind']} · "
                    f"**Plan.** {size}\n\nCode identity `{p['code']}`. No results yet: merging records the proposal; "
                    "a person decides when it runs.\n")
            title = f"Propose study {sid}: {spec['title']}"
        else:
            body = (f"**Question.** {spec['question']}\n\n**Author.** {spec['author']} · **Kind.** {spec['kind']} · "
                    f"**Cases.** {len(results['cases'])} ({counts})\n\n"
                    f"Code identity `{results['code']['digest']}` (structural `{results['code']['structural'][:12]}`, "
                    f"Ptera {results['code'].get('ptera')}).\n\n"
                    "CI validates the spec and results and builds the site with this study merged into the atlas. "
                    "A person merges this pull request; it is never merged automatically.\n")
            title = f"Study {sid}: {spec['title']}"
        r = subprocess.run(["gh", "pr", "create", "--base", "main", "--head", branch, "--title",
                            title, "--body", body], cwd=S.ROOT, text=True)
        return r.returncode
    finally:
        _git("checkout", start, check=False)
        shutil.copytree(keep, folder, dirs_exist_ok=True)
        shutil.rmtree(keep.parent, ignore_errors=True)
        if stash:
            _git("stash", "pop", check=False)


def cmd_list(a) -> int:
    rows = []
    for p in sorted(S.STUDIES.glob("*/")):
        if not (p / "spec.json").exists():
            continue
        st = S.read_json(p / "status.json") if (p / "status.json").exists() else {"state": "proposed"}
        try:
            title = S.read_json(p / "spec.json").get("title", "")
        except json.JSONDecodeError:
            title = "(spec.json is not valid JSON)"
        rows.append((p.name, st.get("state", "?"), f"{st.get('done', 0)}/{st.get('total', '?')}", title))
    if not rows:
        print("no studies yet: python -m wingstudy new my-question")
    for r in rows:
        print(f"{r[0]:<44} {r[1]:<9} {r[2]:>9}  {r[3]}")
    return 0


def _sources(ids) -> list[dict] | None:
    out = []
    for sid in ids:
        rp = S.study_dir(_id(sid)) / "results.json"
        if not rp.exists():
            print(f"{_id(sid)}: no results.json yet; run the study first", file=sys.stderr)
            return None
        out.append(S.read_json(rp))
    return out


def _write_new(spec: dict) -> int:
    dest = S.study_dir(spec["id"]) / "spec.json"
    if dest.exists():
        print(f"{dest} already exists; choose another --id", file=sys.stderr)
        return 1
    e = S.validate(spec)
    if e:
        print("could not build a valid spec:\n  " + "\n  ".join(e), file=sys.stderr)
        return 1
    S.write_json(dest, spec)
    return 0


def _default_id(kind: str, first: str) -> str:
    return f"{dt.date.today():%Y-%m-%d}-{kind}-{_id(first).split('-', 3)[-1]}"[:80].rstrip("-")


def cmd_convergence(a) -> int:
    """Write a convergence (refinement-ladder) study for designs of finished studies."""
    from . import convergence as CV
    sources = _sources(a.sources)
    if sources is None:
        return 1
    keys = list(a.keys or [])
    if a.favorites:
        keys += [f["key"] for f in _favorites()["favorites"]]
    picks = CV.select(sources, top=a.top, sample=a.sample, seed=a.seed, keys=keys,
                      torque_window=tuple(a.torque) if a.torque else None)
    found = {x["key"] for x in picks}
    extra = [k for k in dict.fromkeys(keys) if k not in found and S.KEY_RE.fullmatch(k) and _atlas_try(k)]
    sid = a.id or _default_id("convergence", a.sources[0])
    if not S.ID_RE.fullmatch(sid):
        print(f"--id {sid!r}: YYYY-MM-DD-short-name", file=sys.stderr)
        return 1
    try:
        spec = CV.make_spec(sid, sources, picks, author=a.author, extra_atlas=extra)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    if _write_new(spec):
        return 1
    roles = {r: sum(x["role"] == r for x in picks) for r in ("top", "sample", "pick")}
    print(f"wrote {S.study_dir(sid) / 'spec.json'}: {roles['top']} top, {roles['sample']} sampled, "
          f"{roles['pick'] + len(extra)} picked designs, {S.case_count(spec)} cases ({len(CV.LADDER)} numerics levels each)\n"
          f"next: python -m wingstudy plan {sid} --workers 16, then run it; then python -m wingstudy convergence-report {sid}")
    return 0


def _atlas_try(k):
    try:
        return S.atlas_wings([k])
    except (KeyError, FileNotFoundError):
        return []


def cmd_convergence_report(a) -> int:
    from . import convergence as CV
    sid = _id(a.id)
    spec, rp = S.load(sid), S.study_dir(sid) / "results.json"
    if not rp.exists():
        print(f"{sid}: no results.json yet", file=sys.stderr)
        return 1
    m = CV.metrics(spec, S.read_json(rp))
    print(json.dumps(m, indent=1) if a.json else CV.report(m))
    return 0


def cmd_polish(a) -> int:
    """Write a follow-up search seeded from the best shapes of finished studies (before/after)."""
    from . import polish as PO
    sources = _sources(a.sources)
    if sources is None:
        return 1
    sid = a.id or _default_id("polish", a.sources[0])
    try:
        spec = PO.make_spec(sid, sources, top=a.top, step_mm=a.step, span_step_mm=a.span_step,
                            solves=a.solves, author=a.author, max_half_span_mm=a.max_span)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    if _write_new(spec):
        return 1
    print(f"wrote {S.study_dir(sid) / 'spec.json'}: {S.lineages_per_search(spec)} seeds x "
          f"{len(spec['search']['objectives'])} objective(s), up to {S.case_count(spec)} solves\n"
          f"next: python -m wingstudy plan {sid} --workers 16, then run it. The atlas's Optimized shapes tab "
          "shows each seed before and after.")
    return 0


def _favorites() -> dict:
    if FAVORITES.exists():
        return S.read_json(FAVORITES)
    return {"schema": "wingstudy/favorites@1", "favorites": []}


def cmd_favorite(a) -> int:
    """Shared favourites (atlas/favorites.json): designs worth building, starred in the atlas."""
    fav = _favorites()
    if a.list or not a.keys:
        for f in fav["favorites"]:
            print(f"{f['key']}  {f.get('added', ''):<11} {f.get('note', '')}")
        if not fav["favorites"]:
            print('no favourites yet: python -m wingstudy favorite KEY --note "why"')
        return 0
    bad = [k for k in a.keys if not FAV_KEY_RE.fullmatch(k)]
    if bad:
        print(f"not atlas design keys (24 hex characters, or 20 for an optimized wing): {', '.join(bad)}", file=sys.stderr)
        return 1
    have = {f["key"]: f for f in fav["favorites"]}
    for k in a.keys:
        if a.remove:
            have.pop(k, None)
            continue
        old = have.get(k, {})
        have[k] = {"key": k, "note": a.note if a.note is not None else old.get("note", ""),
                   "added": old.get("added") or f"{dt.date.today():%Y-%m-%d}",
                   **({"by": a.author} if a.author else ({"by": old["by"]} if old.get("by") else {}))}
    fav["favorites"] = sorted(have.values(), key=lambda f: (f["added"], f["key"]))
    S.write_json(FAVORITES, fav)
    print(f"{'removed' if a.remove else 'saved'} {len(a.keys)}; {len(fav['favorites'])} favourite(s) in {FAVORITES}. "
          "Commit it in a pull request to share the stars on the site.")
    return 0


def main(cmd: str, argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog=f"python -m wingstudy {cmd}", description=__doc__)
    if cmd == "new":
        ap.add_argument("id", help="YYYY-MM-DD-name, or just a name (today's date is added)")
        ap.add_argument("--kind", choices=S.KINDS, default="evolutionary")
        ap.add_argument("--author", default="")
    elif cmd == "import":
        ap.add_argument("file", help="a spec.json downloaded from the website's study builder")
    elif cmd == "validate":
        ap.add_argument("ids", nargs="*")
        ap.add_argument("--all", action="store_true", help="every study in studies/")
    elif cmd in ("plan", "run"):
        ap.add_argument("id")
        ap.add_argument("--workers", type=int, default=1)
        if cmd == "plan":
            ap.add_argument("--json", action="store_true")
        else:
            ap.add_argument("--force", action="store_true", help="overwrite results made from a different spec")
            ap.add_argument("--yes", action="store_true",
                            help=f"skip the estimate and the go-ahead question for studies over {LARGE_MINUTES} min")
    elif cmd == "publish":
        ap.add_argument("id")
        ap.add_argument("--no-push", action="store_true", help="commit on the study branch only")
        ap.add_argument("--spec-only", action="store_true", help="propose the study: commit only spec.json, no results needed")
    elif cmd == "convergence":
        ap.add_argument("sources", nargs="+", help="finished study ids whose designs to check")
        ap.add_argument("--top", type=int, default=3, help="best lineage results per search, winner first (default 3)")
        ap.add_argument("--sample", type=int, default=30, help="random other verified designs (default 30)")
        ap.add_argument("--seed", type=int, default=0, help="random seed for the sample")
        ap.add_argument("--torque", type=float, nargs=2, metavar=("LO", "HI"),
                        help="sample only designs with peak torque in [LO, HI] N*m")
        ap.add_argument("--keys", nargs="*", help="extra design keys (from the sources or the campaign atlas)")
        ap.add_argument("--favorites", action="store_true", help="also check every design in atlas/favorites.json")
        ap.add_argument("--id", help="study id (default: today's date, 'convergence' and the first source's name)")
        ap.add_argument("--author", default="")
    elif cmd == "convergence-report":
        ap.add_argument("id")
        ap.add_argument("--json", action="store_true")
    elif cmd == "polish":
        ap.add_argument("sources", nargs="+", help="finished evolutionary study ids")
        ap.add_argument("--top", type=int, default=3, help="best lineage results per search to re-seed (default 3)")
        ap.add_argument("--step", type=float, default=10.0, help="chord step in mm (default 10, half-step 5)")
        ap.add_argument("--span-step", type=float, default=20.0, help="half-span step in mm, 0 = fixed (default 20)")
        ap.add_argument("--solves", type=int, default=150, help="most solves per lineage (default 150)")
        ap.add_argument("--max-span", type=float, default=800.0, help="upper half-span limit in mm (400 = single sheet)")
        ap.add_argument("--id")
        ap.add_argument("--author", default="")
    elif cmd == "favorite":
        ap.add_argument("keys", nargs="*", help="atlas design keys (shown in the atlas's Design details)")
        ap.add_argument("--note", help="why it is a favourite, e.g. 'built 28 Nov'")
        ap.add_argument("--remove", action="store_true")
        ap.add_argument("--list", action="store_true")
        ap.add_argument("--author", default="")
    a = ap.parse_args(argv)
    if cmd == "validate" and not a.all and not a.ids:
        ap.error("give study ids or --all")
    return {"new": cmd_new, "import": cmd_import, "validate": cmd_validate, "plan": cmd_plan, "run": cmd_run,
            "publish": cmd_publish, "list": cmd_list, "convergence": cmd_convergence,
            "convergence-report": cmd_convergence_report, "polish": cmd_polish, "favorite": cmd_favorite}[cmd](a)
