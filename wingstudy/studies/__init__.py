"""Planned studies: a spec in studies/<id>/spec.json, solved locally, published by pull request.

    python -m wingstudy new 2026-11-20-my-question         # write a spec template
    python -m wingstudy validate --all                     # check every spec (CI runs this)
    python -m wingstudy plan 2026-11-20-my-question        # case count, cache hits, time estimate
    python -m wingstudy run 2026-11-20-my-question         # solve; results.json + status.json
    python -m wingstudy publish 2026-11-20-my-question     # branch, commit, push, open a PR

spec.py   the spec contract (validation and expansion)
run.py    the solver side (wraps the campaign engines, caches by key)
atlas.py  folds completed studies into the atlas at site-build time
"""
