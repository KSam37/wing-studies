"""Pull-request rules from CONTRIBUTING.md, checked in CI.

    python tools/check_pr.py BASE        # e.g. HEAD^1 on GitHub's pull-request merge commit

1. One study per pull request: a PR that touches studies/<id>/ touches nothing else.
2. Results are immutable: once BASE has studies/<id>/results.json, that study's
   spec.json, results.json and status.json cannot be modified, renamed or deleted.
3. Generated data (atlas/data, atlas/media) may change only through the tools;
   CI cannot tell how a file was made, so it prints a reminder rather than failing.

Exit status 1 lists every broken rule.
"""
from __future__ import annotations

import subprocess
import sys

FROZEN = ("spec.json", "results.json", "status.json")
GENERATED = ("atlas/data/", "atlas/media/")


def study_of(path: str) -> str | None:
    parts = path.split("/")
    return parts[1] if len(parts) >= 3 and parts[0] == "studies" else None


def problems(changes: list[tuple[str, ...]], has_results) -> tuple[list[str], list[str]]:
    """changes: (status, path) or (R/C status, old, new) as from `git diff --name-status`.
    has_results(id) -> bool: does BASE already hold studies/<id>/results.json?
    Returns (errors, notices)."""
    errors, notices = [], []
    studies, others = set(), []
    for st, *paths in changes:
        for p in paths:
            sid = study_of(p)
            if sid:
                studies.add(sid)
            elif p not in others:
                others.append(p)
    if len(studies) > 1:
        errors.append("one study per pull request: this one touches " + ", ".join(f"studies/{s}/" for s in sorted(studies)))
    if studies and others:
        errors.append("a study pull request changes only studies/<id>/; move these to a separate PR: "
                      + ", ".join(others[:10]) + (" ..." if len(others) > 10 else ""))
    for st, *paths in changes:
        kind = st[:1]
        touched = paths if kind in "RC" else paths[:1]
        if kind == "C":
            touched = paths[1:]          # copying out of a study leaves it unchanged
        for p in touched:
            sid = study_of(p)
            if not sid or p.split("/", 2)[2] not in FROZEN or kind == "A":
                continue
            if has_results(sid):
                verb = {"M": "modifies", "D": "deletes", "R": "renames", "T": "changes the type of"}.get(kind, "changes")
                errors.append(f"results are immutable: this PR {verb} {p}, but studies/{sid}/ already has results. "
                              "Start a new study and name this one as its parent.")
    gen = sorted({p for _, *paths in changes for p in paths if p.startswith(GENERATED)})
    if gen:
        notices.append(f"{len(gen)} generated file(s) under atlas/ changed; the PR should name the tool command that "
                       "wrote them (CONTRIBUTING.md, 'No hand edits to generated data').")
    return errors, notices


def _git(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], text=True, capture_output=True)


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(__doc__, file=sys.stderr)
        return 2
    base = argv[0]
    out = _git("diff", "--name-status", "-M", base, "HEAD")
    if out.returncode:
        print(out.stderr, file=sys.stderr)
        return 2
    changes = [tuple(line.split("\t")) for line in out.stdout.splitlines() if line.strip()]
    errors, notices = problems(changes, lambda sid: _git("cat-file", "-e", f"{base}:studies/{sid}/results.json").returncode == 0)
    for n in notices:
        print(f"::notice::{n}")
    for e in errors:
        print(f"::error::{e}")
    print(f"{len(changes)} changed path(s); " + ("pull-request rules hold" if not errors else f"{len(errors)} rule(s) broken"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
