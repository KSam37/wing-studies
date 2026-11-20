# FAAV Wing Studies

Simulation studies of flapping carbon-fibre wings in water, and an interactive atlas of every wing simulated so far.

**Website:** the landing page, atlas and study builder are published from this repository with GitHub Pages.

Each study predicts the mean thrust and the peak fluid root torque of one isolated wing. It uses one of three analysis types:

| Analysis type | What is modelled |
|---|---|
| Rigid | The outline flaps as a rigid plate |
| Chordwise elasticity | The sheet twists passively about the leading edge |
| Spanwise + chordwise elasticity | The sheet also bends along the span, with large deflections |

Wings are carbon-fibre sheets of several thicknesses, either bare or with a carbon leading-edge rod. Results are numerical predictions. "Verified" means two stabilization settings agree; it is not experimental validation.

## Repository layout

| Path | Contents |
|---|---|
| `site/` | Landing page and study builder (`site/new/`) source |
| `wingstudy/elastic_atlas.html` | Atlas page template (data is inserted at build time) |
| `atlas/data/` | Atlas data: one file per study plus metadata, catalog and span comparisons |
| `atlas/media/`, `atlas/files/` | Animations (recompressed to one flap cycle), plots and reports |
| `wingstudy/` | The study engine (Python package): geometry, rigid and elastic solvers, campaigns, searches, the atlas exporter. Run tools with `python -m wingstudy <command>` |
| `studies/` | Planned studies: spec, status and compact results, one folder each |
| `schema/` | JSON Schema for study specs |
| `tools/` | Setup, launchers, site build, media compression, data import |
| `tests/` | Python tests for the package, plus the atlas UI test |
| `docs/history/` | Earlier READMEs and results notes, kept for provenance |

Large raw outputs (full time histories, SQLite catalogs, older rigid studies) stay on the machine that produced them and are never committed. See [RESTRUCTURE_PLAN.md](RESTRUCTURE_PLAN.md) for where the project is heading.

## Viewing the atlas locally

```powershell
python tools/build_site.py
```

Then open `_site/index.html` (landing page) or `_site/atlas/index.html` directly in a browser. No server is needed.

## Running a new study

Simulations run on your own computer. A study is a folder `studies/<id>/` holding `spec.json` (what to solve), `status.json` and, once run, `results.json` (compact results plus an exact replay input for every case). [`schema/study-spec.schema.json`](schema/study-spec.schema.json) documents the spec.

**Set up (Windows).** Clone the repository (`git clone --recurse-submodules https://github.com/KSam37/wing-studies.git`). Then double-click `Setup Windows.cmd`, which installs the Python dependencies and the pinned Ptera solver into `%LOCALAPPDATA%\WingStudies`. That environment is tied to the folder you set up from: after moving the folder, run `Setup Windows.cmd` again. Linux: `tools/setup_linux.sh`.

**Write the spec on the website.** The [study builder](https://samkir.com/wing-studies/new/) checks a spec with the same rules as the tools (`site/new/spec.js` is a port of `wingstudy/studies/spec.py`; `tests/builder.test.cjs` keeps them identical). Pick wings in the atlas with *Add to a new study*, or type outlines in. *Submit on GitHub* opens a prefilled `studies/<id>/spec.json` that becomes a pull request; *Download spec.json* saves it instead, and `tools\wingstudy.cmd import spec.json` puts it in place. The builder's *Queue* tab lists every study and its state.

**Plan, run, publish.** Use `tools\wingstudy.cmd` (the registered environment) or `python -m wingstudy`:

```powershell
tools\wingstudy.cmd new my-question --kind evolutionary # writes studies/<today>-my-question/spec.json
tools\wingstudy.cmd validate 2026-11-19-my-question     # every problem, in plain words
tools\wingstudy.cmd plan 2026-11-19-my-question --workers 4
tools\wingstudy.cmd run 2026-11-19-my-question --workers 4
tools\wingstudy.cmd publish 2026-11-19-my-question      # study/<id> branch, push, pull request
```

- Kinds:
  - `evolutionary`: the campaigns' coordinate climb. Every model × frequency × objective is one search; each search runs one lineage per seed (seed half-spans × seed families, plus any seed wings). Objectives are a torque budget (max thrust with peak torque ≤ B) or a λ trade-off (T/T<sub>ref</sub> − λ·M/M<sub>ref</sub>). The search block also sets the solves per lineage, the chord step, the smallest chord and whether chords must decrease. `results.json` records every lineage's accepted steps, and the atlas animates each search winner's shape evolution from them.
  - `geometry-sweep`: scrambled-Sobol outlines with the campaign rules, no climbing.
  - `design-set`: re-solve named outlines and/or atlas designs (by key) for every model, frequency and numerical setting.
- `structure` is `chordwise`, `spanwise` or `matched` (every wing solved chordwise-only and with spanwise bending). A matched evolutionary search climbs chordwise and re-solves each search winner as a matched pair.
- Every solved case is cached in `outputs/study-cache/` under a key covering the outline, model, motion, numerics and code identity (structural and solve-path source, Ptera and library versions). Reruns and later studies reuse identical solves, and changing the code re-solves.
- Results are immutable: once a study has run, edit nothing in its spec; start a new study and name the old one as its `parent`.
- `publish` commits only `studies/<id>/` and opens a pull request. CI validates the spec and results and builds the site with the study merged into the atlas. A person merges it; nothing is merged automatically. After the merge the study appears in the atlas as its own study, its designs marked "found by a planned study".

**Campaign tools.** `Run Span Flex Study.cmd` opens the campaign dashboard and `Run Frontier Span Study.cmd` resumes the matched frontier rerun. `tools\wingstudy.cmd --help` lists every command; [V1_5_SYSTEM_GUIDE.md](V1_5_SYSTEM_GUIDE.md) explains each workflow.

**Evolution animations.** For top performers that a search found, `tools\wingstudy.cmd evolution <campaign folder> --atlas-winners rod` (or `weekend`) renders the shape's evolution from its seed into `atlas/media/evolution/`; the atlas shows it as the "Shape evolution" view, with the search's λ. This needs the campaign's `campaign.sqlite`.

The launchers keep the solver's compiled-function cache in `%LOCALAPPDATA%\WingStudies\numba`. If you run Python directly, set `NUMBA_CACHE_DIR` to a short path: long Windows paths (OneDrive folders, for example) can make the cache fail.

## Tests

```powershell
python -m unittest discover -s tests
```

Run this with the registered Ptera environment's Python. `tools\Check Installation.cmd` does the same after verifying the installation.

## Credits

Aerodynamic loads come from [Ptera Software](https://github.com/camUrban/PteraSoftware) by Cameron Urban and contributors. Ptera is an unsteady vortex-lattice method solver released under the MIT licence. This project pins upstream commit `17a98a10f724a743f1b5f1597579b24edf95cf2d` (see `tools/ptera-source.json`). The water operating point, the chordwise and spanwise structural models, and the study tooling are this project's extensions; they are not part of Ptera.

Developed for MIT 2.S986 Robotics in Fluids.
