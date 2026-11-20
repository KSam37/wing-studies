# Wing Studies restructuring plan

*Drafted 19 Nov 2026. Status: decisions taken, not yet started.*

## Decisions taken (19 Nov 2026)

- **One repo: `KSam37/wing-studies`** (currently private, default branch `main`, collaborator `mattfern902`). We write to `main`.
- **Aim:** take the prototype to a polished research tool that can be shared with the community.
- **Data that matters:** the ~60k wings in the atlas (55,170 unique catalog wings plus campaign, refined and spanwise rows). The old rigid studies in `outputs/studies` (3.7 GB) and the master SQLite/Excel catalogs are **legacy**. They stay local, isolated in an archive folder, and are not pushed again.
- **Animations:** recompress or shorten. If they still don't fit, the site goes without animations and they stay local. A test gave about **14× reduction** (see Media below), so they should fit.
- **Ptera** is a third-party tool (Cam Urban, MIT license). It becomes a pinned dependency, credited in the README, the site footer and `CITATION.cff`. It is not vendored and not presented as our code.

## What GitHub currently holds

- Remote `main` = this local source **minus** the spanwise extension. 95 files are identical. 13 differ: 7 `.cmd` launchers (likely line endings only) and 6 elastic files changed by the spanwise work. 17 files exist only locally (spanwise model, frontier runner, guides). Nothing exists only on the remote. Local is therefore a straight superset of `main`.
- The **atlas folder is not in the repo at all.** It exists only in this OneDrive copy.
- Remote HEAD carries **3.7 GB of `outputs/studies`** plus 108 MB of SQLite, so the repo is ~3.9 GB. Deleting them from `main` stops new clones from checking them out, but every clone still downloads the history. Shrinking the repo means rewriting history (`git filter-repo` + force-push, after which the collaborator re-clones). **This needs your decision.**
- The collaborator's original **campaign databases (rod, plate/weekend, sweep `campaign.sqlite`) were never pushed.** They are probably still on their machine. They are the missing originals the system guide mentions, and would allow exact (not nominal) settings for atlas points. Ask for them.
- GitHub Pages is not enabled. Pages on a private repo requires GitHub Pro, which is free for students through GitHub Education. Otherwise the repo must be public.

## Goal

There should be one repository that two people (and AI agents) can work in without stepping on each other. It is published as a GitHub Pages site with:

- a **landing page** with two choices: *Explore the atlas* or *Set up a new study*;
- the **atlas**, which is today's `elastic_atlas.html` with the same look, tabs, filters and viewer, loading data from per-study files;
- a **study builder** that produces a validated study spec and submits it to the repo.

Simulations still run locally. When a run finishes, its compact results go back to the repo as a pull request. Merging the PR rebuilds and redeploys the site, so anyone with the link sees the new study.

## What the survey found

| Area | Current state | Consequence |
|---|---|---|
| Version control | This folder is **not a git repo** (it was copied out of the outer Ptera repo) | Nothing is tracked. Collaboration currently means copying folders |
| Source | 44 modules + ~40 tests in one flat `wingstudy/`, from 4 generations (rigid catalog app, torque/lambda studies, elastic v1.5, spanwise) | Hard to tell what's active |
| Coupling | `elastic_runner → model → catalog ↔ adaptive → torque_study → refinement → adaptive…` (circular imports) | The elastic solver path drags in the whole legacy rigid stack. Old code can't simply be deleted |
| Servers | Two local GUIs (`app.py`, `elastic_dashboard.py`) | Duplicated UI concepts |
| Publishers | `span_atlas.publish()` rewrites the sibling `index.html` via a hardcoded path. `elastic_atlas.py` needs missing databases and writes elsewhere | Two inconsistent build paths |
| Atlas | One 12 MB `index.html` with embedded JSON (`cols` 7.8 MB, `span_comparisons` 4.6 MB, `catalog` 1.4 MB). Rebuilt by string-replacing `/*__ATLAS_DATA__*/` | Every publish rewrites one file, so two collaborators always conflict |
| Media | 1.3 GB, 243 WebP animations, some up to 36 MB. All URLs go through one helper, `MU()` | Too big for Pages (~1 GB cap), but easy to re-point to another host |
| Raw outputs | `outputs/studies` 3.5 GB, master SQLite ~104 MB, elastic results 153 MB | Can't go in git. Need an archive outside the repo |
| Solver | `PteraSoftware/` is vendored (60 MB), but the code actually runs the copy installed in site-packages (pinned commit `17a98a1…`) | The vendored copy is misleading |
| Docs | 6+ READMEs/guides with conflicting historical workflows | New collaborators and agents get misled |
| Location | Lives in OneDrive | Git repos inside OneDrive are prone to sync corruption and long-path failures |

## Target layout

```text
wing-studies/                      git repo, cloned OUTSIDE OneDrive (e.g. C:\dev\wing-studies)
  README.md                        short: what this is, links to site, how to set up
  CLAUDE.md / AGENTS.md            one agent entry point (replaces the scattered guides)
  docs/                            system guide, physics (SPANWISE_ELASTICITY), methods, history/
  pyproject.toml                   installable package + `wingstudy` CLI; Ptera pinned by git commit
  src/wingstudy/
    geometry/                      sections, curves, templates, dimensions (split out of model.py)
    solvers/rigid.py               Ptera problem construction + load metrics (from model.py)
    solvers/elastic/               elastic.py, spanwise_elastic.py, finite_span.py, runner.py
    search/                        coordinate_search, adaptive, pareto, refinement, torque_*
    studies/                       spec.py (schema validation), identity.py, queue.py, run.py, store.py
    publish/                       ONE atlas publisher
    legacy/                        old catalog app, lambda review, PDFs, Excel. Kept working, not extended
    cli.py
  tests/
  schema/
    study-spec.schema.json         contract shared by the website, the CLI and AI agents
    case-result.schema.json
  studies/
    <study-id>/
      spec.json                    what was asked (immutable once run)
      status.json                  proposed | queued | running | complete | failed (+ runner, dates)
      results.json                 compact per-case results (metrics, status, identity, media keys)
      README.md                    optional human notes
  site/
    index.html                     landing page
    atlas/index.html               elastic_atlas.html, changed to fetch data instead of embedding it
    new/index.html                 study builder
    assets/theme.css               the atlas's existing CSS variables, shared by all three pages
  tools/                           setup_windows.py, setup_linux.sh, launchers, lock files
  .github/workflows/
    validate.yml                   on PR: schema-validate specs/results, run tests
    pages.yml                      on merge to main: build site/data from studies/*, deploy Pages
```

These stay **out of git**: `outputs/` (full histories, attempt logs, SQLite, native artifacts) and the vendored `PteraSoftware/`. Large outputs go in a local archive folder. Selected ones can optionally be attached to a GitHub Release per study.

## How a study flows

```text
 website builder ─┐
 AI agent ────────┼─> studies/<id>/spec.json  (PR, validated by CI)  ── merge ──> status: queued
 CLI `wingstudy new`┘
                                    │
            local machine: `wingstudy run <id>`  (opens a draft PR first = visible "claimed" lock)
                                    │
            full outputs -> outputs/<id>/ (local);  compact results -> studies/<id>/results.json
                                    │
            `wingstudy publish <id>`  -> media upload, push branch, mark PR ready
                                    │
            CI validates -> merge -> pages.yml rebuilds atlas -> live for anyone with the link
```

Rules this enforces:

- **Results are immutable.** A rerun with changed physics, settings or code is a new study ID that references its parent, matching the provenance rules in the system guide.
- **One writer per study.** The draft PR opened when a run starts tells the other person not to run it too.
- **Nobody edits generated files.** `site/data/*` is built by CI and never committed by hand, so collaborators can't conflict on it.
- **Failures are saved as failures,** never as zero-valued points.

## Study spec (sketch)

```json
{
  "id": "2026-11-20-bare-sheet-dt-sensitivity",
  "title": "Bare-sheet unresolved cases: 50/100/200 steps per cycle",
  "author": "sam",
  "question": "Do unresolved 0.5 mm bare sheets settle with finer dt?",
  "kind": "matched-comparison",
  "wings": { "from_study": "legacy-preserved-frontier-0p01", "select": { "status": "unresolved", "sample": 12, "stratify": "material" } },
  "physical": { "thickness_mm": "preserve", "rod": "preserve", "material": "preserve" },
  "models": ["chordwise", "spanwise-finite"],
  "motion": { "frequency_hz": [1.0], "speed_mps": 0.5, "waveform": "template:7657" },
  "numerics": { "span_panels": 8, "chord_panels": 4, "cycles": 4, "steps_per_cycle": [50, 100, 200] },
  "verification": { "ladders": { "chordwise": [0.5, 0.7], "spanwise": [0.7, 1.0] } },
  "budget": { "max_cases": 72 }
}
```

`kind` maps to the existing engines: `geometry-sweep` (Sobol map), `evolution` (fixed-reference coordinate search), `matched-comparison` (today's `span_frontier`), and `replay` (media renders). `wingstudy plan <id>` is a dry run. It prints the case count, cache hits and an estimated runtime without solving anything, just as `span_frontier.py` does without `--run` today.

## Media budget

- 243 animated WebP files total 1.38 GB, with frames at 1600×1200 (designs/candidates) or 1024×768 (span). Each holds 200–400 frames, which looks like all simulated cycles.
- Test on the largest file (36.5 MB, 400 frames): keeping the **last 100 frames, downscaled to 800×600, WebP quality 60** gave 2.6 MB, about 14× smaller, with the panel mesh and wake still clearly readable. Halving the frame rate gave 1.3 MB.
- Estimate for all media: **~100 MB** at full frame rate, **~50 MB** at half. Either fits comfortably in the repo and under the Pages limit, so no external host is needed.
- Before trimming, read each animation's actual cycle count from its metadata rather than assuming 4 cycles. The originals stay in the local archive.
- The viewer keeps WebP, so no player change is needed. MP4 can be evaluated later if needed.

## Phases

Each phase ends in a working state and can be paused there.

### Phase 0: Repo bootstrap (½ day)
- Tag the current remote `main` as `pre-restructure`, so the old state stays recoverable.
- Clone `KSam37/wing-studies` outside OneDrive (e.g. `C:\dev\wing-studies`). If history is rewritten first, the clone is small.
- Commit the local spanwise extension on top of `main` as the "v1.5 import" commit and tag it `v1.5-import`.
- Move `outputs/studies`, the master SQLite/xlsx catalogs and `outputs/provenance` out of the repo into a local `legacy-archive/` (outside git), and remove them from `main`.
- Remove the vendored `PteraSoftware` submodule and pin Ptera as a dependency. Add attribution.
- Add the atlas data and recompressed media in Phase 1, not as a raw 1.3 GB dump.
- **Done when** both people can clone, set up and run `python -m wingstudy.span_frontier` (read-only count) from the tag.

### Phase 1: Atlas on GitHub Pages (2–3 days). The first visible win
- Write a one-time converter that splits the embedded atlas JSON into files. The existing campaigns become `studies/legacy-*/` (rod, plate, sweep, rigid catalog, refined/candidates, preserved spanwise frontier), each carrying provenance flags: rounded geometry, nominal fallback, "original DBs missing".
- Change the atlas template to `fetch()` its data. Pages serves it gzip-compressed, so the 12 MB becomes roughly 2–3 MB on the wire. The 55k-row catalog loads lazily, only when the Wing map opens.
- Make `MU()` read a configurable `MEDIA_BASE` and decide where media lives (see decisions).
- Add the landing page using the same theme variables.
- Add `pages.yml` so CI builds and deploys the site.
- **Regression gate:** the data object the new atlas assembles must deep-equal today's embedded `D`. The existing JS harness (`test_atlas_integration.cjs`) must also pass. After that, a real browser check of every tab.
- **Done when** the Pages URL shows the same atlas as the local file, plus the landing page.

### Phase 2: Package restructure (3–5 days)

**Status (2026-11-19): done, with one item deferred.**
- `WingStudy/` became the `wingstudy/` package at the repo root (not `src/`: modules locate `outputs/` as `Path(__file__).parent.parent`, so the root keeps every path unchanged). History follows the files (`git mv`).
- The 8 modules only the rigid app uses, and its pages and JS tests, moved to `legacy/`. They import the shared engine from `wingstudy`.
- **Later (same day):** the legacy rigid app was removed from the repository at the owner's request: `legacy/`, its 5 test files, 2 tests in `test_adaptive.py`, and the `Run Wing Studies.cmd`, `Run Master Catalog.cmd` and `Open Master Excel.cmd` launchers. It remains in git history (commit `8f327b4` and earlier). The shared engine it used stays in `wingstudy/`.
- Python tests moved to `tests/` (`python -m unittest discover -s tests`). Result: 248 tests in 28 suites pass, the same suites as before the move. The setup check also passes once the Ptera submodule is initialized.
- `python -m wingstudy <command>` is the single CLI (`pyproject.toml` also declares a `wingstudy` script). The `.cmd` launchers run `-m wingstudy.*`.
- Ptera was already a pinned submodule (`17a98a1…`), not vendored code. That item needed no change.
- **Fingerprint guard.** `wingstudy/identity.py` defines the structural fingerprint over module content, mapping package-relative imports back to the flat form. It is `c13001410d04…`, equal to all 582 saved frontier records (578 preserved + 4 bare). The Phase 0 template-case fallback had been added inside `elastic_runner.py`, which changed the fingerprint. It was moved out to `wingstudy/cases.py`, and `elastic_runner.py` is again byte-identical apart from its imports. The rigid catalog's physics digest of `model.py` is unchanged too.
- **Reproduction.** Frontier record `nominal-6213b1ab…` was re-solved with the package code. Chordwise and spanwise mean thrust, peak root torque and tip twist match the saved values exactly (relative difference 0).
- **Deferred:** extracting the geometry and load code from `model.py`. The `catalog ↔ adaptive` and `model → catalog` cycles are all function-level (lazy) imports, so they cause no import-order failures. Splitting `model.py` is better done in Phase 3, when the engines are wrapped as study kinds.
- Move the code into `src/wingstudy/` and break the import cycles (`catalog ↔ adaptive`, `model → catalog`). The fix is to pull the pure geometry/load code out of `model.py` so the elastic path no longer imports the legacy catalog stack.
- Move the old rigid app and its helpers into `legacy/` unchanged in behavior.
- Add a single `wingstudy` CLI. The `.cmd` launchers stay as thin wrappers so double-clicking still works.
- Replace the vendored PteraSoftware with a pinned dependency on commit `17a98a1…`. Keep the environment-registration logic in `launch_elastic.py`.
- **Guard:** the structural fingerprint covers `elastic.py`, `spanwise_elastic.py`, `finite_span.py` and `elastic_runner.py`, so moving those files will invalidate it. Define fingerprints over *module content* rather than file paths, and verify that the 578 saved records still match before and after the move.
- **Done when** the test count and results match the snapshot, and one verified frontier case reproduces its metrics within tolerance.

### Phase 3: Studies, runner, single publisher (4–6 days)
- Write the JSON schemas, and `wingstudy new / validate / plan / run / publish`.
- Wrap the existing engines as study `kind`s rather than rewriting them.
- Replace `span_atlas.publish()` and `elastic_atlas.py` with one publisher that writes `studies/<id>/results.json` and nothing else.
- Extend identity hashes to cover `model.py`, orchestration code and environment (known issue #7 in the system guide).
- Add a compact replay manifest per case: exact geometry, actual dt/cycles, mesh/wake, material, motion, code identity (known issue #5).
- **Done when** a small new study (≈4 cases) goes spec → run → PR → merged → visible on the site, end to end.

**Status (2026-11-19): built; waiting on the first study PR to be merged.**
- `wingstudy/studies/`: `spec.py` (stdlib validator and expansion; `schema/study-spec.schema.json` is kept in step by `tests/test_studies.py`), `run.py` (wraps `elastic_campaign._evaluate` and `span_atlas.evaluate` unchanged, caches by key in `outputs/study-cache/`), `atlas.py` (merges completed studies into the atlas at site build; `catalog.end` keeps the catalog range correct), `cli.py` (`new / validate / plan / run / publish / list`).
- Kinds: `design-set`, `geometry-sweep`, `matched-comparison`. Search, evolution and replay kinds are deferred.
- Identity: `identity.code_identity()` adds a solve-path digest (`model.py`, `elastic_campaign.py`, `span_atlas.py`, `cases.py`) and Ptera, numpy, numba, scipy and Python versions to the structural fingerprint; its digest is part of every case key (known issue #7). Each result case carries its exact solver input as `replay` (known issue #5).
- Not done: `span_atlas.publish()` and `elastic_atlas.py` still write the old atlas for existing campaigns. New results go through studies; retiring the old publishers waits until the campaigns' raw data is imported.
- First study: `2026-11-19-numerics-hardware-winner`, 4 cases (the 0.5 mm + rod 1 Hz winner at 8×4 / 16×4 panels × 50 / 100 steps per cycle). Its 8×4/50 case reproduces the atlas value to 0.006% (the atlas stores chords to 0.1 mm).
- CI runs `python -m wingstudy validate --all` and the study tests on every PR.

### Phase 4: Website study builder (3–4 days)
- Add a form under `site/new/` with the atlas styling. It validates in the browser against the same schema and can preselect wings from the atlas (for example "rerun these selected points").
- It can submit through GitHub's prefilled *new file* URL, which opens a PR with the spec and needs no backend and no stored tokens. It can also download the spec instead.
- Add a queue view that lists `proposed / queued / running / complete` studies from `status.json`.
- **Done when** a spec created on the website runs locally with no hand edits.

### Phase 5: Agents and docs (1–2 days)
- Merge the system guide, the READMEs and the `CLAUDE.md` files into `docs/` plus one agent entry point, with historical workflows moved to `docs/history/`.
- Document an agent recipe: write spec → `validate` → `plan` → open PR. Agents never run large batches unattended and never merge.
- Write contributor rules: one PR per study, results immutable, no hand edits to generated data.

## Open decisions (recommended default first)

1. ~~Repository~~: resolved, `KSam37/wing-studies`.
2. ~~Media hosting~~: resolved, recompressed in-repo (~100 MB).
3. **History rewrite.** **Rewrite history** to drop the 3.7 GB of old outputs (tag first, coordinate with the collaborator, who then re-clones). The alternative is deleting them from `main` only, which leaves a ~4 GB clone.
4. **Public or private.** **Public** fits the community-tool goal and gives free Pages. Otherwise stay private and enable Pages through GitHub Pro (Education). Either way, anything in `studies/` is visible to whoever can see the site.
5. **Submission path.** **A PR via prefilled GitHub URL**, which requires each submitter to have a GitHub account with access. The alternative is a GitHub Issue form that a bot or agent turns into a PR.
6. **Auto-merge.** **No.** A human merges each result PR after CI passes. This can be relaxed later.

## Risks

- **Silent provenance loss while moving files.** This is mitigated by the deep-equal gate in Phase 1 and the fingerprint and record-match gate in Phase 2.
- **Collaborator's environment.** `setup_linux.sh` exists but the Python 3.14 + lockfile setup has only been exercised on Windows here. Test the collaborator's setup in Phase 0.
- **Scope creep in the builder.** The site only writes specs. All solving stays in the local CLI.
- **Original campaign databases are still missing.** The restructure doesn't fix that. Legacy studies stay labeled as rounded, nominal-fallback data.
