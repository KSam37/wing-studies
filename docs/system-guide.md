# Wing Studies system guide

**Refreshed 20 November 2026** from the 19 November handoff (kept verbatim in [history/system-guide_2026-11-19.md](history/system-guide_2026-11-19.md)). Audience: anyone, human or agent, who will change the models, run studies or interpret results. Current user instructions override it. Facts that change (counts, run states) are dated; refresh them before quoting.

## 1. Executive briefing

We are designing manufacturable flapping wings for an underwater robot in MIT 2.S986 Robotics in Fluids. The application uses Ptera's unsteady vortex-lattice method (UVLM), prescribed motion and structural models to explore shape, thrust, root loading and compliance. The ultimate goal is to select physical wings and challenge simulation predictions with water-tank measurements—not declare a numerical winner physically optimal.

The work began as a geometry-sweep companion to Ptera. It expanded into independent shape evolution, broad geometric sampling, persistent catalogs, fabrication exports and an offline atlas. A collaborator's v1.5 added efficient stabilized torsional aeroelasticity. The current extension adds spanwise bending and revises rod/sheet boundary treatment. Sam is especially interested in a 0.5 mm carbon sheet without a rod and appreciable deflection, but the latest comparison preserves every selected wing's original material and rod configuration.

The simulation engine and the atlas are parts of ONE analysis workflow. The atlas is published from this repository as a website (samkir.com/wing-studies) together with a study builder; it must stay visually integrated and lighter than the full outputs. Sam explicitly rejected separate, mismatched mini-apps.

### State of the preserved-frontier batch (19 November 2026)

- Preserved-material frontier batch: **578/578 elastic wings processed**; no active frontier run recorded.
- **131 rigid frontier references** retained in the plan; no invented finite stiffness assigned.
- Spanwise: **155 verified, 66 unverified, 8 uncertain, 349 unresolved**.
- Baseline chordwise: **330 verified, 49 unverified, 3 uncertain, 196 unresolved**.
- **149 wings verified in both models** support matched comparisons.
- Twelve native animation replays are complete: both models for six highlighted designs across three frequencies. All referenced media files were checked.
- Wing map has an independent Spanwise elasticity Off/On filter.
- The *Elasticity effects* tab (part 2) defaults to maximum-thrust designs under each model at each frequency, restricted to verified pairs: six distinct designs. This is NOT the full frontier or the best design at every torque.
- A selector exposes all verified pairs. Hover shows the outline and details; clicking opens the paired viewer. Newly rendered animations cover the six highlights, not all 149 pairs.
- Original campaign databases are missing from the imported package. Sam explicitly approved nominal settings for missing details. Do not ask again merely to use this fallback.

## 2. Paths, repository and environment

This folder is the `KSam37/wing-studies` Git repository (public). The owner's working copy lives outside OneDrive: `Documents\Coursework\2.S986-Robotics in Fluids\wing-studies`. Older copies under OneDrive (`...\wing-studies-1.5\` and the outer `...\Ptera\` app) are not this repository; confirm the working directory before running anything.

| Lives in Git | Stays local (never pushed) |
|---|---|
| `wingstudy/` engine, `tools/`, `tests/`, `schema/`, `site/` | `outputs/`: campaign folders, full records, histories, the study cache |
| `atlas/data/` and `atlas/media/`: published atlas data and recompressed media | Legacy master SQLite catalogs and Excel views |
| `studies/<id>/`: spec, status, compact results of planned studies | The Python environment and numba cache (`%LOCALAPPDATA%\WingStudies`) |
| `PteraSoftware` submodule pinned to `17a98a10` | `_site/` (built by `tools/build_site.py`; CI builds the deployed copy) |

The `.gitignore` is an allowlist: a new top-level file or folder is ignored until it is listed there.

### Runtime

```text
Python 3.14.2 (registered environment)
C:\Users\SamKi\AppData\Local\WingStudies\environments\2e1977f87f88a0c1\Scripts\python.exe
```

The live `pterasoftware` import resolves to that environment's `site-packages`, not to the `PteraSoftware` submodule; editing the submodule does not change the installed solver. `tools/ptera-source.json` records the upstream commit and hashes; dependencies are in `tools/requirements-windows.lock`. `Setup Windows.cmd` (or `tools/setup_linux.sh`) creates and registers the environment; `tools/launch_elastic.py` and `tools\wingstudy.cmd` find it again. Moving the checkout requires running setup again.

CI (`.github/workflows/pages.yml`) uses plain Python 3.12 with no solver: it validates studies, runs the standard-library study tests, checks the builder against the Python validator, builds the site and checks every referenced media file.

## 3. Engineering aims and preferences

1. Sample broad, buildable design regions quickly, then refine promising shapes.
2. Retain provenance, failed attempts and reusable solver identities.
3. Compare like-for-like physical, motion, fluid and numerical conditions.
4. Build a thrust–torque tradeoff curve for hardware selection instead of assuming one universal winner.
5. Manufacture selected outlines and compare tank measurements with predictions.
6. Work toward a calibrated engineering tool. Independent AI agreement is review evidence, not physical validation.

Sam favors first-principles models, explicit assumptions, practical GUI controls, concise scientific plots and organized outputs. He dislikes unnecessary scaffolding, duplicated programs, arbitrary hidden limits, and repeated approval questions for authorized work. Human engineering judgment determines what is credible.

Early concepts used carbon rods and Dyneema fabric. Later fabrication shifted to flat carbon-fiber sheet with optional leading-edge rod. Do not carry early fabric mass or rod sizes into current cases automatically. Dyneema is a material family, not a fixed areal density.

## 4. How we arrived here

### Rigid geometry studies

The original app exposed span, chord widths, incidence, sweep, flap frequency/amplitude, time step, cycles and panel resolution. Water properties replaced air settings. Physical symmetry was intended, but paired simulations cancelled roll moments. The workflow therefore moved to **one isolated wing**, with moments referenced to its root. Pair thrust may be estimated as 2T without interaction.

Custom geometry, saved-design refinement, span sweeps, smooth cutting profiles, STL/STEP and split print templates followed. Fabrication makes simulation claims testable. Case 7657 is an important earlier design; its requested fabrication thickness varied over time and is not a universal material setting. Three selected waterjet wings and a roughly 1 N m rectangular comparison exist in older project history. Inspect their folders before quoting final dimensions or identifiers.

### Optimization lessons

- Thrust alone favors large area and loading.
- T/M can reward removing outer material because moment falls faster than thrust. It is not energy efficiency.
- Requiring every move to improve thrust while never increasing torque can stall by rejecting useful tradeoffs.
- A frontier describes competing objectives, but thousands of near-identical points obscure the picture.
- Independent seeds and broad geometric sampling reduce dependence on one triangle.
- A finite budget or flat evolution trace does not prove global convergence.

Torque bands used to summarize results are not automatically torque ceilings for simulations. The user repeatedly corrected this distinction.

### Independent weighted coordinate evolution

Seed families: triangle, rectangle, concave, convex, and a **thin rectangle** for long/narrow. Each shape/span seed retains independent ancestry even when duplicate simulations are reused.

The adopted fixed-reference score is:

```text
S = T / Tref - lambda * M / Mref
Delta S = (T_new - T_parent) / Tref
          - lambda * (M_new - M_parent) / Mref
```

T is mean single-wing thrust; M is peak absolute fluid root roll moment. References are fixed from the study's starting seeds, not reset to each new parent. Historical lambda studies used 0.75, 1.25 and 1.75. Smaller lambda favors normalized thrust relative to torque; it is not a physical percentage of efficiency.

Sam prefers the Delta S equation when explaining acceptance. Do not incorrectly call `T_new/T_parent - lambda*M_new/M_parent` the current fixed-reference objective.

The algorithm initially tests +/- changes to each chord WIDTH in root-to-tip order, accepts the best positive score change, remembers direction, then moves to the next chord. Subsequent passes test that direction. On failure/blocking, it tries one half-step and retires the coordinate; unsuccessful initial directions receive the documented half-step check. Newly exposed tips can be revisited. Initial step was 0.02 m; settings are editable. This is finite-difference, direction-informed coordinate search, not an analytic gradient method or convergence proof.

Root width may shrink under its maximum in generic exploration. The collaborator's original elastic campaigns intentionally fixed the root at 200 mm; preserve those source conditions rather than retroactively applying generic preferences.

### Collaborator's original elastic v1.5

Campaigns combined independent weighted evolution, a 1 N m constrained objective, and scrambled-Sobol shape maps. Those constrained searches remain legitimate historical source data even though the current spanwise rerun has no torque ceiling.

The atlas combines these campaigns with earlier rigid studies and refined/fabrication candidates. Base campaign points are not all high-resolution or experimentally validated.

### Current spanwise extension

Sam requested spanwise flexion for bare sheet and separate sheet flex behind a rotation-constrained rod. A linear beam and finite-rotation span model were implemented beside native Ptera. The aerodynamic solver is reused; spanwise structural code is a project extension, not an upstream native capability.

The latest study is **re-evaluation, not shape optimization**: select existing frontier wings, retain their physical configuration, and compare structural models.

## 5. Definitions and geometry contracts

| Quantity | Meaning |
|---|---|
| T | Final-cycle mean propulsive force of one isolated wing, N; sign handled by model helpers |
| M | Sampled final-cycle peak absolute fluid roll moment about that wing's root, N m |
| T/M | Thrust-to-root-moment ratio, 1/m; not energetic efficiency |
| Span | Distinguish nominal paired span, hinge gap, active material span and instantaneous projected span |
| Chord | Leading-to-trailing-edge width, not node spacing |
| Verified | Numerical settling and stabilization agreement, not mesh/experimental validation |
| Frontier | Observed nondominated thrust–torque points in the evaluated sample |
| Torque band | Display/selection bin; current rerun uses 0.01 N m |

Root fluid torque is not motor-shaft torque. Crank/gearbox conversion was removed from the current objective; Sam will handle it. Structural inertia affects deformation but is not added to the displayed fluid moment as total actuator torque.

Zero chords are allowed only as an outboard suffix. Zero means an omitted section, not epsilon width or a zero-area Ptera panel. At least two positive sections remain. The active wing ends at the last positive station; do not stretch it back to the original tip. Effective span can shorten discretely.

The extension supports straight leading edges and initially planar isolated wings. Unsupported swept/gull/multiple-wing geometry should be rejected, not silently treated as fully supported.

## 6. Physics hierarchy

### Rigid UVLM

Ptera solves prescribed-motion loads with selected free/prescribed wake treatment. Water properties enter the operating point. UVLM is not viscous CFD or a separated-flow model; entering viscosity does not supply complete viscous drag. Zero-forward-speed adapters were rejected earlier. Current campaigns use positive inflow, typically 0.5 m/s.

### Original v1.5: `wingstudy/elastic.py`

The UI calls this chordwise elasticity. Its coordinate is passive sheet/strip pitch about the leading-edge/span axis. Chord sections remain straight; full chordwise camber is not resolved.

- Subclasses native Ptera's aeroelastic problem without editing installed source.
- Generalized-alpha integration, added-inertia partitioning and projected moments.
- Plate torsional rigidity approximately G*c*t^3/3, plus warping regularization.
- Coupling transmits outboard loads to inboard twist.
- Original rod treatment adds rod torsional stiffness to sheet pitch, often making it nearly rigid.

### New spanwise model

`spanwise_elastic.py` supplies the native geometry/load bridge and linear structure. `finite_span.py` supplies finite rotations. Root bending/passive pitch are clamped relative to imposed flap; tip is free.

Linear mode uses Hermite Euler–Bernoulli bending with displacement w, slope beta and pitch theta. Finite mode uses length-preserving segments with station slopes and pitch:

```text
EI_span = E_sheet*c*t^3/12 + E_rod*pi*(do^4 - di^4)/64
alpha_i = (beta_i + beta_(i+1))/2
Delta y_i = h_i*cos(alpha_i)
Delta z_i = h_i*sin(alpha_i)
U_bend = sum EI_i*(beta_(i+1)-beta_i)^2/(2*h_i)
```

Loads are transported/distributed by virtual work, not by applying one root moment to every section. Finite mode includes configuration-dependent inertia, analytic position Jacobians, imposed flap forcing and pose-dependent added inertia. It remains partitioned and time-discretized.

With a rotation-constrained rod, its bending stiffness/mass remain, but rod GJ no longer locks sheet pitch. The equivalent sheet spring behind it uses `k = 3*E_sheet*I_chord/c`, `I_chord = dy*t^3/12`. This matches a tip-loaded cantilever displacement, not full camber or clamped slope distribution.

**Confound:** rod comparisons change BOTH span bending and rod/sheet pitch boundary treatment. Do not attribute every rod-case difference solely to span bending.

This is not a full laminate shell or general 3-D elastic rod. It omits span stretching, in-plane bending, self-contact, resolved camber and full anisotropic coupling. Large fluid angles also challenge UVLM.

### Assumptions and guards

| Parameter | Current value / interpretation |
|---|---|
| Sheet E / G | 50 / 4.5 GPa, assumed plain-weave carbon |
| Sheet density | 1550 kg/m^3 |
| Campaign rod | Carbon tube, 5 mm OD / 3 mm ID, not older 2/4 mm solid-rod concepts |
| Rod longitudinal E | 120 GPa, editable assumption introduced for bending |
| Rod G / density | 4.5 GPa / 1550 kg/m^3 |
| Structural damping ratio | 0.02 default, not a knob to conceal instability |
| Generalized-alpha rho_inf | 0.6 |
| Finite guards | 75° span slope, 80° pitch, tip displacement below 95% material span |
| Linear guards | 20° span slope, 25% span deflection |

Guards are numerical/geometric safeguards, not validated physical accuracy limits. Never clip motion to make a case pass. See [spanwise-elasticity.md](spanwise-elasticity.md) for equations, checks and sources.

## 7. Original settings and authorized fallback

Original base defaults: 8 spanwise × 4 chordwise panels, four cycles, 50 steps/cycle, 0.75/1/1.25 Hz, approximately -26 to +34 degree custom stroke, 0.5 m/s, template case 7657.

The original campaign could extend cycles and refine dt by factors 2 or 4. Finalists used 16 span panels and further timestep checks. Defaults therefore do NOT establish actual settings for every original point.

The atlas stores rounded geometry and metrics, not actual dt/cycles for every campaign point. No original weekend, rod or sweep campaign.sqlite databases were found in the imported package. Some candidate/refined sections contain numerical settings, but not all 578 selected cases.

Sam explicitly authorized **nominal settings for missing details**. The completed batch preserves source physical configuration and atlas outline, using nominal settings where originals are absent. It runs matched baseline/spanwise models at identical settings and labels these as new reruns.

Atlas geometry is rounded to 0.1 mm. Do not call it full-precision source geometry. If original databases arrive, restore exact settings as a separately identified rerun rather than overwriting history.

The bounded comparison checks factors (0.5, 0.7) for baseline and (0.7, 1.0) for spanwise—not the original campaign's entire fallback ladder. No automatic dt, cycle or mesh refinement occurs in the frontier rerun.

## 8. Latest selection and outcomes

`span_frontier.py`, scope `preserved`:

1. Read original campaign rows from the atlas; exclude older rigid catalog rows with different conditions.
2. Keep verified elastic / settled rigid source points.
3. For each frequency, form one nondominated frontier across all material/rod models.
4. Select maximum thrust per occupied 0.01 N m band; exact thrust ties favor lower torque.
5. Preserve selected thickness/material/rod; rigid points remain references.
6. Solve matched structural models, retain attempts, publish compact summaries.

No torque ceiling. This is selected under OLD models, not a spanwise-optimized frontier; it may miss shapes that improve under new physics.

Earlier `bare` and `all` plans were superseded because they would remodel all shapes as 0.5 mm without rod. Only four bare-plan pilot cases ran. Do not launch those plans as the current request.

Authoritative current folder: `outputs/elastic/frontiers/preserved-0p01/`.

| Material | Total | Span verified | Unverified | Uncertain | Unresolved |
|---|---:|---:|---:|---:|---:|
| 1.0 mm bare | 92 | 25 | 2 | 7 | 58 |
| 0.5 mm bare | 152 | 1 | 0 | 0 | 151 |
| 0.25 mm bare | 69 | 3 | 0 | 0 | 66 |
| 0.2 mm bare | 20 | 1 | 0 | 0 | 19 |
| 0.5 mm + rod | 69 | 69 | 0 | 0 | 0 |
| 0.25 mm + rod | 176 | 56 | 64 | 1 | 55 |
| Total | 578 | 155 | 66 | 8 | 349 |

Statuses:
- verified: two settled stabilization runs agree within tolerance; spanwise comparisons include pitch/deflection as well as loads.
- unverified: only one tested setting settled.
- uncertain: multiple settled settings disagree beyond tolerance.
- unresolved: no tested setting produced a settled solution.
- failed: exception-level failure; retain error, not fabricated metrics.

Final messages for 349 unresolved cases: 271 sheet-pitch guards, 57 span-bend/deflection guards, 19 native geometry/angle errors, and 2 no-settled-solution cases without those final errors. These classify final records, not every attempt. **196 also failed the matched baseline rerun.**

This suggests numerical/structural-model difficulty at nominal settings, especially bare sheets. It does not prove the physical wings cannot flap. Investigate added-mass coupling, timestep resolution, deformation validity and frame handling.

### Prior numerical evidence

Wing 7657, 0.5 mm bare, 1 Hz: finite mode at 16 span panels and dt=0.0025 s gave approximately 0.6105–0.6107 N thrust, 0.36875–0.36884 N m peak fluid torque, 127.3 mm tip-travel amplitude and 43.85° maximum span slope at factors 0.7 and 1.0. Next-coarser dt gave about 1.5% lower thrust; 8-to-16 panels at dt=0.005 s changed thrust about 2%. This supports numerical repeatability for this case, not every planform.

In the initial four-winner pilot, one failed 50-step case verified at 100 steps/cycle; another remained unresolved; another became only unverified. Finer time resolution is a diagnostic, not a universal cure.

## 9. Atlas and website

Sources: `wingstudy/elastic_atlas.html` is the atlas template; `atlas/data/` holds its data as small JSON files (`meta.json`, `rows/<study>.json`, `catalog.json`, `span_comparisons.json`; see `tools/atlas_data.py`); `atlas/media/` and `atlas/files/` hold recompressed animations, plots and reports. `site/` holds the landing page and the study builder (`site/new/`). `python tools/build_site.py` assembles everything into `_site/`, merging every completed planned study into the atlas as its own study; open `_site/atlas/index.html` directly, no server needed.

Reuse the template's CSS variables, themes, navigation, chips, chart helpers, tooltips and modal. Do not create another results app. Tabs: *Wing map*, *Top performing wings*, *Optimized shapes*, *Elasticity effects* (1 · rigid → chordwise; 2 · chordwise → spanwise + chordwise). Old `#stiff` and `#span` links redirect to *Elasticity effects*.

Matched comparisons are `D.span_comparisons`. Solved rows are registered into the Wing map arrays at load; `EXTRA` identifies them and `ORIGINAL_N` preserves the old catalog boundary. Never treat every appended row as historical catalog data. Rows from planned studies carry `src` bit 4; evolutionary studies add `D.row_search` (objectives, λ or torque budget, winner marks and the lineage's accepted steps), which drives the *Shape evolution* player without a campaign database.

Every wing carries a **leading-edge boundary condition** tag, derived from its analysis type and construction, with its own filter and colour option. In every model the root is fixed to the flapping hub.

| Tag | Model | What holds the sheet at the leading edge |
|---|---|---|
| Rigid outline | rigid | nothing deforms |
| Pivots freely about a straight leading edge | chordwise, no rod | LE straight and in place; strips pitch against the sheet's own torsion and warping. Also the model of a sheet hinged freely on a rigid rod (the rod's mass sits on the pitch axis and adds no pitching load) |
| Bonded to the rod: twists with it | chordwise, rod | sheet and rod twist together; rod GJ (≈0.24 N·m²) adds to the sheet's and dominates |
| Free sheet: bends along the span and pitches | spanwise, no rod | LE bends with the sheet |
| Clamped to a non-rotating rod: flexes behind it; rod bends | spanwise, rod | rod bends but does not rotate; sheet pitches by bending behind it, k = 3EI/c |

No current model has a sheet hinged freely on a rod that also bends along the span.

**Strouhal number.** Every wing carries a kinematic Strouhal number, computed in the page as St = f·A/U:
- A is the tip's peak-to-peak vertical excursion under the prescribed flap about the root, which sits on the flapping axis. For the custom −26° to +34° stroke used by every elastic study and most of the rigid catalog, A = R·(sin 34° + sin 26°) ≈ 0.998 R. One rigid-catalog conditions group uses a ±30° sine, where A = R.
- R is the effective half-span and U = 0.5 m/s.
- Elastic deflection is not included. This is exact for the chordwise models, whose leading edge stays straight.

St is a Wing map axis, a range filter, an inspector row and a CSV column. *Top performing wings* plots the best thrust at ≤ 1 N·m against St, one line per frequency.

**Top performing wings** is computed in the page from the rows, so new studies appear without a rebuild of `atlas/data`. It has, in order:
- A leaderboard: the best wing per material × analysis type at a chosen frequency (default 1 Hz).
- The Strouhal plot.
- One card per planned study, newest first: the best wing at each half-span the study ran, plus a thrust-against-span chart.
- The campaign winners (`D.winners`) and the rigid catalog.

**Timeline.** A slider above the Wing map shows only the wings run up to a chosen point; *Play* steps through the studies in order while the axes stay fixed. Each wing's run time comes from:
- **Rigid-catalog rows:** their source study's timestamp (the `YYYYMMDD-HHMMSS` prefix of its id in `catalog.json`).
- **Planned studies:** `results.json` `completed`.
- **Matched spanwise reruns:** `SPAN_COMPARISON_DATE`.
- **Rod, plate, sweep and span-free campaigns:** `RUN_DATES` in `tools/atlas_data.py`. Their databases are missing, so these dates are approximate ("on or before 15 Nov 2026") and the timeline says so. Correct them there if a better record turns up.

Wing map: independent Spanwise elasticity chips (Off = rigid/chordwise, On = span+chord); other study/material/frequency/quality filters still apply; inspecting a result enables its elasticity category.

Elasticity effects, part 2: default is the union of maximum-thrust designs under each model at each frequency, among verified pairs (six highlights, no torque ceiling); the alternative shows all 149 verified pairs. Blue/orange identify the model; dashed links join the SAME wing, not an interpolated optimum. Clicking a highlight opens paired native animations with side/front/top controls. Only the six highlights have new replays.

Animations use native camera/scalar framing; they are not phase-locked. Do not compare force by colour or apparent size; use the metrics.

## 10. Code and data map

| File / folder | Responsibility |
|---|---|
| wingstudy/elastic.py | Original stabilized plate/torsion model and config dataclasses |
| wingstudy/spanwise_elastic.py | Linear structure, geometry bridge, load transfer, histories |
| wingstudy/finite_span.py | Finite rotations, centerline, Jacobians, mass/forces |
| wingstudy/elastic_runner.py | Solver construction, metrics, verification, native output |
| wingstudy/elastic_campaign.py | Search/map plans, coordination, SQLite, replay |
| wingstudy/elastic_dashboard.py/html | Local campaign GUI and atlas export |
| wingstudy/elastic_atlas.py | Original full builder requiring campaign databases |
| wingstudy/elastic_atlas.html | Integrated atlas template |
| wingstudy/span_atlas.py | Matched reruns, compact merge/publish, campaign import |
| wingstudy/span_frontier.py | Frontier plan, nominal fallback, parallel runner/progress |
| wingstudy/span_winner_media.py | Highlight replay, media and metric verification |
| wingstudy/model.py | Existing geometry, motion and load helpers |
| wingstudy/coordinate_search.py | Fixed-reference independent coordinate search |
| wingstudy/catalog.py, case_identity.py | Older durable catalog/reuse identities |
| wingstudy/studies/ | Planned studies: spec validation (`spec.py`), runner and cache (`run.py`), evolutionary searches (`evolve.py`), atlas merge (`atlas.py`), CLI (`cli.py`) |
| wingstudy/adaptive.py | Seed families and validity rules shared by campaigns and planned searches |
| tools/launch_elastic.py | Environment discovery and launcher routing |
| tools/build_site.py, check_site.py | Site build and media-reference check |
| tools/atlas_data.py | Split / reassemble atlas data |
| site/new/spec.js | Browser port of `spec.py`, kept identical by `tests/builder.test.cjs` |
| outputs/elastic/frontiers/preserved-0p01/plan.json | Selection/config/provenance snapshot |
| .../results/*.json | Full matched records, attempts, histories, media links |
| .../progress.json, run.log | Last progress and coordinator output |
| outputs/elastic/span_atlas/ | Four-winner pilot, retained screening failures |
| outputs/elastic/span_validation/ | Structural/coupling checks and native artifacts |
| outputs/study-cache/<key>.json | Planned-study solve cache, keyed by outline, model, motion, numerics and code identity |
| atlas/media/span/<key>/<model>/ | Native views, plots, poster, replay check |

Older master SQLite catalogs and Excel views are separate from elastic campaigns and atlas snapshots. Excel is a generated view, not solver ground truth. The 578 JSON records were published to the atlas, not automatically inserted into the old master workbook.

### Data flow

```text
Original campaigns (databases missing in this imported copy)
  -> supplied atlas: rounded geometry + metrics + selected media
  -> span_frontier.py: selected source frontier, 0.01 N m bands
  -> plan.json: source identity + physical config + explicit nominal fallback
  -> parallel workers: matched chordwise and spanwise runs
  -> results/<key>.json: full attempts, metrics, histories, provenance
  -> span_atlas.py: compact merge (now split into atlas/data/)
  -> tools/build_site.py: atlas page on the website
  -> span_winner_media.py: checked native replays for six highlights
```

Planned studies take a separate path:

```text
spec.json (website builder or `new`) -> validate -> plan -> run (study cache, process pool)
  -> results.json (compact results + exact replay input per case) -> publish (PR) -> CI -> human merge
  -> build_site.py merges the study into the atlas
```

## 11. Running, resuming and publishing

Commands assume the repository root and the registered Python (`tools\wingstudy.cmd` routes there). **New questions should be planned studies** ([studies.md](studies.md)); the commands below are the campaign and frontier workflows that produced the current atlas data.

Windows entry points:
- Run Span Flex Study.cmd: finite-span 0.5 mm bare-sheet campaign GUI, not automatically the preserved-frontier batch.
- Run Frontier Span Study.cmd: resume preserved plan with four workers; matching completed cases are skipped.

Read-only remaining-count check:

```powershell
python -m wingstudy.span_frontier
```

Resume current batch (already complete at this snapshot):

```powershell
python -m wingstudy.span_frontier --scope preserved --run --workers 4
```

Apply authorized nominal fallback only where missing:

```powershell
python -m wingstudy.span_frontier --scope preserved --allow-nominal
```

No solving without --run. --limit 4 bounds a trial. A STOP file in the selected frontier folder prevents new scheduling; active cases finish/save. Remove STOP before resuming.

Publish saved records without solving:

```powershell
python -m wingstudy.span_frontier --scope preserved --publish-only
```

This publisher predates the split atlas data; after using it, re-split with `tools/atlas_data.py` and review the diff. The original elastic_atlas.py builder needs the missing databases and writes elsewhere (outputs/elastic/atlas). Do not run it blindly.

Campaign GUI:

```powershell
python -m wingstudy.elastic_campaign dashboard --large-deflection --variant plate --workers 4
```

Changed physics requires a fresh campaign identity. GUI action Save span-flex results to atlas exports summaries. Imports without matched baselines must say so.

Native highlight replays:

```powershell
python -m wingstudy.span_winner_media
```

This re-solves saved cases with stored config/stabilization, renders native PNG and three WebP views, and rejects a replay if thrust/torque differs beyond tight tolerance. Existing replay markers are reused. It is not an arbitrary on-demand renderer for all atlas points.

If original campaign databases arrive:

```powershell
python -m wingstudy.span_frontier --scope preserved --source-root "PATH_TO_CAMPAIGNS"
```

Inspect the imported plan before adding --run. Import is intended to restore exact chords/span, actual dt/cycles, source-plan mesh, material and rod. Validate identity and create a distinct study/version when replacing nominal inputs; do not overwrite completed outcomes casually.

### Windows numerical environment

Launchers set single-thread numerical libraries to avoid worker/thread oversubscription and keep the numba cache at a short path. For direct runs:

```powershell
$env:NUMBA_CACHE_DIR="$env:LOCALAPPDATA\WingStudies\numba"
$env:OMP_NUM_THREADS='1'
$env:OPENBLAS_NUM_THREADS='1'
$env:NUMBA_NUM_THREADS='1'
```

Use Python -X utf8 or explicit UTF-8 file encoding. A Windows guard protects signal.SIGUSR1 use; do not reintroduce unconditional Unix-only signal calls.

## 12. Data integrity and sharing

- One coordinator owns writes; workers solve cases.
- Results write through temporary files and atomic replacement.
- ETA extrapolates completed work; quick failures bias early estimates downward.
- Atlas updates every ten completed cases and at batch end.
- Nominal keys hash geometry, span, frequency, thickness, rod, material, template and numerics—not source nickname alone.
- Structural fingerprints cover elastic.py, spanwise_elastic.py, finite_span.py and elastic_runner.py.
- Existing plans reject changed structural code on resume. Do not replace the stored hash to bypass this.
- Missing/incompatible pilot provenance is not an exact cache match.
- Publisher merges comparisons by source key. Changed physics/settings need distinct identities.
- Older master app searches both Old/New generations for exact reuse; preserve this policy.
- Planned-study results are immutable: `validate` rejects a `results.json` whose `spec_sha256` no longer matches, and CI rejects pull requests that edit a run study (see [CONTRIBUTING.md](../CONTRIBUTING.md)).
- The study cache key includes structural and solve-path source, Ptera and library versions; changing code re-solves instead of reusing.
- A synced or Git-ignored folder is not proof of a tested backup.

## 13. Verification and confidence

Relevant tests:
- test_spanwise_elastic.py: analytical cantilever loads/dynamics, energy, geometry, rod/sheet separation and identity.
- test_finite_span.py: length preservation, Jacobians/virtual work, nonlinear elastica comparison, inertia and small-load limit.
- test_elastic.py: legacy torsion regressions.
- test_span_frontier.py: dominance/ties, bands, no hidden ceiling, nominal material/rod preservation.

```powershell
python -m unittest discover -s tests -p test_spanwise_elastic.py -v
python -m unittest discover -s tests -p test_finite_span.py -v
python -m unittest discover -s tests -p test_elastic.py -v
python -m unittest discover -s tests -p test_span_frontier.py -v
python -m unittest discover -s tests            # everything (registered Python)
python -m unittest discover -s tests -p test_studies.py   # planned studies, stdlib only
node tests/builder.test.cjs                      # builder validator == spec.py
python tools/build_site.py && node tests/atlas_ui.test.cjs _site/atlas/index.html
python tools/check_site.py _site
```

Previously completed: 17 new structural/geometry checks, three legacy regressions, five frontier checks. The current JS harness checks appended rows, filters, span toggle, full hover, six-highlight selection and paired viewer construction. It uses a mocked DOM, not full browser visual QA.

Twelve native replay metric checks passed; all media references exist. The deployed site has been checked in a browser for each Phase 3–4 change; `atlas_ui.test.cjs` itself uses a mocked DOM. Do not claim an end-to-end browser test that did not occur.

Confidence is qualitative, not a fabricated probability:
- Stronger: tested structural equations and geometry contracts.
- Conditional: numerical repeatability of particular verified cases.
- Limited: broad nominal-setting stability and model form for soft sheets.
- Unestablished: experimental thrust/torque accuracy of the extension.

## 14. Known issues and next useful work

1. **Unresolved soft wings:** diagnose a small stratified set. Compare 50/100/200 steps/cycle at fixed geometry/material; inspect histories and stabilization sensitivity. Extra cycles address unfinished settling, not immediate blow-up.
2. **Model form:** large-angle UVLM, straight-chord pitch, rod attachment, anisotropy and material uncertainty require validation. Do not use damping to force agreement.
3. **Geometry rejection:** folded projected planforms and +/-90° section angles need a frame audit. Explicit reference dimensions may remove one error, not validate geometry.
4. **Selection bias:** rerun shapes came from old frontiers; verified-only comparisons exclude many bare sheets. This is not a completed spanwise optimizer.
5. **Future atlas reproducibility:** export exact geometry, actual dt/cycles, mesh/wake, material, motion and code identity in a compact replay manifest. The old export cannot supply missing data retroactively.
6. **Stale template metadata:** sections_case updates sections but can leave inherited case.geometry, requested_sections, aliases and span summaries from 7657. Runner geometry/active-span metrics use case.sections; consumers must not trust stale summaries. Rebuild metadata before exposing it as authoritative.
7. **Cache hardening:** fingerprints do not cover every helper/dependency/environment or changes to model.py/orchestration. Add complete identities before broad reuse. Failed attempts count as completed; deliberate retries should use separate plan/identity.
8. **Original database import:** assumes base source mesh from plan. Validate numerics level, source key, actual settings and duplicate handling if databases arrive.
9. **GUI import completeness:** importer carries summaries/traces but not every physical/provenance field needed for generalized replay. Do not default unknown future imports to 0.5 mm.
10. **Publisher consolidation:** span_atlas.py and elastic_atlas.py predate `atlas/data/`; planned studies are the supported path for new results. Retire or port the old publishers before using them again.
11. **Coordinator failures:** worker/export errors can abort while progress still says running. Check logs/processes, not only the flag. Saved cases remain recoverable. No comprehensive multi-coordinator lock exists.
12. **Campaign databases:** the rod and plate `campaign.sqlite` files are still not on this machine; the evolution GIFs for original campaign winners need them. Planned search winners do not.
13. **Git:** `outputs/` is never pushed; the allowlist `.gitignore` must list any new top-level path.

Recommended scientific next step: representative bare/rod cases spanning verified, unresolved and geometry-limit outcomes; controlled timestep/mesh/stabilization checks; then static deflection and tank comparison. Do not launch another large optimizer merely because it can generate numbers.

## 15. Fresh-session checklist

- Confirm the working directory is the Git checkout and the installed solver path.
- Read the current request, [AGENTS.md](../AGENTS.md), this guide and the relevant source.
- Inspect saved plans/progress and `studies/*/status.json`; do not restart completed work.
- State the engineering question each new simulation answers; prefer a planned study.
- Preserve known settings; use the approved fallback only where originals are missing.
- Run the relevant tests or UI/media checks, and report what was actually checked.
- Keep failures saved and unranked, and retain provenance.
- Distinguish observation, numerical inference, assumption and experiment.

## 16. Related reading

- [Agent entry point](../AGENTS.md) and [contributor rules](../CONTRIBUTING.md)
- [Planned studies](studies.md)
- [Spanwise equations and validation](spanwise-elasticity.md)
- [Coordinate search method](coordinate-search.md)
- [Restructure plan](restructure-plan.md)
- [History](history/): the 19 November handoff, the frontier study record, the rigid-app README and results

Primary background already used: Causin, Gerbeau & Nobile (2005), DOI 10.1016/j.cma.2004.12.005, on partitioned FSI added-mass effects; TU Delft's Euler–Bernoulli formulation; discrete-elastic-rod literature as geometric motivation. These support principles, not physical validation of this implementation.
