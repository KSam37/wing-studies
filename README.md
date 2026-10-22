# Wing Studies

Private Windows research app for Ptera-based wing geometry studies in water. Set up chord-based shape sweeps or custom single wings, compare thrust to root roll moment, inspect native time histories and animations, and browse a persistent master run catalog with filtered 3D comparisons.

## Daily use

| Open this | For |
| --- | --- |
| **Run Wing Studies.cmd** | Create and run wing studies |
| **Run Master Catalog.cmd** | Filter and compare every recorded wing |
| **Open Master Excel.cmd** | Open the two-sheet master workbook |
| **Open Results.cmd** | Browse saved studies and outputs |
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

The repository includes the app, tests, dependency lock, Windows launchers, and an exact Ptera commit reference. **Environments, simulation results, master Excel/database, caches, and old application ZIPs are ignored by Git.** Each collaborator starts with an independent catalog. Share completed results separately by copying the relevant `outputs/studies/<study>` folders and `outputs/provenance`; the app imports those runs into the recipient's catalog. Do not merge two SQLite databases. Global case numbers belong to each catalog and can differ between collaborators; shared study/local case paths and simulation signatures preserve provenance.

`tools/requirements-windows.lock` records the tested runtime package versions. `tools/ptera-source.json` records the exact upstream commit, verified archive checksum, and native file hashes. Setup uses the pinned source because the published 5.1.0 package metadata excludes Python 3.14 while this upstream commit explicitly supports it. Setup never modifies an unrelated Python environment; `--use-python <interpreter>` is an optional advanced path that only registers an already matching environment after verification.

For the complete study workflow, output definitions, filtering, and modeling assumptions, read [the app guide](WingStudy/README.md).

## Model limits and provenance

New runs model one isolated rigid wing with prescribed motion, positive forward speed, water density and viscosity, and selectable UVLM wake settings. Estimated pair thrust is twice the isolated single-wing value, without wing interaction. The primary shape score is mean thrust divided by sampled peak absolute root fluid roll moment; it is not a motor torque or structural qualification. Native simulations do not model membrane bending compliance, wing inertia, drivetrain loads, or zero-inflow test stands.

Ptera is maintained by Cameron Urban and contributors under the licenses in the pinned upstream [PteraSoftware repository](https://github.com/camUrban/PteraSoftware/tree/17a98a10f724a743f1b5f1597579b24edf95cf2d). The companion is a separate research application. Third-party license notices remain with their packages. This repository is private; no public distribution license for the companion is granted here.

## Shared simulation results

The repository includes `outputs/studies/`, `outputs/provenance/`, `outputs/master_runs.xlsx`, and `outputs/master_runs.sqlite3`. Launch **Run Master Catalog.cmd** after setup to browse the compiled results and open original case outputs. Plots, animations, cutting profiles and recorded case inputs remain under their original study/case folders.

The current shared snapshot contains 444 parameter sets and 446 study/case occurrences, including the completed 185-case study `20261021-203041-110378_study`. The older `20261021-143038-203113_sweep-75` retains its unfinished status (30 of 75 cases); its available records are included. Recorded failures and repeatability flags remain visible. Generated comparison folders are included. This adds about 2 GB to the initial repository download. Old software archives, environments, caches, logs and temporary files remain excluded.
