# Contributing

These rules apply to everyone, people and agents alike. They keep every published number traceable to an exact input.

## One pull request per study

- A study PR changes only `studies/<id>/` for a single study. Code, docs and atlas changes go in their own PRs.
- Name the branch `study/<id>`. `tools\wingstudy.cmd publish <id>` does this for you.
- A spec can go in a PR before the study is run (the study is then *proposed*). The results go in a later PR on the same branch, or in a new one.

## Results are immutable

- Once a study has a `results.json` on `main`, its `spec.json` and `results.json` never change. To ask a different question, or the same question with different settings, start a new study and name the old one as its `parent`.
- `validate` rejects results whose `spec_sha256` no longer matches the spec. CI rejects any PR that modifies or deletes a run study's spec or results.
- Failed and unverified cases stay in the results. Don't remove them to tidy a study.

## No hand edits to generated data

These files are written by tools. Change them only by running the tool, and name the command in the PR:

| Files | Written by |
|---|---|
| `studies/<id>/results.json`, `status.json` | `wingstudy run` |
| `atlas/data/**` | `tools/atlas_data.py` (and the campaign publishers) |
| `atlas/media/**` | the campaign media renderers and `tools/compress_media.py` |
| `_site/` | `tools/build_site.py` (never committed) |

`site/new/spec.js` is maintained by hand, but it must stay identical in behaviour to `wingstudy/studies/spec.py`. `tests/builder.test.cjs` checks this.

## Merging

A person merges every PR after CI passes. Nothing is merged automatically, and agents never merge (see [AGENTS.md](AGENTS.md)).

## What CI checks on a pull request

- Every study spec and results file is valid (`python -m wingstudy validate --all`).
- The PR follows the study rules above (`tools/check_pr.py`).
- The standard-library tests pass and the builder matches the Python validator.
- The site builds, the atlas UI checks pass, and every media file the atlas references exists.

The solver tests need the registered Ptera environment, so CI doesn't run them. Run them locally before you change model code (see [docs/system-guide.md](docs/system-guide.md#13-verification-and-confidence)).
