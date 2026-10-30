# Wing Studies

Windows app for native Ptera wing studies in water. The default adaptive mode explores mean single-wing thrust versus peak absolute wing-root torque, with no torque ceiling. Each span starts from one truncated triangular seed (minimum positive chord 0.01 m; outboard zero suffixes may shorten active span). Coordinate perturbations branch from nondominated tradeoffs instead of maximizing thrust/torque. The existing grid / saved-wing span workflow is also available.

Pareto search retains every evaluated result, reuses matching simulations, and prioritizes frontier extremes and gaps when selecting parents. **Frontier parents per pass** controls breadth; **Frontier sampling resolution (%)** spaces near-identical parent metrics within a poll batch without deleting results. Each parent has independent step sizes; unsuccessful polls shrink its steps. Optional coordinated polls vary the entire wing, taper, and smooth chord regions. Progress PNG/CSV reports normalized hypervolume with a common automatic reference recomputed over the complete history; that reference never limits the simulations. New-simulation and candidate budgets remain shared across the span linspace. Selected-wing evolution GIFs follow actual parent ancestry. The resulting frontier is a local, finite-budget sample, not a guarantee of global optimality.

Editable Pareto defaults: four total spans from 0.4–0.8 m, eight chord nodes, 0.20 m seed/root maximum width, 0.01 m seed tip/minimum chord, and 500 new simulations. Motion defaults to 1 Hz and −26° to +34°. Root and tip can vary within the chosen geometry bounds. The optional legacy grid mode retains its separate root-moment limit.

## Daily use

| Open this | For |
| --- | --- |
| **Run Wing Studies.cmd** | Create and run wing studies |
| **Run Master Catalog.cmd** | Open saved studies in the comparison view |
| **Open Master Excel.cmd** | Open the two-sheet master workbook |
| **Setup Windows.cmd** | First setup, or a dependency update |

`outputs/studies` holds your runs; `outputs/master_runs.xlsx` is the generated workbook and `outputs/master_runs.sqlite3` is the durable catalog. Keep these together. `outputs/provenance` retains compact solver/dependency evidence for old runs, so obsolete application ZIPs can be removed without losing reuse checks. Verification reports and recovery backups live in `outputs/maintenance`; temporary authoring files live in `outputs/cache`. Superseded releases, the unused partial environment, and old ZIP build tools are recoverable in `outputs/archive`; they are not used by the application.

The `tools` folder contains setup code, pinned dependencies, checks and the original class-example launcher. `WingStudy` is app source, `PteraSoftware` is the pinned solver, and `tests` contains setup tests. These folders stay separate from daily-use launchers.

## First setup on Windows

1. Install **64-bit Python 3.14** from [python.org](https://www.python.org/downloads/windows/) and include the Python launcher. Python 3.14.2 is the tested version. An existing Ptera installation is not required.
2. Accept the repository invitation and download this private repository. With Git, use `git clone --recurse-submodules https://github.com/KSam37/wing-studies.git`. Alternatively, GitHub's **Code â†’ Download ZIP** works: extract the source once; setup fetches the pinned Ptera source automatically. You no longer need a separately built application ZIP.
3. Double-click **Setup Windows.cmd**. Internet access is needed the first time to install the pinned dependencies and, if needed, the official Ptera source. Leave the window open until it says **Ready**.
4. Double-click **Run Wing Studies.cmd** for the study editor, or **Run Master Catalog.cmd** for compiled results. Keep the terminal open while using the app. A browser opens locally; simulations and results stay on your computer.
5. Optional: double-click **tools/Check Installation.cmd** to verify the solver source, installed package versions, dependency consistency, and application regression checks.

The first setup downloads the scientific libraries and can take several minutes. Later launches reuse the environment. It lives under `%LOCALAPPDATA%\WingStudies\environments`, outside OneDrive and outside Git. Paths are derived from this checkout: there are no user-specific interpreter paths. If you move the folder, run Setup Windows.cmd again. Run files belong to the checkout, so keep its `outputs` folder when moving it.

## Updating and collaborating

Use `git pull --recurse-submodules`, then run Setup Windows.cmd if prompted or if the requirements changed. For a source download, extract the new version and retain your existing `outputs` folder. Changes to WingStudy source can be committed and pushed normally. Ptera itself is pinned as a submodule; avoid editing its native solver in this project.

The repository includes the app, tests, dependency lock, Windows launchers, an exact Ptera commit reference, saved study outputs, and the current master Excel/database. Environments, caches, maintenance trials and old application ZIPs remain excluded. Each collaborator should keep local results backed up before pulling an updated catalog snapshot. Do not merge two SQLite databases; share additional runs through `outputs/studies/<study>` and `outputs/provenance` so the app can import them. Global case numbers belong to each catalog and can differ between collaborators; shared study/local case paths and simulation signatures preserve provenance.

`tools/requirements-windows.lock` records the tested runtime package versions. `tools/ptera-source.json` records the exact upstream commit, verified archive checksum, and native file hashes. Setup uses the pinned source because the published 5.1.0 package metadata excludes Python 3.14 while this upstream commit explicitly supports it. Setup never modifies an unrelated Python environment; `--use-python <interpreter>` is an optional advanced path that only registers an already matching environment after verification.

For the complete study workflow, output definitions, filtering, and modeling assumptions, read [the app guide](WingStudy/README.md).

## Model limits and provenance

New runs default to one isolated rigid wing with prescribed motion, positive forward speed, water density and viscosity, and selectable UVLM wake settings. Native aeroelasticity is optional. Estimated pair thrust is twice the isolated single-wing value, without wing interaction. Adaptive searches maximize mean thrust at each of a range of available peak root torques, sharing evaluated designs across seeds; thrust/torque is a reported ratio, not the sole objective. Root fluid moment is not motor torque or structural qualification. The rigid model omits wing inertia, drivetrain loads, membrane compliance and zero-inflow test stands.

Ptera is maintained by Cameron Urban and contributors under the licenses in the pinned upstream [PteraSoftware repository](https://github.com/camUrban/PteraSoftware/tree/17a98a10f724a743f1b5f1597579b24edf95cf2d). The companion is a separate research application. Third-party license notices remain with their packages. This repository is private; no public distribution license for the companion is granted here.

## Shared simulation results

The repository includes `outputs/studies/`, `outputs/provenance/`, `outputs/master_runs.xlsx`, and `outputs/master_runs.sqlite3`. Launch **Run Master Catalog.cmd** after setup to browse the compiled results and open original case outputs. Plots, animations, cutting profiles and recorded case inputs remain under their original study/case folders.

The previous master is preserved in `outputs/master_runs_old.xlsx` and `outputs/master_runs_old.sqlite3`: 1,533 parameter sets and 1,536 study/case occurrences. The fresh `master_runs.xlsx` / `master_runs.sqlite3` receive new studies. Choose **Master comparison** in the comparison view and toggle **Current** and **Old** independently. Exact cached simulations remain reusable from either catalog. Keep both catalog pairs and the study folders together. Unfinished, cancelled and failed runs retain their status. Saved results add several gigabytes to the initial download; environments, caches and temporary files remain excluded.


The torque–thrust comparison defaults to the highest observed mean thrust in each editable torque band. Empty bands are not filled, and each winner reports the number of evaluated designs in its band. The full observed Pareto frontier remains selectable. PNG/CSV exports preserve actual torque, span, band membership, and winner flags; grouping never imposes a simulation torque ceiling. Initial adjustment changes apply when rebuilding per-chord rows; the preview reports the effective row step sizes.


Adaptive studies support **Parallel Ptera processes** (GUI default 4; 1 runs serially). Independent span seeds and neighbor cases run in isolated processes. One coordinator reserves unique case IDs, checks completed and in-flight geometries, enforces shared budgets, and writes the catalog and combined histories. Completed cases save while other cases are running; poll responses are fed back in request order. Temporary per-process output staging is removed after completion. Stop study ends the worker process tree on Windows. More processes increase memory use, and speedup depends on solver resolution and animation rendering.

See [OPTIMIZATION_STRATEGY.md](OPTIMIZATION_STRATEGY.md) for the current search policy, seed families, reuse rules, and validation limits.

Torque-range studies save `comparisons/torque_curve.csv` and `torque_targets.json`. The primary plot shows the current best feasible wings across targets; its available-torque selector reports the corresponding winner. Native time plots and animation remain unchanged.
