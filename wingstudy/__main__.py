"""wingstudy command line: one entry point for the study tools.

Planned studies (studies/<id>/spec.json -> results -> pull request):

    python -m wingstudy new NAME [--kind design-set|geometry-sweep|matched-comparison]
    python -m wingstudy validate ID... | --all
    python -m wingstudy plan ID [--workers N]        case count, cache hits, time estimate
    python -m wingstudy run ID [--workers N]         solve; writes results.json and status.json
    python -m wingstudy publish ID                   study/<id> branch, push, open a PR (never merges)
    python -m wingstudy list

Campaign tools:

    python -m wingstudy dashboard [args]   span-flex campaign dashboard (elastic_campaign dashboard)
    python -m wingstudy campaign  [args]   elastic campaign tool: dashboard | replay | ... (elastic_campaign)
    python -m wingstudy frontier  [args]   matched chordwise/spanwise frontier rerun (span_frontier)
    python -m wingstudy spanfree  [args]   1 N·m budget search with continuous half-span (elastic_spanfree)
    python -m wingstudy study     [args]   validation, stiffness and sampled studies (elastic_study)
    python -m wingstudy refine    [args]   fine-mesh refinement of winners (elastic_refine)
    python -m wingstudy span-atlas [args]  span comparison export (span_atlas)
    python -m wingstudy report    [args]   PDF report of a campaign (elastic_report)
    python -m wingstudy fingerprint        structural-code fingerprint used by saved plans

Each command forwards its remaining arguments to the module's own command line, so
`python -m wingstudy frontier --help` shows that tool's options.
"""
from __future__ import annotations

import runpy
import sys

COMMANDS = {
    "campaign": "wingstudy.elastic_campaign",
    "frontier": "wingstudy.span_frontier",
    "spanfree": "wingstudy.elastic_spanfree",
    "study": "wingstudy.elastic_study",
    "refine": "wingstudy.elastic_refine",
    "span-atlas": "wingstudy.span_atlas",
    "report": "wingstudy.elastic_report",
    "evolution": "wingstudy.elastic_evolution",
}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    cmd, rest = argv[0], argv[1:]
    from .studies.cli import COMMANDS as STUDY_COMMANDS
    if cmd in STUDY_COMMANDS:
        from .studies.cli import main as study_main
        return study_main(cmd, rest)
    if cmd == "fingerprint":
        from . import identity
        print(identity.structural_fingerprint())
        return 0
    if cmd == "dashboard":
        cmd, rest = "campaign", ["dashboard", *rest]
    if cmd not in COMMANDS:
        print(f"unknown command {cmd!r}\n{__doc__}", file=sys.stderr)
        return 2
    sys.argv = [COMMANDS[cmd], *rest]
    runpy.run_module(COMMANDS[cmd], run_name="__main__", alter_sys=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
