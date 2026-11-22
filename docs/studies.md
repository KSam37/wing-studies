# Planned studies

A planned study is how a new simulation question enters the project. Each study is a folder `studies/<id>/` containing:

- `spec.json`: what to solve. It can't change once the study has run.
- `status.json`: proposed, running or complete.
- `results.json`, once run: compact results plus an exact replay input for every case.

[`schema/study-spec.schema.json`](../schema/study-spec.schema.json) documents the spec. The rules are in `wingstudy/studies/spec.py`.

## Kinds

- **`evolutionary`** runs the campaigns' coordinate climb ([coordinate-search.md](coordinate-search.md)).
  - Every model × frequency × objective combination is one search. Each search runs one lineage per seed: each seed half-span crossed with each seed family, plus any seed wings.
  - An objective is either a torque budget (maximum thrust with peak torque ≤ B) or a λ trade-off (T/T<sub>ref</sub> − λ·M/M<sub>ref</sub>, with the references taken from the search's valid seeds).
  - The `search` block also sets the solves per lineage, the chord step, the smallest chord and whether chords must decrease toward the tip.
  - **Free span.** With `span_step_mm` > 0 the half-span is one more search coordinate. Each pass tries it first (± the step, one half-step retry, then retired, like a chord); the stations stretch with it and the root chord stays fixed. `half_span_limits_mm` bounds it, and the seeds must lie inside. With 0 (the default) each lineage keeps its seed span, as in the campaigns.
  - `results.json` records every lineage's accepted steps and each search's winner. The atlas animates each winner's shape evolution from them.
- **`geometry-sweep`** samples outlines with scrambled Sobol points under the campaign rules. There is no climbing.
- **`design-set`** ("Re-solve chosen wings") re-solves named outlines and/or atlas designs (by key) for every model, frequency and numerical setting.

`structure` is `chordwise`, `spanwise` or `matched`. With `matched`, every wing is solved both chordwise-only and with spanwise bending. A matched evolutionary search climbs chordwise, then re-solves each search winner as a matched pair. Rigid models can't be combined with `spanwise` or `matched`.

## Workflow

```powershell
tools\wingstudy.cmd new my-question --kind evolutionary  # writes studies/<today>-my-question/spec.json
tools\wingstudy.cmd validate 2026-11-20-my-question      # every problem, in plain words
tools\wingstudy.cmd plan 2026-11-20-my-question --workers 4
tools\wingstudy.cmd publish 2026-11-20-my-question --spec-only   # optional: propose it as a PR first
tools\wingstudy.cmd run 2026-11-20-my-question --workers 4
tools\wingstudy.cmd publish 2026-11-20-my-question       # study/<id> branch, push, pull request
```

- **The website builder** ([samkir.com/wing-studies/new](https://samkir.com/wing-studies/new/)) writes specs with the same rules as the Python tools. In the atlas, *Add to a new study* picks wings for it. *Submit on GitHub* opens a prefilled `studies/<id>/spec.json`. *Download spec.json* saves the file instead, and `tools\wingstudy.cmd import spec.json` puts it in place. The builder's *Queue* tab lists every study and its state.
- **`plan`** reports the case count, the cached cases and a time estimate. Searches stop early, so for them it gives a typical figure and a maximum.
- **`run`** asks before starting a study estimated at more than 30 minutes. When no one is at the terminal it refuses such a study unless you pass `--yes`.
- **The cache.** Every solved case is cached in `outputs/study-cache/` under a key covering the outline, model, motion, numerics and code identity (structural and solve-path source, Ptera and library versions). Reruns and later studies reuse identical solves, and a code change forces a re-solve.
- **Results are immutable.** Once a study has run, change nothing in its spec. Start a new study and name the old one as its `parent`.
- **`publish`** commits only `studies/<id>/` and opens a pull request. CI validates the PR and builds the site with the study merged into the atlas. A person merges it. After the merge, the study appears in the atlas as its own study, with its designs marked "found by a planned study".

[CONTRIBUTING.md](../CONTRIBUTING.md) has the rules for study pull requests.
