"""Commands for planned studies: new, import, validate, plan, run, publish, list."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import spec as S

COMMANDS = ("new", "import", "validate", "plan", "run", "publish", "list")


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
        print(f"{p['to_solve']} cases to solve, about {p['estimated_minutes']} min. Starting.")
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
    if not (folder / "results.json").exists():
        e.append("results.json: missing; run the study first")
    if e:
        print("cannot publish:\n  " + "\n  ".join(e), file=sys.stderr)
        return 1
    spec, results = S.load(sid), S.read_json(folder / "results.json")
    branch = f"study/{sid}"
    rel = folder.relative_to(S.ROOT).as_posix()
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
        _git("add", "--", rel)
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
        body = (f"**Question.** {spec['question']}\n\n**Author.** {spec['author']} · **Kind.** {spec['kind']} · "
                f"**Cases.** {len(results['cases'])} ({counts})\n\n"
                f"Code identity `{results['code']['digest']}` (structural `{results['code']['structural'][:12]}`, "
                f"Ptera {results['code'].get('ptera')}).\n\n"
                "CI validates the spec and results and builds the site with this study merged into the atlas. "
                "A person merges this pull request; it is never merged automatically.\n")
        r = subprocess.run(["gh", "pr", "create", "--base", "main", "--head", branch, "--title",
                            f"Study {sid}: {spec['title']}", "--body", body], cwd=S.ROOT, text=True)
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
            ap.add_argument("--yes", action="store_true", help="skip the estimate")
    elif cmd == "publish":
        ap.add_argument("id")
        ap.add_argument("--no-push", action="store_true", help="commit on the study branch only")
    a = ap.parse_args(argv)
    if cmd == "validate" and not a.all and not a.ids:
        ap.error("give study ids or --all")
    return {"new": cmd_new, "import": cmd_import, "validate": cmd_validate, "plan": cmd_plan, "run": cmd_run,
            "publish": cmd_publish, "list": cmd_list}[cmd](a)
